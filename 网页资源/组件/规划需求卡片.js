// 需求卡片只选择规划方式，不改写用户正文或其他表单字段。
export const 需求卡片 = Object.freeze([
    { id: "auto", 名称: "自动识别", 说明: "描述想法，自动安排内容与镜头", 目标体裁: "自动", 改写方式: "自动" },
    { id: "novel", 名称: "小说改编", 说明: "把小说情节改成画面故事", 目标体裁: "剧情叙事", 改写方式: "改编" },
    { id: "script", 名称: "剧本分镜", 说明: "按剧本拆镜头，保留剧情与台词", 目标体裁: "剧情叙事", 改写方式: "保真" },
    { id: "story", 名称: "故事创作", 说明: "从一个想法展开完整故事", 目标体裁: "剧情叙事", 改写方式: "创作补全" },
    { id: "science", 名称: "知识科普", 说明: "把知识要点讲清楚、画出来", 目标体裁: "科普讲解", 改写方式: "保真" },
    { id: "product", 名称: "产品广告", 说明: "突出产品卖点与使用场景", 目标体裁: "产品广告", 改写方式: "自动" },
    { id: "music", 名称: "音乐MV", 说明: "围绕歌词与情绪设计画面", 目标体裁: "音乐视频", 改写方式: "自动" },
    { id: "documentary", 名称: "纪录讲述", 说明: "组织真实资料，讲述人物与经历", 目标体裁: "通用表达", 改写方式: "保真" },
    { id: "storyboard", 名称: "分镜优化", 说明: "整理已有分镜，优化节奏与衔接", 目标体裁: "自动", 改写方式: "保真" },
].map(c => Object.freeze({ ...c, 输入类型: "自动", 封面: new URL(`../图片/规划需求/${c.id}.png`, import.meta.url).href })));

export function 取需求分类(brief = {}) {
    return Object.fromEntries(["输入类型", "目标体裁", "改写方式"].map(k => [k, brief[k] ?? "自动"]));
}
export function 匹配需求卡片(brief = {}) {
    const 分类 = 取需求分类(brief);
    return 需求卡片.find(c => Object.keys(分类).every(k => c[k] === 分类[k])) || null;
}
export function 合并旧需求(brief = {}) {
    const 主题 = String(brief.主题 ?? "").trim(), 内容 = String(brief.详细内容 ?? "").trim();
    if (!主题) return 内容;
    if (!内容) return 主题;
    if (内容 === 主题 || 内容.startsWith(主题 + "\n")) return 内容;
    return `${主题}\n\n${内容}`;
}
export function 采集需求正文(文本, 原始, 已编辑 = false) {
    const 内容 = String(文本 ?? "").trim();
    if (原始 && !已编辑 && 内容 === 合并旧需求(原始)) {
        return Object.fromEntries(["主题", "详细内容"].filter(k => Object.hasOwn(原始, k)).map(k => [k, 原始[k]]));
    }
    return { 详细内容: 内容 };
}
