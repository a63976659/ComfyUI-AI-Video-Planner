"""历史规划、计划文件及可分享的数据包；所有删除均需一次性确认凭据。"""
import asyncio
import copy
import hashlib
import json
import os
import re
import secrets
import shutil
import threading
import time
from pathlib import Path, PurePosixPath

from aiohttp import web
from .计划路由 import 计划根, 安全名, _计划元信息
try:
    from ..规划.项目存储 import 读JSON, 写JSON, _是链接
except ImportError:
    from 规划.项目存储 import 读JSON, 写JSON, _是链接


def 去凭据(value):
    if isinstance(value, dict):
        return {k: 去凭据(v) for k, v in value.items() if k.lower() not in
                {"api_key", "apikey", "token", "凭据摘要", "任务引用", "规划任务引用"}}
    if isinstance(value, list):
        return [去凭据(v) for v in value]
    return value


class 数据管理:
    def __init__(self, manager, plans=None):
        self.manager = manager
        self.plans = Path(plans or 计划根()).resolve()
        self.plans.mkdir(parents=True, exist_ok=True)
        self.确认表 = {}
        self.导入错误 = {}
        self.lock = threading.RLock()

    def 导入目录(self, kind):
        if kind not in ("计划", "规划"):
            raise ValueError("数据类型不合法")
        root = self.plans if kind == "计划" else self.manager.存储.root.resolve()
        if root.exists() and _是链接(root):
            raise ValueError("导入目录不能是链接")
        root.mkdir(parents=True, exist_ok=True)
        return root

    def 计划路径(self, name):
        clean = 安全名(name)
        if not clean or clean != name:
            raise ValueError("计划名称不合法")
        path = self.plans / (clean + ".json")
        if path.exists() and _是链接(path) or path.resolve().parent != self.plans:
            raise ValueError("计划文件路径不安全")
        return path

    def 项目(self, key):
        project = self.manager.存储.项目(key)
        if not project.记录 or project.记录.get("项目") != key or _是链接(project.目录):
            raise ValueError("规划存档不存在或不安全")
        return project

    def 活动项目(self, project):
        if any(j.项目 and j.项目.id == project.id and j.状态 not in {"completed", "failed", "cancelled"}
               for j in list(self.manager.任务.values())):
            return True
        return any(读JSON(p).get("状态") not in {"completed", "failed", "cancelled"}
                   for p in project.路径("运行记录").glob("任务-*.json"))

    def 分集(self, project):
        path = project.路径("阶段成果", "storyboards.json")
        episodes = 读JSON(path).get("episodes", []) if path.exists() else project.记录.get("分集", [])
        return sorted(episodes, key=lambda e: e["集号"])

    def 授权读取(self, key, number=None):
        # 只创建已结束的读取记录，绝不启动模型或复用远端访问凭据。
        from .规划任务路由 import 规划任务
        project = self.项目(key)
        if self.活动项目(project):
            raise ValueError("规划尚在运行或等待恢复，请完成或停止后导入")
        episodes = self.分集(project)
        if not episodes:
            raise ValueError("该规划尚无可导入的分镜结果")
        number = episodes[0]["集号"] if number is None else number
        if isinstance(number, str) and number.isdecimal():
            number = int(number)
        if isinstance(number, bool) or not isinstance(number, int) or number not in {e["集号"] for e in episodes}:
            raise ValueError("请选择该规划中已保存的分集")
        first = copy.deepcopy(project.读分集(number))
        if not isinstance(first.get("segments"), list) or not first["segments"]:
            raise ValueError("规划没有有效分镜")
        first["分集"] = copy.deepcopy(episodes)
        meta = first.setdefault("规划资料", {})
        meta.update(项目=key, 集号=number, 分集索引=episodes,
                    全剧时长=sum(e.get("时长", 0) for e in episodes))
        if "生成完成" in meta:
            meta["全剧生成完成"] = project.记录.get("全剧生成完成") is True
        for field, filename in (("全剧资料", "全剧规划.json"), ("全剧验收", "验收记录.json")):
            path = project.路径("全剧资料", filename)
            if path.exists():
                value = 读JSON(path)
                meta[field] = value[-1] if field == "全剧验收" and isinstance(value, list) and value else value
        if "全剧验收" in project.记录:
            meta["全剧验收"] = project.记录["全剧验收"]
        token = secrets.token_urlsafe(32)
        job = 规划任务(secrets.token_hex(16), hashlib.sha256(token.encode()).digest(), None, {})
        job.项目, job.状态, job.结果, job.结束时间 = project, "completed", first, time.monotonic()
        project.写任务(job)
        self.manager.任务[job.id] = job
        stages = project.阶段快照()
        ref = {"id": job.id, "token": token, "stages": stages, "status": "completed"}
        meta.update(任务引用={"id": job.id, "token": token}, 阶段成果=stages)
        prepared = 读JSON(project.路径("原始资料", "输入.json"))
        return {"结果": first, "brief": prepared.get("brief", {}), "引用": ref,
                "素材": prepared.get("素材", []), "素材理解": prepared.get("素材理解", {})}

    def 导出规划(self, key):
        project = self.项目(key)
        if self.活动项目(project):
            raise ValueError("规划尚在运行或等待恢复，请完成或停止后另存为")
        files = {}
        # 分享结果与只读阶段资料，不分享运行凭据、API 配置及继续生成的检查点。
        for path in project.目录.rglob("*.json"):
            rel = path.relative_to(project.目录).as_posix()
            if rel.split("/")[0] not in {"项目记录.json", "原始资料", "阶段成果", "章节理解", "分集规划", "全剧资料"}:
                continue
            if any(_是链接(p) for p in [path, *path.parents] if p != project.目录.parent):
                raise ValueError("规划含链接，不能导出")
            files[rel] = 去凭据(读JSON(path))
        return {"类型": "规划", "数据包版本": 1, "文件": files}

    def 导出(self, kind, key):
        if kind == "规划":
            return self.导出规划(key)
        if kind != "计划":
            raise ValueError("数据类型不合法")
        plan = 读JSON(self.计划路径(key))
        _计划元信息(plan)
        keys = set()
        def collect(value):
            if isinstance(value, dict):
                meta = value.get("规划资料")
                if isinstance(meta, dict) and meta.get("项目"):
                    keys.add(meta["项目"])
                if isinstance(value.get("分集"), dict) and value.get("项目"):
                    keys.add(value["项目"])
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)
        collect(plan.get("数据", {}).get("剪辑草稿", {}))
        collect(plan.get("数据", {}).get("分集编辑", {}))
        associated = [self.导出规划(key) for key in sorted(keys)]
        return {"类型": "计划", "数据包版本": 1, "名称": key, "计划": 去凭据(plan), "关联规划": associated}

    def 校验规划包(self, package):
        if not isinstance(package, dict):
            raise ValueError("关联规划必须是对象")
        files = package.get("文件")
        if not isinstance(files, dict) or "项目记录.json" not in files or "原始资料/输入.json" not in files:
            raise ValueError("规划数据包缺少项目记录或原始资料")
        for name, value in files.items():
            parts = PurePosixPath(name).parts
            if (not parts or "\\" in name or ":" in name
                or PurePosixPath(name).is_absolute() or ".." in parts or name != PurePosixPath(name).as_posix()
                or parts[0] not in {"项目记录.json", "原始资料", "阶段成果", "章节理解", "分集规划", "全剧资料"}
                or not name.endswith(".json")):
                raise ValueError("规划数据包含不合法文件")
            if not isinstance(value, dict) and not (name == "全剧资料/验收记录.json" and isinstance(value, list)):
                raise ValueError("规划数据文件结构非法")
        record = files["项目记录.json"]
        if record.get("格式") != 1 or not isinstance(record.get("成果阶段", {}), dict):
            raise ValueError("规划数据格式不支持")
        stage = files.get("阶段成果/storyboards.json", {})
        episodes = stage.get("episodes", [])
        if not isinstance(episodes, list) or not episodes:
            raise ValueError("规划包没有分集分镜")
        for e in episodes:
            number = e.get("集号") if isinstance(e, dict) else None
            if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= 120:
                raise ValueError("规划分集编号不合法")
            data = files.get(f"分集规划/第{number:03d}集/分镜结果.json", {})
            if not isinstance(data.get("segments"), list) or not data["segments"]:
                raise ValueError(f"规划包缺少第{number}集分镜")
        return files

    def 导入规划包(self, package):
        files = self.校验规划包(package)
        record = files["项目记录.json"]
        key = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
        root = self.manager.存储.root
        root.mkdir(parents=True, exist_ok=True)
        staging = root / (".导入-" + secrets.token_hex(16))
        staging.mkdir()
        try:
            for name, value in files.items():
                value = 去凭据(value)
                if isinstance(value, dict) and isinstance(value.get("规划资料"), dict):
                    value["规划资料"]["项目"] = key
                if name == "项目记录.json":
                    value.update(项目=key, 状态="完成", 导入时间=time.time(), 来源项目=record.get("项目"))
                写JSON(staging.joinpath(*PurePosixPath(name).parts), value)
            os.replace(staging, root / key)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        return key

    def 回滚导入(self, keys):
        # 仅删除本次新建的随机项目，不触及导入前已有存档。
        root = self.manager.存储.root.resolve()
        for key in keys:
            path = root / key
            if not re.fullmatch(r"[a-f0-9]{64}", key) or path.resolve().parent != root or _是链接(path):
                raise ValueError("导入回滚路径不安全")
            if path.exists():
                shutil.rmtree(path)
            for job_id, job in list(self.manager.任务.items()):
                if job.项目 and job.项目.id == key:
                    del self.manager.任务[job_id]

    def 导入包(self, package, fallback, 完成=None):
        if not isinstance(package, dict):
            raise ValueError("数据文件顶层必须是对象")
        kind = package.get("类型", "计划" if "数据" in package else "")
        if "类型" in package and package.get("数据包版本") != 1:
            raise ValueError("数据包版本不支持")
        if kind == "规划":
            key = self.导入规划包(package)
            try:
                if 完成:
                    完成()
            except Exception:
                self.回滚导入([key])
                raise
            return kind, key
        if kind != "计划":
            raise ValueError("无法识别计划或规划数据文件")
        plan = copy.deepcopy(package.get("计划", package))
        _计划元信息(plan)
        if not isinstance(plan.get("数据"), dict):
            raise ValueError("计划没有数据字段")
        name = 安全名(package.get("名称") or fallback)
        if not name:
            raise ValueError("计划名称不合法")
        archives = package.get("关联规划", [])
        if not isinstance(archives, list):
            raise ValueError("关联规划字段非法")
        sources = []
        for archive in archives:
            files = self.校验规划包(archive)
            source = files["项目记录.json"].get("项目")
            if not isinstance(source, str) or source in sources:
                raise ValueError("关联规划来源标识缺失或重复")
            sources.append(source)
        candidate, n = name, 1
        while self.计划路径(candidate).exists():
            n += 1
            candidate = name[:90] + f" ({n})"
        created, mapping = [], {}
        plan_path = self.计划路径(candidate)
        plan_written = False
        try:
            for source, archive in zip(sources, archives):
                key = self.导入规划包(archive)
                created.append(key)
                mapping[source] = (key, self.授权读取(key))
            def rebind(value):
                if isinstance(value, dict):
                    meta = value.get("规划资料")
                    if isinstance(meta, dict) and meta.get("项目") in mapping:
                        key, loaded = mapping[meta["项目"]]
                        meta.update(项目=key, 任务引用=loaded["结果"]["规划资料"]["任务引用"],
                                    阶段成果=loaded["引用"]["stages"], 分集索引=loaded["结果"]["规划资料"]["分集索引"])
                    if isinstance(value.get("分集"), dict) and value.get("项目") in mapping:
                        value["项目"] = mapping[value["项目"]][0]
                    for child in value.values():
                        rebind(child)
                elif isinstance(value, list):
                    for child in value:
                        rebind(child)
            rebind(plan["数据"])
            写JSON(plan_path, plan)
            plan_written = True
            if 完成:
                完成()
        except Exception:
            if plan_written:
                plan_path.unlink()
            self.回滚导入(created)
            raise
        return kind, candidate

    def 扫描导入(self):
        errors = []
        with self.lock:
            for kind in ("计划", "规划"):
                root = self.导入目录(kind)
                for path in root.glob("*.json"):
                    if _是链接(path):
                        continue
                    signature = (path.stat().st_size, path.stat().st_mtime_ns)
                    previous = self.导入错误.get(str(path))
                    if previous and previous[0] == signature:
                        errors.append({"文件": path.name, "说明": previous[1]})
                        continue
                    try:
                        with path.open(encoding="utf-8-sig") as f:
                            package = json.load(f)
                        actual = package.get("类型", "计划" if "数据" in package else "") if isinstance(package, dict) else ""
                        if actual != kind:
                            raise ValueError(f"请把文件放入{actual or kind}存储文件夹")
                        if path.parent == self.plans and "类型" not in package:
                            # 本地计划及直接复制的原生计划已经是列表可读格式，不再次导入。
                            _计划元信息(package)
                            if not isinstance(package.get("数据"), dict):
                                raise ValueError("计划没有数据字段")
                            self.导入错误.pop(str(path), None)
                            continue
                        # 文件复制完成前解析失败不会写入任何结果；改动后自动重试。
                        done = path.parent / "已导入"
                        if done.exists() and _是链接(done):
                            raise ValueError("已导入目录不能是链接")
                        done.mkdir(exist_ok=True)
                        destination = done / (path.stem + "-" + secrets.token_hex(4) + ".json")
                        # 先归档源包，使同目录计划可以沿用原文件名。失败恢复原件，不覆盖旧计划。
                        os.replace(path, destination)
                        try:
                            self.导入包(package, path.stem)
                        except Exception:
                            if not path.exists():
                                os.replace(destination, path)
                            raise
                        self.导入错误.pop(str(path), None)
                    except (OSError, ValueError, KeyError, TypeError) as e:
                        self.导入错误[str(path)] = (signature, str(e))
                        errors.append({"文件": path.name, "说明": str(e)})
        return errors

    def 列表(self):
        errors = self.扫描导入()
        plans = []
        for path in self.plans.glob("*.json"):
            if _是链接(path):
                continue
            try:
                plan = 读JSON(path)
                if not isinstance(plan, dict) or "类型" in plan or not isinstance(plan.get("数据"), dict):
                    continue
                _计划元信息(plan)
            except (OSError, ValueError, KeyError, TypeError):
                continue
            plans.append({"id": path.stem, "名称": path.stem, "大小": path.stat().st_size,
                          "更新时间": path.stat().st_mtime, "运行中": False})
        projects = []
        for path in self.manager.存储.root.glob("[a-f0-9]*"):
            if not re.fullmatch(r"[a-f0-9]{64}", path.name) or _是链接(path):
                continue
            try:
                project = self.项目(path.name)
                source = 读JSON(project.路径("原始资料", "输入.json"))
                episodes = self.分集(project)
                busy = self.活动项目(project)
                projects.append({"id": project.id, "名称": source.get("brief", {}).get("主题") or source.get("brief", {}).get("详细内容", "")[:60] or "未命名规划",
                                 "集数": len(episodes), "分集": episodes, "更新时间": project.记录.get("更新时间", project.记录.get("创建时间", 0)),
                                 "状态": project.记录.get("状态", ""), "运行中": busy, "可导入": bool(episodes) and not busy})
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return {"计划": sorted(plans, key=lambda x: x["更新时间"], reverse=True),
                "规划": sorted(projects, key=lambda x: x["更新时间"], reverse=True), "导入错误": errors,
                "目录": {kind: str(self.导入目录(kind)) for kind in ("计划", "规划")}}

    def 准备清理(self, kind, ids):
        if kind not in {"计划", "规划"} or not isinstance(ids, list) or not ids or not all(isinstance(x, str) for x in ids):
            raise ValueError("请选择要清理的数据")
        paths = []
        for key in set(ids):
            if kind == "规划":
                project = self.项目(key)
                if self.活动项目(project):
                    raise ValueError("运行中或等待恢复的规划不能清理")
                path = project.目录
                if any(_是链接(p) for p in path.rglob("*")):
                    raise ValueError("规划含链接，不能清理")
            else:
                path = self.计划路径(key)
            if not path.exists():
                raise ValueError("记录已变化，请刷新列表")
            paths.append((key, path.stat().st_mtime_ns))
        now = time.monotonic()
        self.确认表 = {k: v for k, v in self.确认表.items() if v[2] > now}
        token = secrets.token_urlsafe(24)
        self.确认表[token] = (kind, paths, now + 120)
        return {"确认凭据": token, "数量": len(paths)}

    def 清理(self, token):
        item = self.确认表.pop(token, None)
        if not item or item[2] < time.monotonic():
            raise ValueError("二次确认已失效，请重新选择并确认")
        kind, paths, _ = item
        # 全量复核后再删除，活动任务及目录变化不越过二次确认。
        resolved = []
        for key, stamp in paths:
            check = self.准备清理(kind, [key])
            self.确认表.pop(check["确认凭据"], None)
            path = self.项目(key).目录 if kind == "规划" else self.计划路径(key)
            if path.stat().st_mtime_ns != stamp:
                raise ValueError("记录已变化，未清理，请重新确认")
            resolved.append((key, path))
        removed = []
        for key, path in resolved:
            if kind == "规划":
                shutil.rmtree(path)
                for job_id, job in list(self.manager.任务.items()):
                    if job.项目 and job.项目.id == key:
                        del self.manager.任务[job_id]
            else:
                path.unlink()
            removed.append(key)
        return {"已清理": removed}


