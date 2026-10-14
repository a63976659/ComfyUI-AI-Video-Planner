import json

from .规划器 import 提取JSON as _提取JSON, _候选


def 提取JSON(text):
    try:
        return _提取JSON(text)
    except ValueError as original:
        if not isinstance(text, str) or not text.strip():
            raise
        failures = []
        for candidate in _候选(text):
            try:
                json.loads(candidate)
            except json.JSONDecodeError as error:
                failures.append((candidate.startswith(("{", "[")), len(candidate), error))
        if not failures:
            raise
        error = max(failures, key=lambda item: item[:2])[2]
        reasons = {
            "Unterminated string starting at": "字符串缺少结束引号",
            "Invalid control character at": "字符串包含未转义的换行或控制字符",
            "Expecting ',' delimiter": "缺少逗号或字符串引号不配对",
            "Expecting property name enclosed in double quotes": "对象字段名须使用双引号",
            "Expecting value": "缺少合法的 JSON 值",
            "Extra data": "JSON 结束后存在额外内容",
            "Invalid \\escape": "字符串包含无效转义",
        }
        reason = reasons.get(error.msg, error.msg)
        raise ValueError(f"无法从 LLM 输出提取合法 JSON：{reason}；候选 JSON 第{error.lineno}行第{error.colno}列（字符位置{error.pos + 1}）。未改写模型正文") from original


def 保存请求失败(project, stage, error, 请求摘要=None):
    if project is not None:
        summary = dict(请求摘要 or {})
        if getattr(error, "请求ID", ""):
            summary["请求ID"] = error.请求ID
        project.保存失败输出(stage, getattr(error, "原始响应", ""), str(error),
                           请求摘要=summary or None)
