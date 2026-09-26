"""可选交接的纯静态分图，不执行节点、IO、清理或宿主 prompt 校验。

分析仅在 OUTPUT_NODE 的依赖闭包内启用；无有效 H 时透明返回 None。
B 分析模板保留 H 的原定义，但 H 是依赖截断点，须经构建阶段图后展开。
仅支持标量常量及顶层普通链接；完整 validate_prompt 由提交协调层负责。
"""
from collections import deque
from copy import deepcopy
import hashlib
import json
import math
from os import path
import sys

from comfy_execution import graph_utils
from comfy_execution.graph_utils import GraphBuilder, is_link

__all__ = ["分析交接图", "构建阶段图", "展开二采图", "图摘要"]

_SOURCE = "长视频规划师"
_HANDOFF = "初采交接与清理"
_REFINER = "精修与放大"
_MAX_NODES = 4096
_MAX_EDGES = 32768
_MAX_JSON_DEPTH = 64
_MAX_JSON_ITEMS = 262144
_MAX_JSON_BYTES = 8 * 1024 * 1024
_OFFICIAL_LOADERS = {
    "CheckpointLoaderSimple": "nodes.py",
    "UNETLoader": "nodes.py",
    "DualCLIPLoader": "nodes.py",
    "CLIPLoader": "nodes.py",
    "VAELoader": "nodes.py",
    "UpscaleModelLoader": "comfy_extras/nodes_upscale_model.py",
}


def _标准JSON(value):
    """先迭代限制结构，避免 deepcopy/json 自身的递归栈与非 JSON 对象。"""
    pending = [(value, 0)]
    count = chars = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > _MAX_JSON_DEPTH or count > _MAX_JSON_ITEMS:
            raise ValueError("JSON 深度或项目数量超过上限（也不支持循环容器）")
        kind = type(item)
        if kind is dict:
            if len(item) + len(pending) > _MAX_JSON_ITEMS:
                raise ValueError("JSON 项目数量超过上限")
            for key, child in item.items():
                if type(key) is not str:
                    raise ValueError("JSON 对象键必须为字符串")
                chars += len(key)
                pending.append((child, depth + 1))
        elif kind is list:
            if len(item) + len(pending) > _MAX_JSON_ITEMS:
                raise ValueError("JSON 项目数量超过上限")
            pending.extend((child, depth + 1) for child in item)
        elif kind is str:
            chars += len(item)
        elif kind is float:
            if not math.isfinite(item):
                raise ValueError("JSON 不支持 NaN 或 Infinity")
        elif item is not None and kind not in (bool, int):
            raise ValueError("仅支持纯 JSON，不接受模型、Tensor 或自定义对象")
        if chars > _MAX_JSON_BYTES:
            raise ValueError("JSON 文本规模超过上限")
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError) as exc:
        raise ValueError("无法编码标准 JSON") from exc
    if len(encoded) > _MAX_JSON_BYTES:
        raise ValueError("JSON 字节规模超过上限")
    return encoded


def 图摘要(graph):
    """SHA-256(sorted keys、UTF-8、不转义中文、紧凑分隔符的标准 JSON)。"""
    return hashlib.sha256(_标准JSON(graph)).hexdigest()


def _链接(value, where):
    # 宿主 is_link 也接受 bool/float；本分图只支持合法的静态整数槽位。
    if is_link(value):
        if type(value[1]) is not int or value[1] < 0:
            raise ValueError(f"{where}: 链接槽必须是非 bool 的非负整数")
        return value
    if isinstance(value, list):
        raise ValueError(f"{where}: 不支持列表批处理、嵌套列表或非法链接槽")
    if isinstance(value, dict):
        raise ValueError(f"{where}: 不支持字典输入、rawLink 或复杂子图")
    if value is not None and type(value) not in (str, int, float, bool):
        raise ValueError(f"{where}: 仅支持 JSON 标量输入")
    return None