def 注册数据管理路由(routes, manager):
    service = 数据管理(manager)

    async def execute(fn, *args):
        try:
            def locked():
                with service.lock:
                    return fn(*args)
            result = await asyncio.to_thread(locked)
            return web.json_response(result, headers={"Cache-Control": "no-store"})
        except (OSError, ValueError, KeyError, TypeError) as e:
            return web.json_response({"error": str(e)}, status=400)

    @routes.get("/lvp/data/list")
    async def listing(request):
        return await execute(service.列表)

    @routes.get("/lvp/data/planning/load")
    async def load(request):
        return await execute(service.授权读取, request.query.get("id", ""), request.query.get("episode"))

    @routes.get("/lvp/data/export")
    async def export(request):
        return await execute(service.导出, request.query.get("type"), request.query.get("id"))

    @routes.post("/lvp/data/delete/prepare")
    async def prepare(request):
        try:
            body = await request.json()
            return await execute(service.准备清理, body.get("类型"), body.get("ids"))
        except (ValueError, AttributeError):
            return web.json_response({"error": "清理请求非法"}, status=400)

    @routes.post("/lvp/data/delete/confirm")
    async def confirm(request):
        try:
            body = await request.json()
            return await execute(service.清理, body.get("确认凭据", ""))
        except (ValueError, AttributeError):
            return web.json_response({"error": "确认请求非法"}, status=400)

    @routes.post("/lvp/data/folder")
    async def folder(request):
        try:
            body = await request.json()
            path = service.导入目录(body.get("类型"))
            if os.name == "nt":
                os.startfile(str(path))
            return web.json_response({"目录": str(path)})
        except (OSError, ValueError, AttributeError) as e:
            return web.json_response({"error": str(e)}, status=400)

    return service
