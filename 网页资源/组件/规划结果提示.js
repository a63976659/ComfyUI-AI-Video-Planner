export function 规划结果提示(meta = {}) {
    meta = meta || {};
    const warnings = Array.isArray(meta.警告) ? meta.警告 : [];
    const notes = warnings.map(w => typeof w === "string" ? w : [w?.阶段, w?.说明, w?.建议].filter(Boolean).join("："));
    if (Array.isArray(meta.未完成单元) && meta.未完成单元.length) notes.push(`未完成内容：${meta.未完成单元.join("、")}`);
    if (Array.isArray(meta.未输出集号) && meta.未输出集号.length) notes.push(`未输出集：${meta.未输出集号.join("、")}`);
    return { 待完善: !!notes.length || !!meta.未完成 || ["待完善", "部分输出"].includes(meta.输出状态),
             说明: notes.join("\n") || (meta.未完成 ? "内容尚未全部生成，请继续完善。" : "") };
}

export function 可交付规划(result) {
    const meta = result?.规划资料;
    const complete = meta && (Object.hasOwn(meta, "生成完成") ? meta.生成完成 === true && meta.本地校验?.通过 === true : meta.自动验收?.通过 === true);
    const seriesComplete = meta && (Object.hasOwn(meta, "生成完成") ? meta.全剧生成完成 === true : meta.全剧验收?.通过 === true);
    return !!complete && !meta.未完成 &&
        !meta.未完成单元?.length && !meta.未输出集号?.length &&
        !["待完善", "部分输出"].includes(meta.输出状态) &&
        (!result.分集?.length || seriesComplete);
}
