import json


def 序列化规划资料(payload):
    def stable(value):
        if isinstance(value, dict):
            return {key: stable(value[key]) for key in sorted(value)}
        if isinstance(value, list):
            return [stable(item) for item in value]
        return value
    shared = ("规划阶段", "需求", "项目设计", "人物场景", "实体索引", "已定声音身份",
              "素材执行契约", "时长模式", "技能资料", "专项设计资料", "模型编译规则")
    data = {key: stable(payload[key]) for key in shared if key in payload}
    data.update({key: stable(payload[key]) for key in sorted(payload) if key not in data and key != "阶段任务标识"})
    if "阶段任务标识" in payload:
        data["阶段任务标识"] = payload["阶段任务标识"]
    return json.dumps(data, ensure_ascii=False)


def 汇总缓存用量(records):
    stages = {}
    for record in records:
        stage = record.get("阶段") or "未标注阶段"
        item = stages.setdefault(stage, {"请求数": 0, "有缓存统计请求数": 0, "命中tokens": 0, "未命中tokens": 0})
        item["请求数"] += 1
        if all(key in record for key in ("prompt_cache_hit_tokens", "prompt_cache_miss_tokens")):
            item["有缓存统计请求数"] += 1
            item["命中tokens"] += record["prompt_cache_hit_tokens"]
            item["未命中tokens"] += record["prompt_cache_miss_tokens"]
    total = {key: sum(item[key] for item in stages.values()) for key in ("请求数", "有缓存统计请求数", "命中tokens", "未命中tokens")}
    for item in [*stages.values(), total]:
        count = item["命中tokens"] + item["未命中tokens"]
        item["命中率"] = item["命中tokens"] / count if count else None
    return {"合计": total, "分阶段": stages}
