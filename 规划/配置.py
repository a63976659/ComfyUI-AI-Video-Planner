# -*- coding: utf-8 -*-
"""H3 规划器服务器端配置：json 落盘 + 按模型 api_key 掩码 + 私有主机判定。

不 import ComfyUI。原子写盘与 计划路由/媒体路由/段缓存 同源（.part + os.replace）。
设计依据：文档/规格/2026-09-10-H3规划器-设计.md §7.2 + §13；
按模型密钥契约（2026-09-17）参照 ComfyUI-Artificial-Intelligence 节点/api配置.py 的 api_models 统一清单模式。
"""
import contextlib
import ipaddress
import itertools
import json
import logging
import os
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .本地配置 import 本地配置路径

_临时序号 = itertools.count()


def 配置路径() -> str:
    return str(本地配置路径("规划器配置.json"))


def 内置预设() -> list:
    """内置 API 模型预设定义（单一真实源在后端）；经 _迁移模型清单 物化进 api_models（builtin=True）后与自定义同样可编辑。
    与 ComfyUI-Artificial-Intelligence 的 BUILTIN_PRESET_DEFS 同构（name/base_url/model）；
    默认项 Kimi-K3 居首（用户指定 2026-09-16）。"""
    return [
        {"name": "Kimi-K3", "base_url": "https://api.moonshot.cn/v1", "model": "kimi-k3"},
        {"name": "Qwen3.8", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen3.8-flash"},
        {"name": "GLM-5.3-Flash", "base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-5.3-flash"},
    ]


def _净化自定义模型(v) -> list:
    """custom_models 只留字典且只保留 name/base_url/model 三键（防污染配置盘；仅供旧盘迁移用）。"""
    return [{k: str(m.get(k) or "") for k in ("name", "base_url", "model")}
            for m in (v or []) if isinstance(m, dict)]


def _规范化端点(url: str) -> str:
    """端点规范化：用于密钥沿用/继承的「同一端点」判定。比较协议 + 主机(小写) + 端口(补默认)
    + 有效路径(去尾斜杠)，忽略查询/片段/用户名密码。解析不出主机（相对地址等）→ 退化整串小写比较。
    空串 → 空串（调用方据此判不等价，防无地址条目彼此继承凭据）。"""
    s = (url or "").strip()
    if not s:
        return ""
    p = urllib.parse.urlparse(s)
    if not p.netloc:
        return s.lower()
    scheme = (p.scheme or "").lower()
    host = (p.hostname or "").lower()
    try:
        port = p.port
    except ValueError:                        # 非法端口（如 a.com:xyz）→ 视为缺省
        port = None
    default = {"http": 80, "https": 443, "ws": 80, "wss": 443}.get(scheme)
    netloc = host if port in (None, default) else f"{host}:{port}"
    return f"{scheme}://{netloc}{(p.path or '').rstrip('/')}"


def _同端点(a: str, b: str) -> bool:
    """两地址规范化后是否同一端点；任一为空一律 False（空≠空，避免彼此误判继承）。"""
    na = _规范化端点(a)
    return bool(na) and na == _规范化端点(b)


def _净化模型清单(v, 旧清单=None) -> list:
    """api_models 条目净化：只留 id/name/base_url/model/builtin/api_key 六键（防污染配置盘）。
    api_key 空串或含 **** ＝不修改，按 id 且端点未变才沿用旧 Key（同参照插件 api配置.py 掩码规则：
    掩码串绝不落盘）；换了协议/主机/端口/有效路径＝新端点，不继承旧密钥，需重新提供；
    缺 id 服务端补齐，防两条新条目空 id 撞车丢 Key。"""
    旧表 = {m.get("id"): m for m in (旧清单 or []) if isinstance(m, dict)}
    出 = []
    for m in (v or []):
        if not isinstance(m, dict):
            continue
        eid = str(m.get("id") or "").strip()
        if not eid:
            eid = f"custom_{os.getpid()}_{next(_临时序号)}"
        旧条目 = 旧表.get(eid) or {}
        键 = str(m.get("api_key") or "").strip()
        if not 键 or "****" in 键:
            # 密钥沿用绑定同一规范化端点：换了协议/主机/端口/有效路径＝新端点，不自动继承旧 Key
            # （防凭据随改址误发新目标），需用户重新提供。
            键 = (str(旧条目.get("api_key") or "")
                  if _同端点(str(m.get("base_url") or ""), str(旧条目.get("base_url") or ""))
                  else "")
        出.append({
            "id": eid,
            "name": str(m.get("name") or "").strip(),
            "base_url": str(m.get("base_url") or "").strip(),
            "model": str(m.get("model") or "").strip(),
            "builtin": bool(m.get("builtin")),
            "api_key": 键,
        })
    return 出


def _迁移模型清单(盘: dict) -> list:
    """旧配置盘（custom_models + 全局 api_key）→ 统一 api_models（同参照插件 ensure_seeded 物化思路）：
    预设行物化为 builtin=True（与自定义同样可编辑、可填 Key）；旧自定义行转 custom 条目；
    旧全局 Key 挂到地址+模型命中的条目，升级不静默丢密钥。"""
    出 = [{"id": p["name"], "name": p["name"], "base_url": p["base_url"],
           "model": p["model"], "builtin": True, "api_key": ""} for p in 内置预设()]
    for i, m in enumerate(_净化自定义模型(盘.get("custom_models"))):
        出.append({**m, "id": f"custom_{i}", "builtin": False, "api_key": ""})
    旧键 = str(盘.get("api_key") or "")
    if 旧键:
        for e in 出:
            if e["base_url"] == (盘.get("base_url") or "") and e["model"] == (盘.get("model") or ""):
                e["api_key"] = 旧键
                break
    return 出


def _生效密钥(cfg: dict) -> str:
    """生效 Key＝选中模型（base_url+model）命中条目的 Key（该条无 Key 即为空）；
    无命中（旧盘手改地址等遗留配置）保留原值，升级不静默丢密钥。"""
    for e in cfg.get("api_models") or []:
        if e.get("base_url") == cfg.get("base_url") and e.get("model") == cfg.get("model"):
            return e.get("api_key") or ""
    return cfg.get("api_key") or ""


def _整数配置(cfg: dict, 键: str, 默认: int, 下限: int = None) -> int:
    """脏配置防御：用户可编辑的 规划器配置.json 把数值写成 ""/null/"auto" 时 int() 会抛
    TypeError/ValueError——回落默认，不让裸 ValueError 外溢（否则绕过 LLM错误 结构化契约，
    在路由层退化成无分类 500，前端无法按 §3.10 B4 「config 不重试」分流）。"""
    try:
        v = int(cfg.get(键, 默认))
    except (TypeError, ValueError):
        v = 默认
    return v if 下限 is None else max(下限, v)


def 默认配置() -> dict:
    首 = 内置预设()[0]
    return {
        "base_url": 首["base_url"],
        "model": 首["model"],
        "api_key": "",          # 生效密钥：由 _生效密钥 从选中模型条目派生（调用方零改动）
        "temperature": 0.7,
        "max_tokens": 4096,
        "timeout": 120,
        "planning_max_active": 0,
        "planning_image_max_active": 0,
        "verify_ssl": True,
        "llm_max_active": 2,                      # 4阶段 B2：进程级同时进行的 LLM 请求数上限
        "llm_max_queued": 4,                      # 4阶段 B2：超过活动数后允许排队的请求数上限，再超返回繁忙
        "api_models": _迁移模型清单({}),   # 统一模型清单：预设行物化可编辑（同参照插件 api_models）
        "ai_model_selections": {"planning": "", "timeline": "", "editor": ""},
    }


def 读配置() -> dict:
    cfg = 默认配置()
    盘 = {}
    路径 = 配置路径()
    try:
        with open(路径, "r", encoding="utf-8") as f:
            盘 = json.load(f)
        if not isinstance(盘, dict):
            盘 = {}
    except (OSError, ValueError):
        盘 = {}                                 # 缺失/损坏 → 静默返回默认（不抛）
    cfg.update({k: 盘[k] for k in cfg if k in 盘})
    if isinstance(盘.get("api_models"), list):
        cfg["api_models"] = _净化模型清单(盘["api_models"])
    else:
        cfg["api_models"] = _迁移模型清单(盘)   # 旧盘：custom_models + 全局 api_key → 统一清单
    cfg["ai_model_selections"] = _净化用途模型(cfg.get("ai_model_selections"), cfg["api_models"])
    return cfg


def _净化用途模型(value, models):
    value = value if isinstance(value, dict) else {}
    ids = {m["id"] for m in models}
    return {key: value.get(key) if isinstance(value.get(key), str) and value[key] in ids else ""
            for key in ("planning", "timeline", "editor")}


def 写配置(patch: dict) -> dict:
    cfg = 读配置()
    for k, v in (patch or {}).items():
        if k not in cfg:
            continue                            # 忽略未知键（防污染）
        if k == "api_key" and (v is None or v == ""):
            continue                            # 掩码模式：不回传明文 → 保留原密钥
        if k == "api_models":
            v = _净化模型清单(v, 旧清单=cfg["api_models"])
        cfg[k] = v
    cfg["ai_model_selections"] = _净化用途模型(cfg.get("ai_model_selections"), cfg["api_models"])
    cfg["api_key"] = _生效密钥(cfg)              # 生效密钥随选中模型条目派生（调用方 默认opener 零改动）
    目标 = 配置路径()
    临时 = f"{目标}.{os.getpid()}.{next(_临时序号)}.part"
    已落盘 = False
    try:
        with open(临时, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(临时, 目标)
        已落盘 = True
    finally:
        if not 已落盘:
            with contextlib.suppress(OSError):
                os.remove(临时)
    return 读配置()


def 测连通性(entry: dict) -> dict:
    """连通性测试（同参照插件 api配置.py test_api_model 思路）：发一次最小请求验证 Base URL/模型/API Key 三要素。
    返回 dict 不抛——测试结果用于面板展示，不中断执行。api_key 空串/掩码＝沿用已存 Key（按 id 或 地址+模型 匹配，
    编辑行可能只带了地址/模型未重填 Key）；测试超时封顶 30s（不等配置的长超时）。"""
    cfg = 读配置()
    entry = entry if isinstance(entry, dict) else {}
    base = str(entry.get("base_url") or "").rstrip("/")
    model = str(entry.get("model") or "").strip()
    if not base or not model:
        return {"ok": False, "error": "请先填写 Base URL 与模型名"}
    键 = str(entry.get("api_key") or "").strip()
    if not 键 or "****" in 键:
        # 空/掩码 Key 的沿用同样绑定端点：base_url 变了就视作未填，绝不对新址发送旧凭据
        eid = str(entry.get("id") or "").strip()
        for e in cfg.get("api_models") or []:
            if not _同端点(base, e.get("base_url") or ""):
                continue
            if (eid and e["id"] == eid) or e["model"] == model:
                键 = e["api_key"]
                break
    if not 键:
        return {"ok": False, "error": "未填写 API Key"}
    # 同参照插件 _build_body：不发 temperature/top_p/seed，用各家官方默认——恒发会让个别服务端直接 400
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": "ping"}],
                       "max_tokens": 8, "stream": False}).encode("utf-8")
    url = f"{base}/chat/completions"
    ctx = _ssl上下文(cfg, url)
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    # 凭据走「不随重定向携带」头：跨目标重定向时 urllib 会丢弃它，防 Authorization 误发新址
    req.add_unredirected_header("Authorization", f"Bearer {键}")
    try:
        with urllib.request.urlopen(req, timeout=min(int(cfg.get("timeout", 120)), 30), context=ctx) as resp:
            数据 = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": _错误摘要(e)}
    if isinstance(数据, dict) and 数据.get("error"):      # 少数供应商 200 裹 error 体
        return {"ok": False, "error": str(数据["error"])[:200]}
    return {"ok": True}


