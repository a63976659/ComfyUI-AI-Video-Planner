import { 默认语速, 按台词重排 } from "./台词时长.js";

export function 打开台词时长(草, 规划总时长 = 草.brief?.总时长) {
    const 框 = document.createElement("dialog");
    框.className = "lvp-speech-dialog";
    框.setAttribute("aria-label", "台词估时与拆段预览");
    const 样式 = document.createElement("style");
    样式.textContent = `
      .lvp-speech-dialog{width:min(720px,92vw);max-height:88vh;padding:14px;border:1px solid var(--border-color,#444);border-radius:8px;background:var(--comfy-menu-bg,#2b2b2b);color:var(--fg-color,#ddd);font:12px system-ui;box-sizing:border-box}
      .lvp-speech-dialog::backdrop{background:rgb(0 0 0 / .45)}
      .lvp-speech-dialog *{box-sizing:border-box}
      .lvp-speech-dialog h3{margin:0 0 8px;font-size:14px}
      .lvp-speech-dialog p{margin:6px 0;line-height:1.5}
      .lvp-speech-rates,.lvp-speech-actions{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:10px 0}
      .lvp-speech-rates label{display:flex;align-items:center;gap:6px}
      .lvp-speech-rate{width:76px}
      .lvp-speech-dialog input,.lvp-speech-dialog button{font:inherit;color:inherit;background:var(--comfy-input-bg,#222);border:1px solid var(--border-color,#555);border-radius:4px;padding:4px 7px}
      .lvp-speech-dialog button{cursor:pointer}
      .lvp-speech-dialog button:disabled{opacity:.45;cursor:not-allowed}
      .lvp-speech-dialog :focus-visible{outline:2px solid var(--p-primary-color,#4a9eff);outline-offset:2px}
      .lvp-speech-body{max-height:50vh;overflow:auto;border-block:1px solid var(--border-color,#444);padding:6px 0}
      .lvp-speech-choice{display:flex;gap:6px;align-items:flex-start;margin:6px 0;overflow-wrap:anywhere;white-space:pre-wrap}
      .lvp-speech-check{flex:none}
      .lvp-speech-item{padding:8px 0;border-top:1px solid var(--border-color,#444)}
      .lvp-speech-text{white-space:pre-wrap;overflow-wrap:anywhere}
      .lvp-speech-note{color:var(--p-text-muted-color,#aaa)}
      .lvp-speech-error{color:var(--p-error-color,#ff6b6b);min-height:18px}
      .lvp-speech-actions{justify-content:flex-end;margin-bottom:0}`;
    框.appendChild(样式);
    const 建 = (tag, 类, 文 = "") => {
        const el = document.createElement(tag); el.className = 类; el.textContent = 文; return el;
    };
    框.appendChild(建("h3", "", "台词估时与拆段预览"));
    框.appendChild(建("p", "lvp-speech-note", "仅勾选需要朗读的字幕；屏幕标题、说明文字请勿勾选。估时为近似值，不含表演停顿，不保证生成音频时长。"));
    const 语速行 = 建("div", "lvp-speech-rates");
    const 语速入 = {};
    for (const [键, 标签] of [["中文每分钟", "中文（字/分钟）"], ["英文每分钟", "英文（词/分钟）"]]) {
        const 标 = 建("label", "", 标签);
        const 入 = 建("input", "lvp-speech-rate"); 入.type = "number"; 入.min = "1"; 入.step = "any"; 入.value = 默认语速[键];
        入.oninput = 清预览;
        标.appendChild(入); 语速行.appendChild(标); 语速入[键] = 入;
    }
    框.appendChild(语速行);
    const 内容 = 建("div", "lvp-speech-body");
    const 选择框 = 草.segments.map((s, i) => {
        const 行 = 建("label", "lvp-speech-choice");
        const 入 = 建("input", "lvp-speech-check"); 入.type = "checkbox"; 入.checked = false;
        入.disabled = typeof s.字幕 !== "string" || !s.字幕.trim();
        入.onchange = 清预览;
        行.append(入, 建("span", "", `第${i + 1}段 · ${(s.end - s.start).toFixed(1)}秒 · ${s.字幕 || "（无字幕）"}`));
        内容.appendChild(行); return 入;
    });
    const 预览区 = 建("div", "lvp-speech-preview"); 内容.appendChild(预览区); 框.appendChild(内容);
    const 概要 = 建("p", "lvp-speech-summary"); 概要.setAttribute("aria-live", "polite"); 框.appendChild(概要);
    框.appendChild(建("p", "lvp-speech-note", "勾选段调整为5–15秒，向上取整秒；超长先按语句、再按词或汉字拆开，不截断原文。其余段保留时长并顺移。原画面描述和素材沿用，请核查分段提示词中的其他对白或时间描述。"));
    const 错误 = 建("p", "lvp-speech-error"); 错误.setAttribute("role", "alert"); 框.appendChild(错误);
    const 操作 = 建("div", "lvp-speech-actions");
    const 取消 = 建("button", "", "取消"), 预览 = 建("button", "", "预览重排"), 应用 = 建("button", "", "确认应用草稿");
    for (const 钮 of [取消, 预览, 应用]) 钮.type = "button";
    应用.disabled = true;
    操作.append(取消, 预览, 应用); 框.appendChild(操作);
    let 结果 = null, 返回 = null;
    function 清预览() {
        结果 = null; 应用.disabled = true; 预览区.replaceChildren(); 概要.textContent = ""; 错误.textContent = "";
    }
    预览.onclick = () => {
        清预览();
        try {
            结果 = 按台词重排(草, {
                台词段: 选择框.flatMap((入, i) => 入.checked && !入.disabled ? [i] : []),
                中文每分钟: Number(语速入.中文每分钟.value), 英文每分钟: Number(语速入.英文每分钟.value),
            });
            const 新草 = 结果.草稿;
            const 原总 = 草.segments.at(-1).end;
            const 原规划 = Number.isFinite(规划总时长) ? 规划总时长 : 原总;
            概要.textContent = `草稿 ${草.segments.length} → ${新草.segments.length} 段，${原总} → ${新草.brief.总时长}秒；规划总时长 ${原规划} → ${新草.brief.总时长}秒。确认后仅更新草稿，不填充执行节点。`;
            for (const 变化 of 结果.变化) {
                const 块 = 建("div", "lvp-speech-item");
                块.appendChild(建("p", "", `原第${变化.原段 + 1}段：${变化.原时长}秒，台词约${变化.估时.toFixed(1)}秒 → ${变化.新段下标.length}段`));
                for (const k of 变化.新段下标) {
                    const s = 新草.segments[k];
                    块.appendChild(建("p", "lvp-speech-text", `新第${k + 1}段 · ${s.start}–${s.end}秒（${s.end - s.start}秒）\n${s.字幕}`));
                    const 详情 = 建("details", "");
                    详情.append(建("summary", "", "查看同步后的提示词"), 建("p", "lvp-speech-text", s.prompt));
                    块.appendChild(详情);
                }
                预览区.appendChild(块);
            }
            应用.disabled = false;
        } catch (e) {
            清预览(); 错误.textContent = e.message || "估时失败，原草稿未修改";
        }
    };
    取消.onclick = () => 框.close();
    应用.onclick = () => { if (!结果 || 应用.disabled) return; 返回 = 结果.草稿; 框.close(); };
    框.addEventListener("cancel", e => { e.preventDefault(); 框.close(); });
    框.addEventListener("keydown", e => e.stopPropagation());
    框.addEventListener("keyup", e => e.stopPropagation());
    const 完成 = new Promise(resolve => 框.addEventListener("close", () => { 框.remove(); resolve(返回); }, { once: true }));
    document.body.appendChild(框);
    try { 框.showModal(); } catch (e) { 框.remove(); throw e; }
    return 完成;
}
