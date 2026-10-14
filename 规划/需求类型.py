需求类型 = {
    "auto": "自动识别", "novel": "小说改编", "script": "剧本分镜", "story": "故事创作",
    "science": "知识科普", "product": "产品广告", "music": "音乐MV",
    "documentary": "纪录讲述", "storyboard": "分镜优化",
}
_类型能力 = {
    "music": "通用镜头设计",
    "documentary": "资料与科普讲解分镜",
    "storyboard": "分镜结构与覆盖要求",
}


def 类型技能(brief, 阶段="内容规划"):
    from .技能注册 import 注册技能, 解析技能, 技能根
    from .技能资料 import 读取正文, 资料依赖, 合并资料
    modes = [brief.get("需求类型", "auto")]
    if brief.get("输入类型") == "已有分镜":
        modes.append("storyboard")
    if brief.get("目标体裁") == "音乐视频":
        modes.append("music")
    cards, docs = 注册技能(), []
    for key in dict.fromkeys(modes):
        if key not in _类型能力:
            continue
        card = 解析技能(cards, _类型能力[key])
        if 阶段 not in card.get("适用阶段", []):
            continue
        paths, deps = [], []
        for item in card["资料文件"]:
            if item.get("用途") == "技能入口" or 阶段 not in item.get("适用阶段", card["适用阶段"]):
                continue
            paths.append(item["路径"])
            deps.extend(item.get("依赖资料", []))
        if paths:
            docs.append({"技能": card["显示名称"], "资料": "\n".join(
                读取正文(技能根, path) for path in paths)})
            docs.extend(资料依赖(paths, deps, 阶段))
    return 合并资料(docs)