def 取脱敏配置() -> dict:
    cfg = 读配置()
    return {
        "base_url": cfg["base_url"], "model": cfg["model"],
        "temperature": cfg["temperature"], "max_tokens": cfg["max_tokens"],
        "timeout": cfg["timeout"], "verify_ssl": cfg["verify_ssl"],
        "ai_model_selections": cfg["ai_model_selections"],
        # 统一模型清单（预设行 builtin=True）：逐条 has_key，绝不含 api_key 明文/掩码串
        "models": [{**{k: e[k] for k in ("id", "name", "base_url", "model", "builtin")},
                    "has_key": bool(e["api_key"])} for e in cfg["api_models"]],
    }


def _是私有主机(url: str) -> bool:
    """回环/私有网段判定（localhost / 127.* / ::1 / 10.* / 192.168.* / 172.16-31.*）。
    用 ipaddress 严格解析主机：非合法 IP（如 127.evil.com）→ False，杜绝前缀伪装。"""
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if host == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback


def _ssl上下文(cfg: dict, url: str):
    """TLS 安全默认（不做全局关闭）：http→None；https+verify→校验；
    https+!verify+私有→放行本地自签；https+!verify+公网→强制校验+warning。"""
    if not url.startswith("https://"):
        return None
    if cfg.get("verify_ssl", True):
        return ssl.create_default_context()
    if _是私有主机(url):
        return ssl._create_unverified_context()
    logging.warning("[长视频规划师] 公网 https 强制保持 TLS 校验（忽略 verify_ssl=False）：%s", url)
    return ssl.create_default_context()