def _图结构(graph):
    if type(graph) is not dict or len(graph) > _MAX_NODES:
        raise ValueError("图必须是节点字典，且有效节点规模不能超过 4096")
    _标准JSON(graph)
    links, deps = {}, {}
    edges = 0
    for node_id, node in graph.items():
        if not node_id or type(node) is not dict:
            raise ValueError(f"{node_id!r}: 非法节点 ID 或定义")
        if set(node) - {"class_type", "inputs", "_meta", "override_display_id"}:
            raise ValueError(f"{node_id}: 不支持复杂子图或额外节点字段")
        if not isinstance(node.get("class_type"), str) or not node["class_type"]:
            raise ValueError(f"{node_id}: 缺少 class_type")
        if type(node.get("inputs")) is not dict:
            raise ValueError(f"{node_id}: inputs 必须是静态字典")
        links[node_id], deps[node_id] = {}, set()
        for key, value in node["inputs"].items():
            link = _链接(value, f"{node_id}.{key}")
            if link is not None:
                if link[0] not in graph:
                    raise ValueError(f"{node_id}.{key}: 链接引用不存在的节点 {link[0]}")
                links[node_id][key] = link
                deps[node_id].add(link[0])
                edges += 1
                if edges > _MAX_EDGES:
                    raise ValueError("有效连线规模超过上限")
    return links, deps


def _拓扑(deps):
    degree = {key: len(parents) for key, parents in deps.items()}
    children = {key: [] for key in deps}
    for key in sorted(deps):
        for parent in deps[key]:
            children[parent].append(key)
    ready = deque(sorted(key for key, count in degree.items() if count == 0))
    order = []
    while ready:
        key = ready.popleft()
        order.append(key)
        for child in children[key]:
            degree[child] -= 1
            if degree[child] == 0:
                ready.append(child)
    if len(order) != len(deps):
        raise ValueError("有效图存在循环，不支持非 DAG 或循环子图")
    return order


def _闭包(roots, deps, cut=None):
    found = set()
    pending = list(roots)
    while pending:
        key = pending.pop()
        if key in found:
            continue
        found.add(key)
        if key != cut:
            pending.extend(deps[key] - found)
    return found


def _输出闭包(graph, outputs):
    """启用探测不校验普通图，只读取宿主识别的顶层连线。"""
    found = set()
    pending = list(outputs)
    while pending:
        key = pending.pop()
        if key in found:
            continue
        found.add(key)
        node = graph.get(key)
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            continue
        for value in node["inputs"].values():
            if is_link(value) and value[0] not in found:
                pending.append(value[0])
    return found


def _节点合同(node_id, node, cls):
    if cls is None:
        raise ValueError(f"{node_id}: 宿主 node_classes 中不存在 {node['class_type']}")
    for flag in ("INPUT_IS_LIST", "NODE_IS_LIST"):
        value = getattr(cls, flag, False)
        if value is not False:
            raise ValueError(f"{node_id}: 不支持 {flag} 列表节点或不明确的列表合同")
    returns = getattr(cls, "RETURN_TYPES", None)
    if not isinstance(returns, (tuple, list)) or not all(isinstance(x, str) for x in returns):
        raise ValueError(f"{node_id}: 不支持动态 RETURN_TYPES 合同")
    output_lists = getattr(cls, "OUTPUT_IS_LIST", (False,) * len(returns))
    if (not isinstance(output_lists, (tuple, list)) or len(output_lists) != len(returns)
            or any(type(x) is not bool for x in output_lists) or any(output_lists)):
        raise ValueError(f"{node_id}: 不支持 OUTPUT_IS_LIST 列表或错误的列表合同")
    if getattr(cls, "ACCEPT_ALL_INPUTS", False):
        raise ValueError(f"{node_id}: 不支持 ACCEPT_ALL_INPUTS 动态输入")
    if getattr(cls, "API_NODE", False):
        raise ValueError(f"{node_id}: 不支持远程 API 节点")
    try:
        schema = cls.INPUT_TYPES()
    except Exception as exc:
        raise ValueError(f"{node_id}: 无法读取宿主 INPUT_TYPES 合同") from exc
    if type(schema) is not dict or set(schema) - {"required", "optional", "hidden"}:
        raise ValueError(f"{node_id}: 不支持复杂 INPUT_TYPES 子图合同")
    specs = {}
    for group in ("required", "optional"):
        fields = schema.get(group, {})
        if type(fields) is not dict:
            raise ValueError(f"{node_id}: 不支持动态 {group} 输入")
        for key, spec in fields.items():
            if key in specs or not isinstance(spec, (tuple, list)) or not 1 <= len(spec) <= 2:
                raise ValueError(f"{node_id}.{key}: 不支持的输入声明")
            data_type = spec[0]
            if not (isinstance(data_type, str) or (
                    isinstance(data_type, list) and data_type
                    and all(type(x) in (str, int, float, bool) for x in data_type))):
                raise ValueError(f"{node_id}.{key}: 不支持复杂动态输入类型")
            options = spec[1] if len(spec) == 2 else {}
            if type(options) is not dict:
                raise ValueError(f"{node_id}.{key}: 输入选项必须是字典")
            if options.get("rawLink") or options.get("lazy"):
                raise ValueError(f"{node_id}.{key}: 不支持 rawLink/lazy 依赖")
            specs[key] = spec
    for key in node["inputs"]:
        if key not in specs:
            raise ValueError(f"{node_id}.{key}: INPUT_TYPES 未声明的输入，不猜测复杂子图")
    return returns


