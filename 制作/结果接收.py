"""从完成工作流中接收终端视频与本轮真实分段，绝不把参考素材当成生成结果。"""
import copy
import json
import math
import os
from pathlib import Path

from .扩展 import _安全相对路径, _提取输出文件, _分块复制视频
from .工具 import 安全媒体路径, 文件摘要
from .合成 import 探测信息

结果字段 = "lvp_production"


def _上游(graph, node):
    value = graph.get(str(node), {})
    return {str(v[0]) for v in value.get("inputs", {}).values()
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], (str, int)) and isinstance(v[1], int)}


def 祖先(graph, node):
    pending, found = [str(node)], set()
    while pending:
        current = pending.pop()
        for parent in _上游(graph, current) - found:
            found.add(parent)
            pending.append(parent)
    return found


def _后续(graph, node):
    return {key for key in graph if 属于视频分支(graph, key, node)}


def 属于视频分支(graph, node, source):
    """规划师仅图像/初采产物可决定画面归属，音频或帧率连线不算视频分支。"""
    source, node = str(source), str(node)
    pending, seen = [node], set()
    allowed = {0, 5} if graph.get(source, {}).get("class_type") in ("长视频规划师", "精修与放大") else None
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        for link in graph.get(current, {}).get("inputs", {}).values():
            if not isinstance(link, list) or len(link) != 2 or not isinstance(link[1], int):
                continue
            parent = str(link[0])
            if parent == source:
                if allowed is None or link[1] in allowed:
                    return True
                continue
            pending.append(parent)
    return False


def _保存节点(kind):
    return kind == "视频制作输出" or "savevideo" in kind.lower() or "videocombine" in kind.lower()


def _纯秒(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _本轮段(graph, source):
    raw = graph.get(str(source), {}).get("inputs", {}).get("时间轴数据", "{}")
    if not isinstance(raw, str):
        return []
    try:
        parsed = json.loads(raw)
    except ValueError:
        return []
    return parsed.get("segments", []) if isinstance(parsed, dict) else []


def 构建结果元数据(package, graph, node, fps, frames):
    if package.get("type") == "LVP_FIRST_PASS_DISK":
        try:
            from ..执行.初采产物存储 import 读交接清单
        except ImportError:
            from 执行.初采产物存储 import 读交接清单
        manifest = 读交接清单(package)
        snapshots = [x["data"] for x in manifest["segments"]]
    else:
        snapshots = package.get("segments", ())
    source = str(package.get("source_node_id", node))
    original = _本轮段(graph, source)
    clips, cursor = [], 0
    for snap in snapshots:
        index, a, b = snap.get("index"), snap.get("output_start"), snap.get("output_end")
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in (index, a, b)) or a != cursor or b <= a or b > frames:
            raise ValueError("实际生成分段帧边界无效")
        submitted = original[index] if 0 <= index < len(original) and isinstance(original[index], dict) else {}
        speech = submitted.get("台词")
        if not isinstance(speech, str):
            data = submitted.get("镜头资料", {})
            speech = "".join(str(data.get(k, "") or "") for k in ("对白", "旁白")) if isinstance(data, dict) else ""
        voice = copy.deepcopy(snap.get("refs", {}).get("台词配音"))
        timing = submitted.get("配音计时", {})
        if voice is None and isinstance(timing, dict) and timing.get("文件名") and _纯秒(timing.get("时长")):
            begin = timing.get("文件起点", 0)
            if _纯秒(begin) and begin >= 0 and timing["时长"] > 0:
                voice = {"文件名": timing["文件名"], "起": begin, "末": begin+timing["时长"]}
        length, captions = (b-a)/fps, []
        if isinstance(timing, dict) and isinstance(timing.get("片段"), list):
            for line in timing["片段"]:
                if not isinstance(line, dict) or not _纯秒(line.get("起")) or not _纯秒(line.get("末")):
                    continue
                begin, end = max(0, line["起"]), min(length, line["末"])
                text = line.get("台词", "")
                if end > begin and isinstance(text, str) and text.strip():
                    captions.append({"开始": begin, "结束": end, "文本": text})
        if not captions and speech.strip():
            end = min(length, voice["末"]-voice["起"]) if isinstance(voice, dict) else length
            if end > 0:
                captions.append({"开始": 0, "结束": end, "文本": speech})
        clips.append({"序号": index, "开始": a/fps, "结束": b/fps,
                      "名称": submitted.get("标题", f"片段{index+1}"), "台词": speech, "字幕": captions, "配音": voice})
        cursor = b
    if not clips or cursor != frames:
        raise ValueError("实际生成分段不能覆盖最终视频")
    return {"节点": str(node), "来源节点": source, "帧率": fps, "帧数": frames,
            "时长": frames/fps, "运行标识": package.get("source_run_id", ""), "片段": clips}