def _错误摘要(e) -> str:
    码 = getattr(e, "code", None)
    if not 码:
        return str(e)
    # 同参照插件 _safe_read+_extract_error_detail：读服务端错误回包挖出具体 message，
    # 只剩 "HTTP 400: Bad Request" 无法定位（如 temperature/seed 恒发被个别服务端拒）
    try:
        文 = e.read().decode("utf-8", errors="replace")
    except Exception:
        文 = ""
    try:
        j = json.loads(文)
        err = j.get("error") if isinstance(j, dict) else None
        if isinstance(err, dict):
            细 = str(err.get("message") or err.get("code") or "")
        elif isinstance(err, str):
            细 = err
        else:
            细 = ""
    except Exception:
        细 = (文 or "").strip()
    摘 = f"HTTP {码}: {getattr(e, 'reason', '')}"
    return f"{摘}｜{细[:300]}" if 细 else 摘


# ==================== 4阶段 B：LLM 请求治理（错误结构 / 重试分类 / 超时预算 / 响应规模 / 并发名额）====================

class LLM错误(RuntimeError):
    """结构化 LLM 异常：继承 RuntimeError 以兼容既有 `except RuntimeError` 透传与
    pytest.raises(RuntimeError, match="未配置")。携带 类别/可重试/状态码/请求ID，
    供路由据此定 HTTP 状态，不再靠中文异常子串匹配（B4）。"""

    def __init__(self, message, *, 类别="unknown", 可重试=False, 状态码=500, 请求ID=""):
        super().__init__(message)
        self.类别 = 类别
        self.可重试 = 可重试
        self.状态码 = 状态码
        self.请求ID = 请求ID