def _检查共享(node_id, node, cls):
    name = node["class_type"]
    filename = _OFFICIAL_LOADERS.get(name)
    owner = sys.modules.get(cls.__module__)
    origin = getattr(owner, "__file__", None)
    # 本机 load_custom_node 用文件路径作为模块名；不猜测模块别名。
    # 只比较已加载模块的源位置与类身份，不导入 nodes，也不读取源文件。
    host_root = path.dirname(path.dirname(graph_utils.__file__))
    official = (filename is not None and isinstance(origin, str)
                and path.normcase(path.abspath(origin))
                == path.normcase(path.abspath(path.join(host_root, filename))))
    if (not official or getattr(owner, name, None) is not cls or cls.__name__ != name
            or getattr(cls, "OUTPUT_NODE", False)
            or getattr(cls, "NOT_IDEMPOTENT", False)):
        raise ValueError(f"{node_id}: 共享节点不属于已支持的官方纯加载链白名单")


def 分析交接图(graph, node_classes):
    """返回纯 JSON 分析字典；无有效交接为 None，启用但不支持时抛 ValueError。

    source_digest 仅绑定 S 及其完整上游定义（包括原 ID），不绑定二采参数。
    a_outputs 包含将成为 OUTPUT_NODE 的写入节点 H；输出 ID 均为原 ID。
    """
    if type(graph) is not dict:
        raise ValueError("graph 必须是序列化节点字典")
    handoffs = {key for key, node in graph.items()
                if isinstance(node, dict) and node.get("class_type") == _HANDOFF}
    if not handoffs:
        return None
    outputs = []
    for key, node in graph.items():
        if isinstance(node, dict) and isinstance(node.get("class_type"), str):
            cls = node_classes.get(node["class_type"])
            if cls is not None and getattr(cls, "OUTPUT_NODE", False) is True:
                outputs.append(key)
    active = _输出闭包(graph, outputs)
    if not active.intersection(handoffs):
        return None
    if len(active) > _MAX_NODES:
        raise ValueError("有效节点规模超过 4096 上限")
    # 不复制或序列化悬空分支；普通路径和无关画布元数据保持原样。
    effective = {key: graph[key] for key in active if key in graph}
    links, deps = _图结构(effective)
    order = _拓扑(deps)
    classes, returns = {}, {}
    for key in order:
        cls = node_classes.get(effective[key]["class_type"])
        returns[key] = _节点合同(key, effective[key], cls)
        classes[key] = cls
    for key in order:
        for name, (parent, slot) in links[key].items():
            if slot >= len(returns[parent]):
                raise ValueError(f"{key}.{name}: 链接槽超出 {parent} 的 RETURN_TYPES")

    ids = {}
    for label, kind in (("S", _SOURCE), ("H", _HANDOFF), ("R", _REFINER)):
        matches = [key for key in order if effective[key]["class_type"] == kind]
        if len(matches) != 1:
            raise ValueError(f"有效交接链必须恰有一个 {label}={kind}；不支持多节点或绕过 H 的精修")
        ids[label] = matches[0]
    source, handoff, refiner = ids["S"], ids["H"], ids["R"]
    if effective[handoff]["inputs"] != {"初采产物": [source, 5]}:
        raise ValueError("H 必须仅接长视频规划师 S 的初采产物槽 5")
    if links[refiner].get("初采产物") != [handoff, 0]:
        raise ValueError("R 必须直接连接 H 的初采产物槽 0")
    for key in order:
        for name, link in links[key].items():
            if link[0] == handoff and (key != refiner or name != "初采产物" or link[1] != 0):
                raise ValueError("H 仅支持唯一 R 的初采产物消费者，不支持其他交接分支")

    # 位标记只计算一次，避免为每个输出保存 O(N²) 的完整祖先集合。
    flags, direct_source = {}, {}
    a_outputs, b_outputs = [], []
    output_set = set(outputs)
    for key in order:
        flags[key] = (1 if key == source else 2 if key == handoff else 4 if key == refiner else 0)
        for parent in deps[key]:
            flags[key] |= flags[parent]
        direct_source[key] = key == source or (key != handoff and any(direct_source[p] for p in deps[key]))
        if key not in output_set:
            continue
        if flags[key] & 4:
            if direct_source[key]:
                raise ValueError(f"{key}: 二采输出混合跨阶段的一采依赖，禁止附带 S 任意输出")
            b_outputs.append(key)
        elif direct_source[key] and not flags[key] & 2:
            a_outputs.append(key)
        else:
            raise ValueError(f"{key}: 不支持与交接链无关的有效输出或交接旁路输出")
    if not b_outputs:
        raise ValueError("缺少精修 R 的有效输出目标")
    a_ids = _闭包([source, handoff, *a_outputs], deps)
    b_ids = _闭包([refiner, *b_outputs], deps, cut=handoff)
    if source in b_ids or refiner in a_ids:
        raise ValueError("A/B 存在跨阶段依赖，二采不能包含 S 任意输出")
    for key in sorted(a_ids & b_ids - {handoff}):
        _检查共享(key, effective[key], classes[key])
    source_ids = _闭包([source], deps)
    return {
        "source_id": source, "handoff_id": handoff, "refiner_id": refiner,
        "a_graph": deepcopy({key: effective[key] for key in sorted(a_ids)}),
        "b_graph": deepcopy({key: effective[key] for key in sorted(b_ids)}),
        "a_outputs": sorted(set(a_outputs) | {handoff}),
        "b_outputs": sorted(b_outputs),
        "source_digest": 图摘要({key: effective[key] for key in sorted(source_ids)}),
    }


