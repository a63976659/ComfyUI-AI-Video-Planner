// 制作页纯数据工具。保留未知字段，使后续制作扩展与现有规划草稿往返兼容。
export const 新制作ID = (前缀 = "item") => `${前缀}-${globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`}`;
const 数 = (v, d) => Number.isFinite(Number(v)) ? Number(v) : d;
export function 规范制作(值 = {}) {
    const p = 值 && typeof 值 === "object" && !Array.isArray(值) ? 值 : {};
    const 接收记录 = Array.isArray(p.自动接收记录) ? p.自动接收记录 : [];
    const 全片段 = Array.isArray(p.片段) ? p.片段 : [];
    const 最近结果 = 接收记录.at(-1);
    const 片段 = p.最近生成工作流 ? 全片段.filter(s => s.源工作流 === p.最近生成工作流)
        : 最近结果 && 全片段.some(s => s.源结果id) ? 全片段.filter(s => s.源结果id === 最近结果) : 全片段;
    return {
        ...p, 版本: 1, 模式: "后期",
        片段,
        自动接收记录: 接收记录,
        画布: { 宽: 1280, 高: 720, 帧率: 24, ...p.画布 },
        实体: Array.isArray(p.实体) ? p.实体 : [],
        镜头: p.镜头 && typeof p.镜头 === "object" && !Array.isArray(p.镜头) ? p.镜头 : {},
        音轨: Array.isArray(p.音轨) ? p.音轨 : [],
        字幕: { 启用: true, 字号: 36, 颜色: "#ffffff", 位置: "底部", ...p.字幕, 条目: Array.isArray(p.字幕?.条目) ? p.字幕.条目 : [] },
        文字: Array.isArray(p.文字) ? p.文字 : [],
        后处理: { 亮度: 0, 对比度: 1, 饱和度: 1, 去闪烁: false, 防抖: false, 插帧: false, 响度标准化: true, 音乐压低: true, ...p.后处理 },
        工作流: Array.isArray(p.工作流) ? p.工作流 : [],
    };
}
export function 取镜头配置(草, 段) {
    const p = 规范制作(草?.制作), 已存 = p.镜头[段?.segment_id];
    // 只回退明确存在的文件引用；H3时间轴计划没有可读成片路径，绝不以提示词冒充视频。
    const 用 = [...(段?.使用素材 || []), ...(草?.全局素材 || [])];
    const 素 = (草?.素材 || []).filter(m => 用.includes(m.名));
    const 首项 = v => typeof v === "string" ? v : Array.isArray(v) ? v[0] : "";
    const 视 = 首项(段?.refs?.视频) || 素.find(m => m.类型 === "视频")?.名;
    const 图 = 段?.refs?.首帧 || 首项(段?.refs?.图片) || 素.find(m => m.类型 === "图像")?.名;
    return { 来源: 视 ? "视频" : 图 ? "图片" : "", 文件名: 视 || 图 || "", 起点: 0, 运镜: "静止", 标题: 段?.标题 || "", 声音: "原声", 音量: 1, 实体引用: [], 起始状态: 段?.起始状态 || 段?.镜头资料?.起始状态 || "", 结束状态: 段?.结束状态 || 段?.镜头资料?.结束状态 || "", 转场: "硬切", ...已存 };
}
export const 镜头参与制作 = 段 => (段?.启用 ?? 段?.run ?? true) !== false;
export function 取制作镜头时段(草) {
    const p = 规范制作(草?.制作), fps = 数(p.画布.帧率, 24) || 24, 表 = {};
    let 帧 = 0;
    const 后期 = 草?.制作?.模式 === "后期";
    for (const s of 后期 ? p.片段 : 草?.segments || []) {
        if (!镜头参与制作(s)) continue;
        const 长 = Math.max(1, Math.round(Math.max(0, 后期 ? 数(s.时长, 0) : 数(s.end, 0) - 数(s.start, 0)) * fps));
        表[后期 ? s.id : s.segment_id] = { 开始: 帧 / fps, 结束: (帧 + 长) / fps }; 帧 += 长;
    }
    return 表;
}
export function 取制作时长(草) {
    return Math.max(0, ...Object.values(取制作镜头时段(草)).map(s => s.结束));
}
// 自动接收只维护独立后期片段，不写入规划素材、segments 或执行时间轴。
export function 接收生成结果(草, 结果) {
    if (!结果 || typeof 结果.结果id !== "string" || !结果.结果id || typeof 结果.文件名 !== "string" || !结果.文件名 || !Array.isArray(结果.片段) || !结果.片段.length) throw new Error("生成结果缺少有效视频或片段信息");
    const p = 规范制作(草?.制作);
    const 工作流 = 结果.本轮工作流 || 结果.运行标识 || 结果.结果id;
    const 同轮 = p.最近生成工作流 === 工作流;
    if (同轮 && p.自动接收记录.includes(结果.结果id)) return { 草稿: 草, 新增: 0 };
    if (!同轮) { p.片段 = []; p.自动接收记录 = []; }
    const 总长 = 数(结果.时长, 0);
    if (!(总长 > 0)) throw new Error("生成结果时长无效");
    const 新片段 = 结果.片段.map((s, i) => {
        const 开始 = Number(s.开始), 结束 = Number(s.结束);
        if (!Number.isFinite(开始) || !Number.isFinite(结束) || 开始 < 0 || 结束 <= 开始 || 结束 > 总长 + .01) throw new Error("生成结果片段范围无效");
        return { id: 新制作ID("clip"), 名称: s.名称 || `生成片段 ${p.片段.length + i + 1}`, 文件名: 结果.文件名, 素材时长: 总长, 源开始: 开始, 源结束: 结束, 起点: 开始, 时长: 结束 - 开始, 启用: true, 声音: s.配音?.文件名 ? "配音" : "原声", 音量: 1, 转场: "硬切", 台词: s.台词 || "", 字幕: (s.字幕 || []).map(x => ({ ...x })), 配音: s.配音 ? { ...s.配音 } : null, 源工作流: 工作流, 源结果id: 结果.结果id, 源节点: String(结果.节点), 源段序号: s.序号 ?? i };
    });
    if (!p.画布已初始化 && !p.画布手动) {
        if (!(Number(结果.宽) > 0 && Number(结果.高) > 0 && Number(结果.帧率) > 0)) throw new Error("生成结果缺少画布尺寸");
        p.画布 = { 宽: Number(结果.宽), 高: Number(结果.高), 帧率: Number(结果.帧率) };
    }
    p.画布已初始化 = true;
    p.最近生成工作流 = 工作流;
    p.片段 = [...p.片段, ...新片段]; p.自动接收记录 = [...p.自动接收记录, 结果.结果id];
    return { 草稿: { ...草, 制作: p }, 新增: 新片段.length };
}
export function 取后期字幕(草) {
    const p = 规范制作(草?.制作), 时段 = 取制作镜头时段({ ...草, 制作: p });
    const 条目 = p.片段.flatMap(s => {
        if (!时段[s.id]) return [];
        const 偏移 = 数(s.起点, 0) - 数(s.源开始, 0), 时长 = 数(s.时长, 0);
        return (s.字幕 || []).flatMap(x => {
            const 开始 = Math.max(0, 数(x.开始, 0) - 偏移), 结束 = Math.min(时长, 数(x.结束, 0) - 偏移);
            return 结束 > 开始 ? [{ 开始: 时段[s.id].开始 + 开始, 结束: 时段[s.id].开始 + 结束, 文本: x.文本 }] : [];
        });
    });
    return [...条目, ...p.字幕.条目].sort((a, b) => a.开始 - b.开始);
}
export function 取失效镜头(草) {
    const 有效 = new Set((草?.segments || []).map(s => s.segment_id));
    return Object.keys(规范制作(草?.制作).镜头).filter(id => !有效.has(id));
}
function 读SRT时刻(文本) {
    const m = /^(\d+):(\d{2}):(\d{2})[,.](\d{3})$/.exec(文本.trim());
    if (!m || Number(m[2]) > 59 || Number(m[3]) > 59) throw new Error(`无效字幕时间：${文本}`);
    return Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3]) + Number(m[4]) / 1000;
}
export function 解析SRT(文本) {
    const 块 = String(文本).replace(/^\uFEFF/, "").replace(/\r/g, "").trim();
    if (!块) return [];
    return 块.split(/\n\s*\n/).map((b, i) => {
        const 行 = b.split("\n");
        if (/^\d+$/.test(行[0].trim())) 行.shift();
        const 时 = /^\s*(\S+)\s*-->\s*(\S+)(?:\s+.*)?$/.exec(行.shift() || "");
        if (!时) throw new Error(`第 ${i + 1} 条字幕缺少合法时间范围`);
        const 开始 = 读SRT时刻(时[1]), 结束 = 读SRT时刻(时[2]), 文 = 行.join("\n").trim();
        if (结束 <= 开始 || !文) throw new Error(`第 ${i + 1} 条字幕时间或文本无效`);
        return { 开始, 结束, 文本: 文 };
    });
}
function 写SRT时刻(v) {
    const ms = Math.round(Math.max(0, 数(v, 0)) * 1000), sec = Math.floor(ms / 1000);
    return [Math.floor(sec / 3600), Math.floor(sec / 60) % 60, sec % 60].map(x => String(x).padStart(2, "0")).join(":") + "," + String(ms % 1000).padStart(3, "0");
}
export function 生成SRT(条目) {
    return (条目 || []).map((x, i) => `${i + 1}\n${写SRT时刻(x.开始)} --> ${写SRT时刻(x.结束)}\n${x.文本 || ""}`).join("\n\n") + "\n";
}
export function 解析API工作流(值) {
    const 图 = 值?.prompt || 值?.output || 值;
    if (!图 || typeof 图 !== "object" || Array.isArray(图) || !Object.keys(图).length || 图.nodes) {
        throw new Error("请选择 ComfyUI「导出 API 格式」文件，或导入当前画布；普通画布 JSON 需要先在 ComfyUI 打开。");
    }
    for (const [id, n] of Object.entries(图)) {
        if (!n || typeof n.class_type !== "string" || !n.inputs || typeof n.inputs !== "object" || Array.isArray(n.inputs)) throw new Error(`节点 ${id} 不是有效 API 工作流节点`);
    }
    return JSON.parse(JSON.stringify(图));
}
export function 取工作流输入(图) {
    return Object.entries(图 || {}).flatMap(([节点, n]) => Object.entries(n.inputs || {}).filter(([, v]) => !Array.isArray(v)).map(([输入]) => ({ 节点, 输入, 名称: `${节点} · ${n._meta?.title || n.class_type} · ${输入}` })));
}
export const 工作流映射值 = ["提示词", "秒数", "帧数", "帧率", "种子", "宽", "高", "参考图", "参考视频"];
// 通用分镜进入旧 H3 管线前显式校验，不裁切、不把不兼容媒体静默忽略。
export function 准备H3填充(段组, 草, 默认任务 = "t2v", 上限 = { 图片: 9, 视频: 3, 音频: 3 }) {
    if (草?.brief?.执行后端 !== "通用工作流") return 段组;
    const p = 规范制作(草.制作);
    return 段组.map((s, i) => {
        const duration = Number(s.end) - Number(s.start), task = String(s.task || 默认任务).trim().toLowerCase();
        if (!Number.isFinite(duration) || duration < 5 || duration > 30) throw new Error(`镜头 ${i + 1} 为 ${duration} 秒，单镜头允许 5–30 秒。请先调整生成规划的镜头时长。`);
        if (!["t2v", "i2v", "fl2v", "r2v", "v2v", "rv2v"].includes(task)) throw new Error(`镜头 ${i + 1} 的任务 ${task} 不属于 H3 六任务，请调整生成任务类型。`);
        const refs = { ...(s.refs || {}) }, ids = p.镜头[s.segment_id]?.实体引用 || s.实体引用 || [];
        const bound = p.实体.filter(e => ids.includes(e.id));
        const list = v => typeof v === "string" ? [v] : Array.isArray(v) ? v : [];
        const 图片 = [...new Set([...list(refs.图片), ...bound.map(e => e.参考图).filter(Boolean)])];
        if (图片.length) refs.图片 = 图片;
        for (const k of ["图片", "视频", "音频"]) if (list(refs[k]).length > 上限[k]) throw new Error(`镜头 ${i + 1} 的${k}参考超过 H3 的 ${上限[k]} 个上限，请减少生成参考素材。`);
        const first = refs.首帧 || 图片[0], last = refs.尾帧, 视频 = list(refs.视频), 音频 = list(refs.音频);
        if ((task === "i2v" && !first) || (task === "fl2v" && (!first || !last))) throw new Error(`镜头 ${i + 1} 的 ${task} 缺少所需首帧/尾帧，请在生成规划中设置参考帧。`);
        if (["v2v", "rv2v"].includes(task) && !视频.length) throw new Error(`镜头 ${i + 1} 的 ${task} 缺少参考视频，请在生成规划中设置参考视频。`);
        if (task === "r2v" && !图片.length && !视频.length && !音频.length) throw new Error(`镜头 ${i + 1} 的 r2v 缺少参考素材。`);
        if (["t2v", "i2v", "fl2v"].includes(task) && (视频.length || 音频.length)) throw new Error(`镜头 ${i + 1} 的 ${task} 无法消费这些视频/音频参考，请改用参考任务。`);
        if (task === "t2v" && 图片.length) throw new Error(`镜头 ${i + 1} 绑定了参考图片，H3 t2v 无法将其作为真实条件，请改为 i2v/r2v 生成任务。`);
        if (["i2v", "fl2v"].includes(task) && !refs.首帧) refs.首帧 = first;
        const opts = p.镜头[s.segment_id] || {}, descriptions = bound.map(e => `${e.名称}：${e.描述 || ""}`).filter(Boolean);
        const states = [opts.起始状态 ? `开始状态：${opts.起始状态}` : "", opts.结束状态 ? `结束状态：${opts.结束状态}` : ""].filter(Boolean);
        return { ...s, task, refs, prompt: [s.prompt || "", ...descriptions, ...states].filter(Boolean).join("\n") };
    });
}
export function 制作产物URL(任务, 名) {
    if (!任务?.id || !任务?.token || typeof 名 !== "string" || !名) return "";
    return "/lvp/production/file?" + new URLSearchParams({ job: 任务.id, name: 名, token: 任务.token });
}
