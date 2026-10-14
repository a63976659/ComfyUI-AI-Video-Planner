# -*- coding: utf-8 -*-
"""本机规划检查点；所有路径由内部标识产生，模型密钥不写入项目。"""
import asyncio
import json
import os
import re
import secrets
import shutil
import time
from pathlib import Path
from .规划契约 import 规划预算耗尽, 指纹

阶段名称 = {"analysis": "分析素材", "episodes": "规划剧集", "references": "生成参考", "storyboards": "生成分镜"}


def 写JSON(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    resolved = path.resolve()
    if path.is_symlink() or not resolved.is_relative_to(path.parent.resolve()):
        raise ValueError("规划存储路径越界")
    temp = path.with_name(path.name + "." + secrets.token_hex(8) + ".临时")
    try:
        with temp.open("x", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def 读JSON(path):
    if path.is_symlink():
        raise ValueError("规划存档不安全")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _是链接(path):
    # Windows 联接点及其它重解析点不能递归删除；兼容 Python 3.10/3.11。
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)


class 项目存储:
    def __init__(self, root=None):
        self.root = Path(root or Path(__file__).resolve().parents[1] / "计划数据" / "长剧项目").resolve()

    def 标识(self, prepared, identity):
        return 指纹({"格式": 1, "输入": prepared, "运行版本": identity})

    def 清理旧项目(self, 保留=()):
        """兼容旧调用方的显式清理工具；新建、恢复及读取均不调用。"""
        removed, errors = [], []
        if not self.root.exists():
            return removed, errors
        protected = set(保留)
        for path in self.root.iterdir():
            if (not re.fullmatch(r"[a-f0-9]{64}", path.name) or path.name in protected
                    or _是链接(path) or not path.is_dir()):
                continue
            # 删除前核对最终绝对路径；不递归进入链接/联接点或其它目录。
            target = path.resolve()
            if target.parent != self.root or not target.is_relative_to(self.root):
                continue
            if not (path / "项目记录.json").exists():
                continue
            try:
                record = 读JSON(path / "项目记录.json")
                if record.get("格式") != 1 or record.get("项目") != path.name:
                    continue
                tasks = [读JSON(p) for p in (path / "运行记录").glob("任务-*.json")]
                if tasks:
                    latest = max(tasks, key=lambda t: t.get("更新时间", 0))
                    if latest.get("状态") not in ("completed", "failed", "cancelled"):
                        continue
                elif record.get("状态") not in ("完成", "失败"):
                    continue
                unsafe = False
                for directory, folders, files in os.walk(target, followlinks=False):
                    if any(_是链接(Path(directory) / name) for name in [*folders, *files]):
                        unsafe = True
                        break
                if unsafe:
                    continue
                shutil.rmtree(target)
                removed.append(path.name)
            except (OSError, ValueError, TypeError):
                errors.append(path.name)
        return removed, errors

    def 打开(self, prepared, identity, *, 新建=False):
        input_key = self.标识(prepared, identity)
        key = 指纹({"输入": input_key, "批次": secrets.token_hex(16)}) if 新建 else input_key
        project = 规划项目(self, key)
        if not project.记录路径.exists():
            写JSON(project.路径("原始资料", "输入.json"), prepared)
            写JSON(project.记录路径, {"格式": 1, "项目": key, "输入标识": input_key, "运行版本": identity,
                                     "创建时间": time.time(), "累计调用": 0, "调用上限": 600,
                                     "状态": "等待", "全剧生成完成": False, "分集": []})
        project.记录 = 读JSON(project.记录路径)
        return project

    def 项目(self, key):
        return 规划项目(self, key)

    def 任务记录(self):
        if not self.root.exists():
            return []
        records = []
        for path in self.root.glob("*/运行记录/任务-*.json"):
            if not path.resolve().is_relative_to(self.root):
                continue
            try:
                data = 读JSON(path)
                if data.get("格式") == 1:
                    records.append(data)
            except (OSError, ValueError, TypeError):
                continue
        return sorted(records, key=lambda x: x.get("更新时间", 0), reverse=True)


class 规划项目:
    def __init__(self, store, key):
        if not re.fullmatch(r"[a-f0-9]{64}", key):
            raise ValueError("规划项目标识不合法")
        self.store, self.id = store, key
        self.目录 = store.root / key
        if not self.目录.resolve().is_relative_to(store.root) or self.目录.is_symlink():
            raise ValueError("规划项目目录越界")
        self.记录路径 = self.路径("项目记录.json")
        self.记录 = 读JSON(self.记录路径) if self.记录路径.exists() else {}

    def 路径(self, *parts):
        path = self.目录.joinpath(*parts)
        if self.目录.is_symlink() or not self.目录.resolve().is_relative_to(self.store.root) or not path.resolve().is_relative_to(self.目录.resolve()):
            raise ValueError("规划项目文件越界")
        return path

    def 更新(self, **values):
        self.记录.update(values)
        self.记录["更新时间"] = time.time()
        写JSON(self.记录路径, self.记录)

    def 阶段快照(self):
        saved = self.记录.get("成果阶段", {})
        return [{"id": key, "label": label, "status": "pending", "available": False,
                 "completed": 0, "total": 0, **saved.get(key, {})} for key, label in 阶段名称.items()]

    def 写阶段(self, stage, data=None, *, status="running", completed=0, total=0, reason="", revision=None):
        if stage not in 阶段名称 or status not in ("pending", "running", "completed", "skipped", "partial"):
            raise ValueError("规划成果阶段不合法")
        stages = dict(self.记录.get("成果阶段", {}))
        previous = stages.get(stage, {})
        if data is not None:
            写JSON(self.路径("阶段成果", stage + ".json"), data)
        stages[stage] = {"status": status, "available": data is not None or previous.get("available", False),
                         "completed": completed, "total": total, "reason": reason,
                         "revision": previous.get("revision", 0) + (data is not None) if revision is None else revision}
        self.更新(成果阶段=stages)

    def 暂停阶段(self, reason):
        for stage in self.阶段快照():
            if stage["status"] in ("running", "partial"):
                self.写阶段(stage["id"], status="partial" if stage["available"] else "pending",
                           completed=stage["completed"], total=stage["total"], reason=reason,
                           revision=stage.get("revision", 0))

    def 读阶段(self, stage, episode=None, offset=0):
        if stage not in 阶段名称:
            raise ValueError("规划成果阶段不存在")
        summary = next(x for x in self.阶段快照() if x["id"] == stage)
        if not summary["available"]:
            raise ValueError("此阶段尚未保存成果")
        data = 读JSON(self.路径("阶段成果", stage + ".json"))
        if stage == "analysis" and data.get("mode") != "chapters" and offset:
            raise ValueError("内容页不存在")
        if stage == "analysis" and data.get("mode") == "chapters":
            count = data["totalContents"]
            if not 0 <= offset <= count:
                raise ValueError("内容页不存在")
            end = min(offset + 20, count)
            indices = data.get("范围序号", list(range(1, count + 1)))
            data["contents"] = [读JSON(self.路径("章节理解", f"范围{i:03d}.json")) for i in indices[offset:end]]
            data.update(offset=offset, nextOffset=end if end < count else None)
        if stage == "storyboards":
            directory = data.get("episodes", [])
            number = episode if episode is not None else directory[0]["集号"] if directory else None
            if number is None or not any(e["集号"] == number for e in directory):
                raise ValueError("此集尚未生成保存")
            data.update(episode=number, result=self.读分集(number))
        return {**summary, "data": data}

    async def 读取(self, stage, payload):
        key = 指纹({"阶段": stage, "输入": payload})
        path = self.路径("阶段检查点", key + ".json")
        if not path.exists():
            return None
        try:
            data = await asyncio.to_thread(读JSON, path)
            if data.get("指纹") == key:
                return data.get("结果")
        except (OSError, ValueError, TypeError):
            pass
        return None

    async def 保存(self, stage, payload, result):
        key = 指纹({"阶段": stage, "输入": payload})
        await asyncio.to_thread(写JSON, self.路径("阶段检查点", key + ".json"),
                                {"指纹": key, "阶段": stage, "保存时间": time.time(), "结果": result})

    def 保存失败输出(self, stage, raw, error, 请求摘要=None):
        """诊断与通过检查点分离；不存模型配置或请求头，不增加请求次数。"""
        key = 指纹({"阶段": stage, "输出": raw, "错误": error, "请求摘要": 请求摘要})
        写JSON(self.路径("运行记录", f"失败输出-{key}.json"),
               {"阶段": stage, "输出": raw, "错误": error, "保存时间": time.time(),
                "调用次数": self.记录.get("累计调用", 0),
                **({"请求摘要": 请求摘要} if 请求摘要 is not None else {})})

    def 计次(self, stage="", identity=None):
        count = self.记录.get("累计调用", 0)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0 or count >= self.记录.get("调用上限", 600):
            raise 规划预算耗尽(f"规划项目已达到{self.记录.get('调用上限', 600)}次累计请求安全上限；检查点已保留，未提交不合格结果")
        values = {"累计调用": count + 1}
        if identity is not None:
            if not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{64}", identity):
                raise ValueError("规划阶段任务标识不合法")
            entries = dict(self.记录.get("阶段请求", {}))
            used = entries.get(identity, {}).get("次数", 0)
            limit = 6  # 同一阶段的网络、格式和重复语义请求共用额度，恢复不清零。
            if isinstance(used, bool) or not isinstance(used, int) or used < 0 or used >= limit:
                raise 规划预算耗尽(f"{stage}已达到{limit}次阶段请求上限；保留检查点，不能继续整集重试")
            entries[identity] = {"阶段": stage, "次数": used + 1, "上限": limit}
            values["阶段请求"] = entries
        self.更新(**values)
        return count + 1

    def 写任务(self, job, shutdown=False):
        if not re.fullmatch(r"[a-f0-9]{32}", job.id):
            raise ValueError("规划任务标识不合法")
        写JSON(self.路径("运行记录", f"任务-{job.id}.json"),
               {"格式": 1, "任务": job.id, "项目": self.id, "凭据摘要": job.凭据摘要.hex(),
                "状态": "interrupted" if shutdown else job.状态, "序号": job.序号, "进度": job.进度,
                "预览": job.预览, "结果": job.结果, "错误": job.错误, "更新时间": time.time()})

    def 写分集(self, number, result):
        if not 1 <= number <= 120:
            raise ValueError("分集数量超过120集安全上限")
        写JSON(self.路径("分集规划", f"第{number:03d}集", "分镜结果.json"), result)

    def 读分集(self, number):
        if not 1 <= number <= 120:
            raise ValueError("分集不存在")
        return 读JSON(self.路径("分集规划", f"第{number:03d}集", "分镜结果.json"))