def 构建阶段图(analysis, *, job_id, attempt, a_nonce, b_nonce):
    """深拷贝分析模板，替换 H；控制参数不回写源图或 analysis。"""
    for name, value in (("job_id", job_id), ("a_nonce", a_nonce), ("b_nonce", b_nonce)):
        if type(value) is not str or not value.strip():
            raise ValueError(f"{name} 必须为非空控制字符串")
    if type(attempt) is not int or attempt < 0:
        raise ValueError("attempt 必须为非 bool 的非负整数")
    if a_nonce == b_nonce:
        raise ValueError("A/B 必须使用独立阶段 nonce")
    keys = {"source_id", "handoff_id", "refiner_id", "a_graph", "b_graph", "a_outputs", "b_outputs", "source_digest"}
    if type(analysis) is not dict or set(analysis) != keys:
        raise ValueError("必须提供分析交接图返回的完整 analysis")
    _标准JSON(analysis)
    handoff = analysis["handoff_id"]
    for stage in ("a_graph", "b_graph"):
        if (type(analysis[stage]) is not dict or handoff not in analysis[stage]
                or analysis[stage][handoff].get("class_type") != _HANDOFF):
            raise ValueError("analysis 必须包含尚未替换的 H 模板")
    result = deepcopy({key: analysis[key] for key in ("a_graph", "b_graph", "a_outputs", "b_outputs")})
    writer = result["a_graph"][handoff]
    writer["class_type"] = "LVP_交接写入"
    writer["inputs"].update(job_id=job_id, attempt=attempt, nonce=a_nonce)
    reader = result["b_graph"][handoff]
    reader["class_type"] = "LVP_读取初采引用"
    reader["inputs"] = {"job_id": job_id, "attempt": attempt, "nonce": b_nonce}
    return result


def 展开二采图(graph):
    """展开已经冻结、构建并经宿主全量校验的 B 模板；不执行任何子节点。

    此接口不接收 node_classes，输入合同检查属于分析阶段，不能代替宿主校验。
    override_display_id 总是原 ID，而 node_ids 返回真正的动态执行 ID。
    """
    links, deps = _图结构(graph)
    order = _拓扑(deps)
    builder = GraphBuilder()
    nodes = {}
    for key in order:
        inputs = deepcopy(graph[key]["inputs"])
        # GraphBuilder.set_input(None) 会删除输入；常量必须在初始化时传入。
        constants = {name: value for name, value in inputs.items()
                     if name not in links[key] and name not in ("self", "id", "class_type")}
        node = builder.node(graph[key]["class_type"], id=key, **constants)
        # 避免合法输入名与 GraphBuilder.node 的 Python 参数重名。
        for name in ("self", "id", "class_type"):
            if name in inputs and name not in links[key]:
                node.inputs[name] = inputs[name]
        node.set_override_display_id(key)
        nodes[key] = node
    for key in order:
        for name, (parent, slot) in links[key].items():
            nodes[key].set_input(name, nodes[parent].out(slot))
    return {"graph": builder.finalize(), "node_ids": {key: node.id for key, node in nodes.items()}}