def _分类HTTP(码: int):
    """HTTP 状态码 → (类别, 可重试, 建议响应状态码)。
    401/403＝鉴权失败、4xx＝参数/客户端错误：均不重试（同样的请求重试只会再错）。
    429＝限流、5xx＝上游故障：暂态可重试。总尝试≤2 在调用处再约束。"""
    if 码 in (401, 403):
        return "auth", False, 502
    if 码 == 429:
        return "rate_limited", True, 502
    if 400 <= 码 < 500:
        return "client", False, 502
    if 码 >= 500:
        return "server", True, 502
    return "http", False, 502


def _读取限长(resp, 上限: int) -> bytes:
    """保留旧调用签名，不再限制响应字节；服务端决定输出容量。"""
    原文 = resp.read()
    if isinstance(原文, str):
        原文 = 原文.encode("utf-8", errors="replace")
    return 原文


class _LLM限流器:
    """进程级 LLM 并发闸（B2）：最多 活动 个请求同时发起，额外最多 排队 个等待，
    再超立刻判「繁忙」。名额在发起线程真正结束（finally）后才释放——不把客户端断开
    误当后台已停。排队等待有独立预算，用尽也判繁忙，不扣除网络等待时间。"""

    def __init__(self, 活动: int = 2, 排队: int = 4):
        self._cv = threading.Condition()
        self._活动上限 = max(1, int(活动))
        self._排队上限 = max(0, int(排队))
        self._活动 = 0
        self._排队 = 0

    def 设置上限(self, 活动: int, 排队: int):
        with self._cv:
            self._活动上限 = max(1, int(活动))
            self._排队上限 = max(0, int(排队))
            self._cv.notify_all()

    def 获取(self, 等待预算秒: float) -> bool:
        with self._cv:
            # 有空闲活动位且无人在排队 → 直接占用，不占排队名额（排队上限=0 也应允许）
            if self._活动 < self._活动上限 and self._排队 == 0:
                self._活动 += 1
                return True
            if self._排队 >= self._排队上限:
                return False                        # 队列已满 → 立即繁忙
            self._排队 += 1
            截止 = time.monotonic() + max(0.0, 等待预算秒)
            try:
                while self._活动 >= self._活动上限:
                    剩 = 截止 - time.monotonic()
                    if 剩 <= 0 or not self._cv.wait(剩):
                        return False                # 等待预算耗尽 → 繁忙
                self._活动 += 1
                return True
            finally:
                self._排队 -= 1                     # 无论成功/繁忙/超时，离开「排队」态

    def 释放(self):
        with self._cv:
            if self._活动 > 0:
                self._活动 -= 1
            self._cv.notify()

    async def 异步获取(self, 等待预算秒: float) -> bool:
        """规划协程共用原有名额；取消等待立即退队，不遗留占位线程。"""
        import asyncio
        with self._cv:
            if self._活动 < self._活动上限 and self._排队 == 0:
                self._活动 += 1
                return True
            if self._排队 >= self._排队上限:
                return False
            self._排队 += 1
        截止 = time.monotonic() + max(0, 等待预算秒)
        try:
            while time.monotonic() < 截止:
                with self._cv:
                    if self._活动 < self._活动上限:
                        self._活动 += 1
                        return True
                await asyncio.sleep(min(0.05, max(0, 截止 - time.monotonic())))
            return False
        finally:
            with self._cv:
                self._排队 -= 1

    def 快照(self):
        with self._cv:
            return {"活动": self._活动, "排队": self._排队,
                    "活动上限": self._活动上限, "排队上限": self._排队上限}


