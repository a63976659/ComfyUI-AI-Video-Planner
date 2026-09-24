import { 新段ID } from "./桥接/节点桥.js";
import { 分配中间帧 } from "./中间帧.js";

export const 默认语速 = Object.freeze({ 中文每分钟: 240, 英文每分钟: 130 });
const 词式 = /\p{Script=Han}|[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*/gu;

function 取词(文本, 语速) {
    if (![语速.中文每分钟, 语速.英文每分钟].every(n => typeof n === "number" && Number.isFinite(n) && n > 0)) {
        throw new Error("语速必须是大于0的有效数字");
    }
    if (typeof 文本 !== "string") throw new Error("台词必须是文字");
    if (/[\p{L}\p{N}]/u.test(文本.replace(词式, ""))) throw new Error("目前只支持中文和英文台词估时，请取消勾选其他语言的段");
    return [...文本.matchAll(词式)].map(m => ({
        起: m.index, 末: m.index + m[0].length, 中文: /\p{Script=Han}/u.test(m[0]),
    }));
}

export function 估算台词(文本, 语速 = 默认语速) {
    const 词 = 取词(文本, 语速);
    const 中文字数 = 词.filter(w => w.中文).length, 英文词数 = 词.length - 中文字数;
    return { 中文字数, 英文词数, 秒数: 60 * (中文字数 / 语速.中文每分钟 + 英文词数 / 语速.英文每分钟) };
}

function 拆台词(文本, 语速) {
    const 词 = 取词(文本, 语速);
    if (!词.length) throw new Error("勾选段没有可朗读台词，请取消勾选或补充字幕");
    const 片段 = [];
    let 起词 = 0, 起字 = 0;
    while (起词 < 词.length) {
        let 末词 = 起词, 秒 = 0, 句界 = 0, 分句界 = 0;
        while (末词 < 词.length) {
            const 加 = 60 / (词[末词].中文 ? 语速.中文每分钟 : 语速.英文每分钟);
            if (秒 + 加 > 15 + 1e-9) break;
            秒 += 加;
            const 间 = 文本.slice(词[末词].末, 词[末词 + 1]?.起 ?? 文本.length);
            末词++;
            if (/[。！？!?；;\n]/u.test(间) || /\.(?:[”"’']|\s|$)/u.test(间)) 句界 = 末词;
            else if (/[，,、：:]/u.test(间)) 分句界 = 末词;
        }
        if (末词 === 起词) throw new Error("当前语速下单字或单词超过15秒，请提高语速后重新预览");
        if (末词 < 词.length) 末词 = 句界 || 分句界 || 末词;
        const 末字 = 词[末词]?.起 ?? 文本.length;
        const 台词 = 文本.slice(起字, 末字);
        片段.push({ 台词, 时长: Math.max(5, Math.ceil(估算台词(台词, 语速).秒数 - 1e-9)) });
        起词 = 末词; 起字 = 末字;
    }
    return 片段;
}

function 同步提示词(s, 原台词, 台词, 时长) {
    let 词 = s.prompt || "";
    // 仅移除本功能保存的完整旧约束，保留用户追加的画面说明。
    if (s.台词时长提示) 词 = 词.replace(s.台词时长提示, "");
    if (原台词 !== 台词) 词 = 词.replaceAll(原台词, () => 台词);
    const 后缀 = `\n\n本段时长：${时长}秒。本段仅朗读以下台词，不重复前后段台词：${JSON.stringify(台词)}。画面动作配合本段台词节奏。`;
    return { prompt: 词 + 后缀, 台词时长提示: 后缀 };
}

export function 按台词重排(草, { 台词段, ...语速 } = {}) {
    语速 = { ...默认语速, ...语速 };
    if (!Array.isArray(草?.segments) || !草.segments.length) throw new Error("草稿中没有分段");
    if (!Array.isArray(台词段) || !台词段.length) throw new Error("请先勾选作为台词的字幕段");
    if (台词段.some(i => !Number.isInteger(i) || i < 0 || i >= 草.segments.length)) throw new Error("台词段选择已失效，请重新打开");
    if (草.segments.some(s => !Number.isFinite(s?.start) || !Number.isFinite(s?.end) || s.end <= s.start)) {
        throw new Error("草稿含无效时长，请先修正后重新预览");
    }
    const 选择 = new Set(台词段), segments = [], 变化 = [];
    let 时间 = 0;
    草.segments.forEach((s, i) => {
        const 片段 = 选择.has(i) ? 拆台词(s.字幕, 语速) : [{ 时长: s.end - s.start }];
        const 新段下标 = [], 子段 = [];
        for (const 片 of 片段) {
            const 新 = JSON.parse(JSON.stringify(s));
            新.start = 时间;
            时间 = Number((时间 + 片.时长).toFixed(9));
            新.end = 时间;
            if (选择.has(i)) {
                新.字幕 = 片.台词;
                Object.assign(新, 同步提示词(s, s.字幕, 片.台词, 片.时长));
                if (片段.length > 1 || !新.segment_id) 新.segment_id = 新段ID();
            }
            新段下标.push(segments.length + 子段.length);
            子段.push(新);
        }
        segments.push(...分配中间帧(s, 子段));
        if (选择.has(i)) 变化.push({ 原段: i, 原时长: s.end - s.start, 估时: 估算台词(s.字幕, 语速).秒数, 新段下标 });
    });
    if (时间 > 3600) throw new Error("重排后总时长超过60分钟，请减少台词或拆为多个计划；原草稿未修改");
    return { 草稿: { ...JSON.parse(JSON.stringify(草)), brief: { ...草.brief, 总时长: 时间 }, segments }, 变化 };
}
