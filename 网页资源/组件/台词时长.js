import { 新段ID } from "./桥接/节点桥.js";
import { 分配中间帧 } from "./中间帧.js";
import { 清理旧台词模板 } from "./台词提示词清理.js";

export const 默认语速 = Object.freeze({ 中文每分钟: 240, 英文每分钟: 130 });
export const 默认台词设置 = Object.freeze({ ...默认语速, 逗号停顿: 0.15, 句末停顿: 0.3, 留白: 0.5, 数字读法: true, 保留镜头: true });
const 词式 = /\p{Script=Han}|[A-Za-z0-9]+(?:[.'’\-][A-Za-z0-9]+)*/gu;
const 复制 = x => JSON.parse(JSON.stringify(x));
const 取整 = x => Math.ceil(x - 1e-9);
export const 取台词文本 = s => typeof s?.台词 === "string" ? s.台词 : "";

function 校验设置(设置) {
    if (![设置.中文每分钟, 设置.英文每分钟].every(n => Number.isFinite(n) && n > 0)) throw new Error("语速必须是大于0的有效数字");
    for (const 键 of ["逗号停顿", "句末停顿", "留白"]) {
        if (设置[键] !== undefined && (!Number.isFinite(设置[键]) || 设置[键] < 0 || 设置[键] >= 30)) throw new Error("停顿和留白须为0至30秒之间的有效数字（不含30秒）");
    }
}

function 取词(文本, 设置) {
    校验设置(设置);
    if (typeof 文本 !== "string") throw new Error("台词必须是文字");
    if (/[\p{L}\p{N}]/u.test(文本.replace(词式, ""))) throw new Error("目前只支持中文和英文台词估时，请取消勾选其他语言的段");
    const 中文环境 = /\p{Script=Han}/u.test(文本);
    return [...文本.matchAll(词式)].map(m => {
        // 中文环境的数字按逐位读数、点和百分号保守估计，不改原文；歧义读法由用户写出。
        const 数字 = 设置.数字读法 === true && /^\d+(?:\.\d+)?$/.test(m[0]);
        const 中文数字 = 数字 && (中文环境 || !/[A-Za-z]/u.test(文本));
        const 百分号 = 数字 && /[%％]/u.test(文本[m.index + m[0].length] || "");
        return { 起: m.index, 末: m.index + m[0].length, 中文: 中文数字 || /\p{Script=Han}/u.test(m[0]), 单位: 数字 ? m[0].length + (百分号 ? (中文数字 ? 3 : 1) : 0) : 1 };
    });
}
function 停顿秒(间, 设置) {
    const 句 = (间.match(/[。！？!?；;…\n]+|\.(?=[”"’'\s]|$)/gu) || []).length;
    const 逗 = (间.match(/[，,、：:]+/gu) || []).length;
    return 句 * (设置.句末停顿 || 0) + 逗 * (设置.逗号停顿 || 0);
}
export function 估算台词(文本, 设置 = 默认语速) {
    const 词 = 取词(文本, 设置);
    const 中文字数 = 词.filter(w => w.中文).reduce((n, w) => n + w.单位, 0);
    const 英文词数 = 词.filter(w => !w.中文).reduce((n, w) => n + w.单位, 0);
    const 停顿 = 词.reduce((秒, w, i) => 秒 + 停顿秒(文本.slice(w.末, 词[i + 1]?.起 ?? 文本.length), 设置), 0);
    return { 中文字数, 英文词数, 秒数: 60 * (中文字数 / 设置.中文每分钟 + 英文词数 / 设置.英文每分钟) + 停顿 + (词.length ? 设置.留白 || 0 : 0) };
}
export function 台词估时详情(s, 设置 = 默认台词设置, 文本 = 取台词文本(s)) {
    const 中 = 估算台词(文本, 设置);
    const 慢 = 估算台词(文本, { ...设置, 中文每分钟: 设置.中文每分钟 * 0.8, 英文每分钟: 设置.英文每分钟 * 0.8 });
    const 快 = 估算台词(文本, { ...设置, 中文每分钟: 设置.中文每分钟 * 1.2, 英文每分钟: 设置.英文每分钟 * 1.2 });
    const 计时 = 有效配音计时(s, 文本);
    const 秒 = 计时 ? 计时.时长 + (设置.留白 || 0) : 中.秒数;
    return { ...中, 秒数: 秒, 慢: 慢.秒数, 正常: 中.秒数, 快: 快.秒数, 来源: 计时 ? "配音测时" : "文字估算", 偏紧: 秒 > s.end - s.start + 1e-9, 数字提示: /\d/u.test(文本) && 设置.数字读法 === true };
}

function 拆台词(文本, 设置) {
    const 词 = 取词(文本, 设置);
    if (!词.length) throw new Error("勾选段没有可朗读台词，请取消勾选或补充台词");
    const 留白 = 设置.留白 || 0, 容量 = 30 - 留白;
    const 累加 = [0], 句界 = [];
    词.forEach((w, i) => {
        const 间 = 文本.slice(w.末, 词[i + 1]?.起 ?? 文本.length);
        const 秒 = 60 * w.单位 / (w.中文 ? 设置.中文每分钟 : 设置.英文每分钟) + 停顿秒(间, 设置);
        if (秒 > 容量 + 1e-9) throw new Error("当前语速下单字、单词或停顿超过30秒，请调整语速或留白后重新预览");
        累加.push(累加.at(-1) + 秒);
        句界.push(/[。！？!?；;…\n]|\.(?:[”"’']|\s|$)/u.test(间) ? 0 : /[，,、：:]/u.test(间) ? 0.6 : 2);
    });
    if (累加.at(-1) > 3600) throw new Error("重排后总时长超过60分钟，请拆为多个计划；原草稿未修改");
    const 片段 = [];
    let 起词 = 0, 起字 = 0;
    while (起词 < 词.length) {
        const 剩秒 = 累加.at(-1) - 累加[起词];
        const 目标 = 剩秒 / Math.max(1, 取整(剩秒 / 容量));
        let 末词 = 起词, 得分 = Infinity;
        for (let k = 起词 + 1; k <= 词.length; k++) {
            const 秒 = 累加[k] - 累加[起词];
            if (秒 > 容量 + 1e-9) break;
            if (剩秒 <= 容量 + 1e-9) { 末词 = k; continue; }
            const 余秒 = 累加.at(-1) - 累加[k];
            const 分 = Math.abs(秒 - 目标) + 句界[k - 1] + (余秒 > 0 && 余秒 + 留白 < 5 ? 5 : 0);
            if (分 < 得分) { 得分 = 分; 末词 = k; }
        }
        const 末字 = 词[末词]?.起 ?? 文本.length;
        const 台词 = 文本.slice(起字, 末字);
        片段.push({ 台词, 时长: Math.max(5, 取整(估算台词(台词, 设置).秒数)) });
        起词 = 末词; 起字 = 末字;
    }
    return 片段;
}
export function 保护台词提示词(s, 新词 = s.prompt || "") {
    // 台词和时长保存在结构字段；改写时由模型融入正文，保存不追加朗读模板。
    return { prompt: 清理旧台词模板(新词), 台词时长提示: "" };
}
const 规范台词 = 文 => String(文).normalize("NFKC").toLowerCase().replace(/[\p{P}\p{Z}\s]/gu, "");
export function 解析配音时间戳(文本) {
    if (typeof 文本 !== "string" || 文本.length > 2_000_000) throw new Error("时间戳文件无效或超过2MB");
    let 项;
    if (/^[\s\uFEFF]*[\[{]/u.test(文本)) {
        const json = JSON.parse(文本.replace(/^\uFEFF/u, ""));
        项 = Array.isArray(json) ? json : json.segments || json.cues;
        if (!Array.isArray(项)) throw new Error("JSON需包含segments/cues数组，每项为start、end、text");
        项 = 项.map(s => ({ 起: s.start, 末: s.end, 台词: s.text }));
    } else {
        const 秒 = 值 => { const [h, m, s] = 值.replace(",", ".").split(":").map(Number); return h * 3600 + m * 60 + s; };
        项 = 文本.replace(/^\uFEFF/u, "").replace(/\r/g, "").trim().split(/\n\s*\n/u).map(块 => {
            const 行 = 块.split("\n");
            if (/^\d+$/u.test(行[0])) 行.shift();
            const 时间 = 行.shift()?.match(/^(\d{2}:[0-5]\d:[0-5]\d[,.]\d{3})\s*-->\s*(\d{2}:[0-5]\d:[0-5]\d[,.]\d{3})$/u);
            if (!时间) throw new Error("SRT时间格式须为00:00:00,000 --> 00:00:01,000");
            return { 起: 秒(时间[1]), 末: 秒(时间[2]), 台词: 行.join("\n") };
        });
    }
    if (!项.length || 项.length > 10000) throw new Error("时间戳需包含1至10000条台词");
    let 末 = 0;
    for (const s of 项) {
        if (!Number.isFinite(s.起) || !Number.isFinite(s.末) || s.起 < 末 - 1e-9 || s.末 <= s.起 || s.末 > 3600 || typeof s.台词 !== "string" || !规范台词(s.台词)) throw new Error("时间戳含无效台词、重叠或越界时间，请先修正");
        末 = s.末;
    }
    return 项;
}
export function 校验配音计时(计时, 文本) {
    if (!计时 || !Number.isFinite(计时.时长) || 计时.时长 <= 0 || 计时.时长 > 3600 || typeof 计时.文件名 !== "string" || !计时.文件名) throw new Error("请先读取有效配音文件的时长");
    if (计时.文本 !== 文本) throw new Error("台词已修改，原配音测时已失效，请重新测量和核对");
    if (计时.片段) {
        const 项 = 解析配音时间戳(JSON.stringify(计时.片段.map(s => ({ start: s.起, end: s.末, text: s.台词 }))));
        if (项.at(-1).末 > 计时.时长 + 0.05) throw new Error("时间戳超过配音文件时长");
        if (规范台词(项.map(s => s.台词).join("")) !== 规范台词(文本)) throw new Error("时间戳台词与本段台词不一致；请使用对应配音，不会自动改写台词");
    }
    if (计时.文件起点 !== undefined && (!Number.isFinite(计时.文件起点) || 计时.文件起点 < 0)) throw new Error("配音切片起点无效");
    return 计时;
}
function 有效配音计时(s, 文本) { return s.配音计时 ? 校验配音计时(s.配音计时, 文本) : null; }

function 按配音拆分(s, 文本, 设置) {
    const 计时 = 有效配音计时(s, 文本);
    if (!计时) return null;
    const 留白 = 设置.留白 || 0;
    if (计时.时长 + 留白 <= 30) return [{ 台词: 文本, 时长: Math.max(5, 取整(计时.时长 + 留白)), 配音计时: 计时 }];
    if (!计时.片段?.length) throw new Error("配音超过单段30秒，请导入对应SRT/JSON时间戳后按句拆分，不能仅按总时长切台词");
    const 片段 = [], 项 = 计时.片段, 索引 = [];
    for (let i = 0; i < 文本.length;) { const 字 = String.fromCodePoint(文本.codePointAt(i)); for (const _ of 规范台词(字)) 索引.push(i); i += 字.length; }
    let 起 = 0, 起字 = 0, 已读 = 0, 段起 = 0;
    while (起 < 项.length) {
        const 剩秒 = 计时.时长 - 段起, 容量 = 30 - 留白;
        const 目标 = 剩秒 / Math.max(1, 取整(剩秒 / 容量));
        let 止 = 起, 得分 = Infinity;
        for (let k = 起; k < 项.length; k++) {
            const 末 = 项[k + 1]?.起 ?? 计时.时长, 秒 = 末 - 段起;
            if (秒 > 容量 + 1e-9) break;
            if (剩秒 <= 容量 + 1e-9) { 止 = k; continue; }
            const 余 = 计时.时长 - 末;
            const 分 = Math.abs(秒 - 目标) + (余 > 0 && 余 + 留白 < 5 ? 5 : 0);
            if (分 < 得分) { 得分 = 分; 止 = k; }
        }
        const 段末 = 项[止 + 1]?.起 ?? 计时.时长;
        if (段末 - 段起 + 留白 > 30 + 1e-9) throw new Error("配音单句或停顿超过30秒，请先在句内补充时间戳或调整配音");
        const 本句 = 项.slice(起, 止 + 1);
        已读 += 规范台词(本句.map(x => x.台词).join("")).length;
        const 末字 = 索引[已读] ?? 文本.length;
        const 台词 = 文本.slice(起字, 末字);
        const 新计时 = { ...计时, 文本: 台词, 时长: 段末 - 段起, 文件起点: (计时.文件起点 || 0) + 段起, 片段: 本句.map(x => ({ ...x, 起: x.起 - 段起, 末: x.末 - 段起 })) };
        片段.push({ 台词, 时长: Math.max(5, 取整(新计时.时长 + 留白)), 配音计时: 新计时 });
        起 = 止 + 1; 起字 = 末字; 段起 = 段末;
    }
    return 片段;
}
export function 按台词重排(草, { 台词段, ...设置 } = {}) {
    设置 = { ...默认语速, ...设置 };
    校验设置(设置);
    if (!Array.isArray(草?.segments) || !草.segments.length) throw new Error("草稿中没有分段");
    if (!Array.isArray(台词段) || !台词段.length) throw new Error("请先勾选需要朗读的台词段");
    if (台词段.some(i => !Number.isInteger(i) || i < 0 || i >= 草.segments.length)) throw new Error("台词段选择已失效，请重新打开");
    if (草.segments.some(s => !Number.isFinite(s?.start) || !Number.isFinite(s?.end) || s.end <= s.start)) throw new Error("草稿含无效时长，请先修正后重新预览");
    const 选择 = new Set(台词段), segments = [], 变化 = [];
    let 时间 = 0;
    草.segments.forEach((s, i) => {
        const 文本 = 取台词文本(s), 原时长 = s.end - s.start;
        const 片段 = 选择.has(i) ? (按配音拆分(s, 文本, 设置) || 拆台词(文本, 设置)) : [{ 时长: 原时长 }];
        if (选择.has(i)) {
            const 本设置 = s.台词设置 || {};
            const 动作秒 = 本设置.动作秒 ?? (设置.保留镜头 ? 原时长 : 0);
            if (!Number.isFinite(动作秒) || 动作秒 < 0 || 动作秒 > 3600) throw new Error("动作所需秒数无效，请先修正");
            const 台词总 = 片段.reduce((n, x) => n + x.时长, 0);
            const 需求 = 本设置.先后发生 ? 台词总 + 动作秒 : Math.max(台词总, 动作秒);
            if (需求 > 片段.length * 30 + 1e-9) throw new Error("第" + (i + 1) + "段动作与台词需要" + 需求.toFixed(1) + "秒，现有拆段放不下；请增加镜头或调整动作预算");
            let 剩 = Math.max(0, 需求 - 台词总);
            for (const 片 of 片段) { const 加 = Math.min(30 - 片.时长, 剩); 片.时长 += 加; 剩 -= 加; }
        }
        const 新段下标 = [], 子段 = [];
        for (const 片 of 片段) {
            const 新 = 复制(s); 新.start = 时间; 时间 = Number((时间 + 片.时长).toFixed(9)); 新.end = 时间;
            if (选择.has(i)) {
                新.台词 = 片.台词; 新.台词参与估时 = true;
                if (片.配音计时) 新.配音计时 = 复制(片.配音计时);
                if (新.配音计时?.输出原声) {
                    const 配 = 新.配音计时;
                    新.refs = { ...新.refs, 台词配音: { 文件名: 配.文件名, 起: 配.文件起点 || 0, 末: (配.文件起点 || 0) + 配.时长 } };
                } else if (新.refs) delete 新.refs.台词配音;
                if (片段.length > 1 && 新.台词设置?.动作秒 !== undefined) {
                    const 总长 = 片段.reduce((n, p) => n + p.时长, 0);
                    新.台词设置.动作秒 *= 片.时长 / 总长;
                }
                新.prompt = 清理旧台词模板(s.prompt || "");
                if (文本 !== 片.台词) 新.prompt = 新.prompt.replaceAll(文本, () => 片.台词);
                Object.assign(新, 保护台词提示词(新));
                if (片段.length > 1 || !新.segment_id) 新.segment_id = 新段ID();
                if (片段.length > 1) 新.台词拆段待核查 = true;
            }
            新段下标.push(segments.length + 子段.length); 子段.push(新);
        }
        segments.push(...分配中间帧(s, 子段));
        if (选择.has(i)) 变化.push({ 原段: i, 原时长, 估时: 有效配音计时(s, 文本)?.时长 ?? 估算台词(文本, 设置).秒数, 新段下标 });
    });
    if (时间 > 3600) throw new Error("重排后总时长超过60分钟，请减少台词或拆为多个计划；原草稿未修改");
    return { 草稿: { ...复制(草), 台词设置: { ...设置 }, brief: { ...草.brief, 总时长: 时间 }, segments }, 变化 };
}