_限流器 = _LLM限流器()


def _退避(尝试: int):
    """有界重试间的指数退避：第 0 次失败后等 0.5s、其后翻倍。"""
    time.sleep(0.5 * (2 ** 尝试))


def 造opener(覆盖=None, 请求回调=None, 停止=None):
    """工厂：返回 (system,user)->str 的 opener；覆盖={'base_url','model','api_key'} 优先于配置盘
    （供 /lvp/plan 按前端所选模型临时切换，不写盘）；覆盖缺省或某键为 None → 回落配置盘对应值。
    urllib 标准库（无新依赖）。4阶段 B 请求治理：
      · 网络等待超时：每次 urlopen 使用 timeout 限制连接/阻塞读写等待，不限制整个任务耗时。
      · 错误分类重试：401/403/4xx 参数错误不重试；429/5xx/网络暂态退避重试，总尝试≤2（B1）。
      · 响应容量由模型服务判断；不按本地字节额度拦截（含旧配置额度）。
      · 并发名额：进程级最多 llm_max_active 活动 + llm_max_queued 排队，超限/等待超时抛繁忙（B2）。
      · 结构化异常：统一抛 LLM错误（含 类别/可重试/状态码/请求ID），供路由定 HTTP 状态（B4）。"""
    覆盖 = 覆盖 if isinstance(覆盖, dict) else {}

    def opener(system: str, user: str) -> str:
        if 停止 is not None and 停止():
            raise LLM错误("LLM 请求已停止", 类别="cancelled", 状态码=409)
        cfg = 读配置()
        base = str(覆盖.get("base_url") or cfg.get("base_url") or "").rstrip("/")
        model = str(覆盖.get("model") or cfg.get("model") or "").strip()
        请求ID = uuid.uuid4().hex[:8]
        if not base or not model:
            raise LLM错误("LLM 未配置", 类别="config", 状态码=400, 请求ID=请求ID)
        键 = 覆盖.get("api_key")
        if 键 is None:
            键 = cfg.get("api_key") or ""
        # 同 测连通性/参照插件 _build_body：不发 temperature/top_p/seed，也不发 max_tokens
        # （思考模型推理会吃掉 token 预算，封顶会截断答复 JSON）。
        body = json.dumps({
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }).encode("utf-8")
        头 = {"Content-Type": "application/json"}
        url = f"{base}/chat/completions"
        ctx = _ssl上下文(cfg, url)

        网络超时 = _整数配置(cfg, "timeout", 120, 下限=1)
        响应上限 = None  # 旧配置中的max_response_bytes不再产生本地拦截。
        _限流器.设置上限(_整数配置(cfg, "llm_max_active", 2, 下限=1),
                    _整数配置(cfg, "llm_max_queued", 4, 下限=0))

        # B2 并发名额：拿不到（队列满或等待超时）→ 繁忙 503，不占线程也不发网络
        if not _限流器.获取(网络超时):
            raise LLM错误("LLM 请求已达并发上限，请稍后重试", 类别="busy",
                          可重试=True, 状态码=503, 请求ID=请求ID)
        try:
            最后错 = None
            for 尝试 in range(2):                       # 总尝试 ≤2（B1）
                if 停止 is not None and 停止():
                    raise LLM错误("LLM 请求已停止", 类别="cancelled", 状态码=409, 请求ID=请求ID)
                req = urllib.request.Request(url, data=body, headers=头, method="POST")
                if 键:
                    # 凭据走不随重定向携带头：跨目标重定向丢弃，防误发新址（同 测连通性）
                    req.add_unredirected_header("Authorization", f"Bearer {键}")
                try:
                    if 请求回调 is not None:
                        请求回调()
                    with urllib.request.urlopen(req, timeout=网络超时, context=ctx) as resp:
                        原文 = _读取限长(resp, 响应上限)                 # B3
                    数据 = json.loads(原文.decode("utf-8"))
                    # content 优先、空则回落 reasoning_content（思考模型可能 content 为空）。
                    消息 = (数据.get("choices") or [{}])[0].get("message") or {}
                    return str(消息.get("content") or 消息.get("reasoning_content") or "").strip()
                except LLM错误:                          # oversize 等已分类，直接透传
                    raise
                except urllib.error.HTTPError as e:      # 先于 URLError（HTTPError 是其子类）
                    最后错 = e
                    类别, 可重试, 码 = _分类HTTP(getattr(e, "code", 0) or 0)
                    if not 可重试 or 尝试 == 1:
                        raise LLM错误(f"LLM 调用失败：{_错误摘要(e)}", 类别=类别,
                                      可重试=可重试, 状态码=码, 请求ID=请求ID) from e
                    _退避(尝试)
                except (TimeoutError, urllib.error.URLError) as e:
                    # 网络暂态 / 连接拒 / DNS / 读超时（socket.timeout 是 TimeoutError 别名）：可重试
                    最后错 = e
                    if 尝试 == 1:
                        raise LLM错误(f"LLM 调用失败（暂态）：{_错误摘要(e)}", 类别="network",
                                      可重试=True, 状态码=502, 请求ID=请求ID) from e
                    _退避(尝试)
                except ValueError as e:                  # JSON 解析失败＝模型输出问题，重试无意义
                    raise LLM错误(f"LLM 响应解析失败：{e}", 类别="parse",
                                  可重试=False, 状态码=502, 请求ID=请求ID) from e
            # 防御性收尾；正常的二次失败已在上面按类别抛出。
            raise LLM错误(f"LLM 调用失败：{_错误摘要(最后错)}", 类别="network",
                          可重试=True, 状态码=502, 请求ID=请求ID)
        finally:
            _限流器.释放()

    return opener


# 默认 opener＝无覆盖的工厂产物：读配置盘 base_url/model/api_key（调用方零改动）
默认opener = 造opener()