def 交付生成结果(images, audio, fps, package, hidden):
    """NodeOutput UI支持宿主缓存回放；有下游保存时避免重复编码。"""
    graph, node = getattr(hidden, "prompt", None), getattr(hidden, "unique_id", None)
    if not isinstance(graph, dict) or node is None or not isinstance(package, dict):
        return None
    graph = {str(k): v for k, v in graph.items() if isinstance(v, dict)}
    try:
        if package.get("type") == "LVP_FIRST_PASS_DISK":
            try:
                from ..执行.跨任务清理 import 取得协调器
            except ImportError:
                from 执行.跨任务清理 import 取得协调器
            context = 取得协调器().取磁盘制作提交图(package)
            graph = context["graph"]
            node = context["dynamic_ids"].get(str(node), str(node))
        meta = 构建结果元数据(package, graph, node, float(fps), int(images.shape[0]))
        later = _后续(graph, node)
        if not any(graph[k].get("class_type") in ("精修与放大", "初采交接与清理", "LVP_交接写入") or _保存节点(graph[k].get("class_type", "")) for k in later):
            try:
                from ..节点.视频制作输出 import _编码
                from ..后端路由.媒体路由 import 媒体根
            except ImportError:
                from 节点.视频制作输出 import _编码
                from 后端路由.媒体路由 import 媒体根
            name, _path = _编码(images, audio, float(fps), 媒体根(), "生成结果")
            meta.update(文件名=name, 宽=int(images.shape[2]), 高=int(images.shape[1]))
        return {结果字段: [meta]}
    except Exception as exc:
        # 后期交付失败不能丢弃已经生成的张量，错误随本轮结果明确显示。
        return {"lvp_production_warning": [f"生成结果自动接收失败：{exc}"]}


def 接收工作流结果(record, prompt_id, source, media_root):
    if not isinstance(record, dict):
        raise ValueError("本轮工作流结果不存在")
    status = record.get("status", {})
    if status.get("status_str") not in (None, "success") or status.get("completed") is not True:
        raise ValueError("仅能接收成功完成的工作流结果")
    submitted = record.get("prompt", [])
    graph = submitted[2] if isinstance(submitted, (list, tuple)) and len(submitted) > 2 else {}
    if not isinstance(graph, dict):
        raise ValueError("工作流缺少本轮提交图")
    graph = {str(k): v for k, v in graph.items() if isinstance(v, dict)}
    source = str(source)
    if graph.get(source, {}).get("class_type") != "长视频规划师":
        raise ValueError("结果不属于当前长视频规划师节点")
    outputs = record.get("outputs", {})
    candidates, metadata, warnings = {}, {}, []
    for node, output in outputs.items():
        node = str(node)
        if node != source and not 属于视频分支(graph, node, source):
            continue
        if not isinstance(output, dict):
            continue
        warnings.extend(x for x in output.get("lvp_production_warning", []) if isinstance(x, str))
        data = output.get(结果字段, [])
        for meta in data if isinstance(data, list) else []:
            if isinstance(meta, dict) and str(meta.get("来源节点")) == source:
                metadata[node] = meta
                if meta.get("文件名"):
                    candidates.setdefault(node, []).append({"filename": meta["文件名"], "subfolder": "长视频规划师_媒体", "type": "input"})
        files, _ = _提取输出文件({"outputs": {node: output}})
        for file in files:
            if file not in candidates.setdefault(node, []):
                candidates[node].append(file)
        if not candidates.get(node):
            candidates.pop(node, None)
    # 同一分支只导入最末端的视频输出，独立终端分支分别保留。
    terminal = [n for n in candidates if not any(属于视频分支(graph, other, n) for other in candidates if other != n)]
    import folder_paths
    roots = {"input": folder_paths.get_input_directory(), "output": folder_paths.get_output_directory(), "temp": folder_paths.get_temp_directory()}
    bundles, seen = [], set()
    for node in terminal:
        available = [m for key, m in metadata.items() if key == node or key in 祖先(graph, node)]
        closest = next((m for m in available if m.get("节点") == node), None)
        if closest is None and available:
            closest = max(available, key=lambda m: len(祖先(graph, str(m.get("节点")))))
        for descriptor in candidates[node]:
            kind = descriptor.get("type", "output")
            if kind not in roots:
                raise ValueError("生成视频目录类型无效")
            filename, sub = descriptor.get("filename"), descriptor.get("subfolder", "")
            if not isinstance(filename, str) or Path(filename).name != filename or not isinstance(sub, str):
                raise ValueError("生成视频文件引用无效")
            path = _安全相对路径(roots[kind], (sub+"/" if sub else "")+filename)
            digest = 文件摘要(path)
            if digest in seen:
                continue
            seen.add(digest)
            name = filename if os.path.realpath(os.path.dirname(path)) == os.path.realpath(media_root) else f"结果_{digest[:24]}{Path(filename).suffix.lower()}"
            dest = 安全媒体路径(media_root, name)
            if os.path.realpath(path) != os.path.realpath(dest):
                dest = _分块复制视频(path, media_root, name, None)
                name = Path(dest).name
                if 文件摘要(dest) != digest:
                    raise ValueError("生成视频复制不完整")
            info = 探测信息(dest)
            if not info["width"] or not info["height"] or not _纯秒(info["duration"]) or not 0 < info["duration"] <= 3600 or not 1 <= info["fps"] <= 120:
                raise ValueError("最终输出不是可用视频")
            bundle = copy.deepcopy(closest or {})
            if not closest or abs(bundle.get("时长", 0)-info["duration"]) > max(0.12, 2/info["fps"]):
                bundle["片段"] = [{"序号": 0, "开始": 0, "结束": info["duration"], "台词": "", "字幕": [], "配音": None}]
                warnings.append("最终视频时序与生成分段不一致，已作为整段导入并保留原声；没有自动套用配音和字幕。")
            # 宿主缓存回放不算新素材；真正新一轮生成的运行标识仍区分独立结果。
            identity = bundle.get("运行标识") or f"{kind}:{sub}:{filename}"
            bundle.update(结果id=f"{source}:{node}:{identity}:{digest}", 本轮工作流=prompt_id, 节点=node, 来源节点=source, 文件名=name,
                          宽=info["width"], 高=info["height"], 帧率=info["fps"], 时长=info["duration"])
            bundles.append(bundle)
    from .片段记录 import 片段记录
    片段记录(media_root).保存(bundles)
    return {"结果": bundles, "warnings": warnings}
