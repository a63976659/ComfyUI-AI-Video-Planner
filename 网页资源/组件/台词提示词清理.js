// 旧台词估时模板仅是程序附加信息，不是分镜、对白或 H3 章节。
const 旧模板 = /(^|\r?\n\r?\n)本段时长：[\d.eE+\-]+秒。本段仅朗读以下台词，不重复前后段台词："(?:[^"\\]|\\[\s\S])*"。画面动作配合本段台词节奏。/g;

export function 清理旧台词模板(文本) {
    if (typeof 文本 !== "string") return 文本;
    // 锁定对白中的相同文字属于作者内容，不作为程序模板删除。
    return 文本.split(/(<d>[\s\S]*?<\/d>)/g).map((part, i) => i % 2 ? part : part.replace(旧模板, "")).join("");
}

export function 清理草稿台词模板(草稿) {
    if (!Array.isArray(草稿?.segments)) return 草稿;
    return { ...草稿, segments: 草稿.segments.map(s => {
        if (!s || typeof s !== "object") return s;
        const 新 = { ...s };
        if (typeof s.prompt === "string") 新.prompt = 清理旧台词模板(s.prompt);
        if (typeof s.分镜原稿 === "string") 新.分镜原稿 = 清理旧台词模板(s.分镜原稿);
        delete 新.台词时长提示;
        return 新;
    }) };
}
