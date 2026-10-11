import { 默认台词设置, 按台词重排, 取台词文本, 台词估时详情, 解析配音时间戳, 校验配音计时 } from "./台词时长.js";

export function 打开台词时长(草, 规划总时长 = 草.brief?.总时长) {
    const 编辑草 = JSON.parse(JSON.stringify(草));
    const 设置 = { ...默认台词设置, ...草.台词设置 };
    const 框 = document.createElement("dialog");
    框.className = "lvp-speech-dialog";
    框.setAttribute("aria-label", "台词估时与拆段预览");
    const 样式 = document.createElement("style");
    样式.textContent = [
        ".lvp-speech-dialog{width:min(850px,94vw);max-height:90vh;padding:16px;border:1px solid var(--border-color,#444);border-radius:10px;background:var(--comfy-menu-bg,#2b2b2b);color:var(--fg-color,#ddd);font:12px system-ui;box-sizing:border-box}",
        ".lvp-speech-dialog::backdrop{background:rgb(0 0 0 / .45)}.lvp-speech-dialog *{box-sizing:border-box}",
        ".lvp-speech-dialog h3{margin:0 0 8px;font-size:15px}.lvp-speech-dialog p{margin:6px 0;line-height:1.5}",
        ".lvp-speech-rates,.lvp-speech-actions,.lvp-speech-audio{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:10px 0}",
        ".lvp-speech-rates label{display:flex;align-items:center;gap:5px}.lvp-speech-rate{width:70px}",
        ".lvp-speech-dialog input,.lvp-speech-dialog button,.lvp-speech-dialog select{font:inherit;color:inherit;background:var(--comfy-input-bg,#222);border:1px solid var(--border-color,#555);border-radius:4px;padding:4px 7px}",
        ".lvp-speech-dialog button{cursor:pointer}.lvp-speech-dialog button:disabled{opacity:.45;cursor:not-allowed}",
        ".lvp-speech-dialog :focus-visible{outline:2px solid var(--p-primary-color,#4a9eff);outline-offset:2px}",
        ".lvp-speech-body{max-height:48vh;overflow:auto;padding:4px 0}.lvp-speech-choice{display:flex;gap:6px;align-items:flex-start;overflow-wrap:anywhere;white-space:pre-wrap}",
        ".lvp-speech-row,.lvp-speech-item{padding:10px;border:1px solid var(--border-color,#444);border-radius:6px;margin:8px 0}",
        ".lvp-speech-check{flex:none}.lvp-speech-text{white-space:pre-wrap;overflow-wrap:anywhere}",
        ".lvp-speech-note{color:var(--p-text-muted-color,#aaa)}.lvp-speech-error{color:var(--p-error-color,#ff6b6b);min-height:18px}",
        ".lvp-speech-stats{font-variant-numeric:tabular-nums}.lvp-speech-stats.tight{color:var(--p-error-color,#ffb454)}",
        ".lvp-speech-actions{justify-content:flex-end;margin-bottom:0}.lvp-speech-dialog audio{max-width:100%;height:32px}",
    ].join("\n");
    框.appendChild(样式);
    const 建 = (tag, 类, 文 = "") => { const el = document.createElement(tag); el.className = 类; el.textContent = 文; return el; };
    框.appendChild(建("h3", "", "台词估时与拆段预览"));
    框.appendChild(建("p", "lvp-speech-note", "先检查，再决定是否调整。只勾选需要朗读的台词。慢／正常／快表示语速假设，不是准确率。"));
    const 语速行 = 建("div", "lvp-speech-rates"), 语速入 = {};
    for (const [键, 标签] of [["中文每分钟", "中文字/分钟"], ["英文每分钟", "英文词/分钟"], ["逗号停顿", "逗号停顿秒"], ["句末停顿", "句末停顿秒"], ["留白", "每段留白秒"]]) {
        const 标 = 建("label", "", 标签), 入 = 建("input", "lvp-speech-rate");
        入.type = "number"; 入.min = 键.endsWith("每分钟") ? "1" : "0"; 入.step = "any"; 入.value = 设置[键];
        入.oninput = 改参数; 标.appendChild(入); 语速行.appendChild(标); 语速入[键] = 入;
    }
    const 保留标 = 建("label", "", "保留原镜头时长（避免压短动作）"), 保留 = 建("input", "lvp-speech-keep");
    保留.type = "checkbox"; 保留.checked = 设置.保留镜头 !== false; 保留.onchange = 改参数;
    保留标.appendChild(保留); 语速行.appendChild(保留标);
    框.appendChild(语速行);
    const 内容 = 建("div", "lvp-speech-body"), 行表 = [], 待办 = new Set(), 播放器 = [], 取消读取 = new Set();
    let 关闭 = false, 导入代 = 0;
    const 选择框 = 编辑草.segments.map((s, i) => {
        const 盒 = 建("div", "lvp-speech-row"), 行 = 建("label", "lvp-speech-choice");
        const 入 = 建("input", "lvp-speech-check"); 入.type = "checkbox"; 入.checked = s.台词参与估时 === true;
        const 文本 = 取台词文本(s);
        入.disabled = typeof 文本 !== "string" || !文本.trim();
        入.onchange = 改参数;
        行.append(入, 建("span", "", "第" + (i + 1) + "段 · 镜头" + (s.end - s.start).toFixed(1) + "秒 · " + (文本 || "（无台词）")));
        const 统计 = 建("p", "lvp-speech-stats"); 统计.setAttribute("aria-live", "polite"); 行表.push(统计);
        盒.append(行, 统计);
        const 动作行 = 建("div", "lvp-speech-rates");
        const 动作标 = 建("label", "", "动作至少秒"), 动作 = 建("input", "lvp-speech-motion");
        动作.type = "number"; 动作.min = "0"; 动作.max = "3600"; 动作.step = "any"; 动作.value = s.台词设置?.动作秒 ?? "";
        动作.title = "留空按上方保留镜头开关处理；填0表示不额外保留动作时间";
        动作.oninput = () => { s.台词设置 = { ...s.台词设置 }; if (动作.value === "") delete s.台词设置.动作秒; else s.台词设置.动作秒 = Number(动作.value); 改参数(); };
        动作标.appendChild(动作); 动作行.appendChild(动作标);
        const 顺序标 = 建("label", "", "动作在台词之后"), 顺序 = 建("input", "");
        顺序.type = "checkbox"; 顺序.checked = s.台词设置?.先后发生 === true;
        顺序.onchange = () => { s.台词设置 = { ...s.台词设置, 先后发生: 顺序.checked }; 改参数(); };
        顺序标.appendChild(顺序); 动作行.appendChild(顺序标); 盒.appendChild(动作行);
        const 精确 = 建("details", ""), 音区 = 建("div", "lvp-speech-audio");
        精确.appendChild(建("summary", "", "按已有配音测时与试听"));
        const 选音 = 建("button", "", "选择媒体池配音"), 音选 = 建("select", "lvp-speech-audio-select");
        选音.type = "button"; 音选.hidden = true; 音选.setAttribute("aria-label", "第" + (i + 1) + "段配音");
        const 导入 = 建("input", "lvp-speech-timestamps"); 导入.type = "file"; 导入.accept = ".srt,.json"; 导入.title = "导入本段配音对应的句级时间戳；JSON每项为start、end、text";
        const 清音 = 建("button", "", "恢复文字估算"); 清音.type = "button";
        const 原声标 = 建("label", "", "成片使用这条配音原声"), 原声 = 建("input", "lvp-speech-source");
        原声.type = "checkbox"; 原声.checked = s.配音计时?.输出原声 !== false;
        原声.onchange = () => { if (s.配音计时) s.配音计时.输出原声 = 原声.checked; 改参数(); };
        原声标.appendChild(原声);
        const 播放 = 建("audio", ""); 播放.controls = true; 播放.preload = "metadata"; 播放器.push(播放);
        if (s.配音计时?.文件名) 播放.src = "/lvp/media/file?name=" + encodeURIComponent(s.配音计时.文件名);
        const 音提示 = 建("p", "lvp-speech-note", s.配音计时 ? s.配音计时.文件名 + " · " + s.配音计时.时长.toFixed(2) + "秒" : "先在参考文件区上传配音。配音须对应本段台词；超过30秒需导入SRT/JSON句界。");
        async function 办理(fn) {
            const 代 = ++导入代; 待办.add(代); 清预览(); 应用.disabled = true;
            try { await fn(() => !关闭 && 代 === 导入代); }
            catch (e) { if (!关闭 && 代 === 导入代) 错误.textContent = e.message || "配音读取失败"; }
            finally { 待办.delete(代); if (!关闭) { 清预览(false); 刷估时(); } }
        }
        选音.onclick = () => 办理(async 有效 => {
            const resp = await fetch("/lvp/media/list"); if (!resp.ok) throw new Error("读取媒体池失败");
            const 数据 = await resp.json(); if (!有效()) return;
            音选.replaceChildren();
            const 默认 = 建("option", "", "请选择对应配音"); 默认.value = ""; 音选.appendChild(默认);
            for (const x of 数据.items || []) if (/\.(wav|mp3|flac|ogg|m4a|aac|opus)$/i.test(x.name)) { const o = 建("option", "", x.name); o.value = x.name; 音选.appendChild(o); }
            音选.hidden = false;
            if (音选.children.length === 1) throw new Error("媒体池没有音频，请先在参考文件区上传");
        });
        音选.onchange = () => {
            const 名 = 音选.value; if (!名) return;
            for (const 取消 of 取消读取) 取消();
            return 办理(async 有效 => {
                const 数据 = await new Promise((resolve, reject) => {
                    const 成 = () => { 清(); resolve(播放.duration); }, 败 = () => { 清(); reject(new Error("浏览器无法读取此音频，请转换为WAV或MP3后重试")); };
                    const 取消 = () => { 清(); reject(new Error("已取消配音读取")); };
                    const 超时 = setTimeout(() => { 清(); reject(new Error("配音读取超时，请检查文件后重试")); }, 45000);
                    const 清 = () => { clearTimeout(超时); 取消读取.delete(取消); 播放.removeEventListener("loadedmetadata", 成); 播放.removeEventListener("error", 败); };
                    取消读取.add(取消);
                    播放.addEventListener("loadedmetadata", 成, { once: true }); 播放.addEventListener("error", 败, { once: true });
                    播放.src = "/lvp/media/file?name=" + encodeURIComponent(名); 播放.load();
                });
                if (!有效()) return;
                const 计时 = { 文件名: 名, 时长: 数据, 文件起点: 0, 文本: 取台词文本(s), 输出原声: 原声.checked };
                校验配音计时(计时, 计时.文本); s.配音计时 = 计时; 入.checked = true;
                音提示.textContent = 名 + " · 实测" + 数据.toFixed(2) + "秒。请试听确认台词一致。";
            });
        };
        导入.onchange = () => 办理(async 有效 => {
            const 文件 = 导入.files?.[0]; if (!文件) return;
            if (文件.size > 2_000_000) throw new Error("时间戳文件超过2MB");
            const 文 = await 文件.text(); if (!有效()) return;
            const 片段 = 解析配音时间戳(文);
            const 计时 = { ...s.配音计时, 片段 }; 校验配音计时(计时, 取台词文本(s));
            s.配音计时 = 计时; 音提示.textContent = 计时.文件名 + " · " + 片段.length + "句已匹配；切点与原台词均保留。";
        });
        清音.onclick = () => { 导入代++; for (const 取消 of 取消读取) 取消(); delete s.配音计时; 播放.pause?.(); 播放.removeAttribute("src"); 音提示.textContent = "已恢复文字估算"; 改参数(); };
        音区.append(选音, 音选, 导入, 清音, 原声标, 播放); 精确.append(音区, 音提示);
        精确.appendChild(建("p", "lvp-speech-note", "原声在输出时替换本段生成声音；镜头仍由H3生成，口型需要试听核查。时间戳由已有配音工具导出，本功能不自动识别语音。"));
        盒.appendChild(精确); 内容.appendChild(盒); return 入;
    });
    const 预览区 = 建("div", "lvp-speech-preview"); 内容.appendChild(预览区); 框.appendChild(内容);
    const 概要 = 建("p", "lvp-speech-summary"); 概要.setAttribute("aria-live", "polite"); 框.appendChild(概要);
    框.appendChild(建("p", "lvp-speech-note", "文字估算计入可调停顿和留白；数字在中文环境按逐位朗读估计，特殊读法请写出。拆分优先语义句界并平衡段长。拆出的画面和素材沿用，应用前请核查重复动作、旧时间描述及素材。"));
    const 错误 = 建("p", "lvp-speech-error"); 错误.setAttribute("role", "alert"); 框.appendChild(错误);
    const 操作 = 建("div", "lvp-speech-actions");
    const 取消 = 建("button", "", "取消"), 预览 = 建("button", "", "预览重排"), 应用 = 建("button", "", "确认应用草稿");
    for (const 钮 of [取消, 预览, 应用]) 钮.type = "button";
    应用.disabled = true; 操作.append(取消, 预览, 应用); 框.appendChild(操作);
    let 结果 = null, 返回 = null;
    function 读设置() {
        return { ...设置, ...Object.fromEntries(Object.entries(语速入).map(([键, 入]) => [键, 入.value === "" ? NaN : Number(入.value)])), 保留镜头: 保留.checked };
    }
    function 清预览(清错 = true) { 结果 = null; 应用.disabled = true; 预览区.replaceChildren(); 概要.textContent = ""; if (清错) 错误.textContent = ""; }
    function 刷估时() {
        let 已选 = 0, 紧 = 0;
        编辑草.segments.forEach((s, i) => {
            const el = 行表[i];
            try {
                const x = 台词估时详情(s, 读设置());
                const 范围 = "慢 " + x.慢.toFixed(1) + " / 正常 " + x.正常.toFixed(1) + " / 快 " + x.快.toFixed(1) + "秒";
                el.textContent = (x.来源 === "配音测时" ? "配音实测＋留白 " + x.秒数.toFixed(1) + "秒；文字参考：" : "") + 范围 + " · " + (x.偏紧 ? "镜头偏紧" : "镜头可容纳") + (x.数字提示 ? " · 请核对数字读法" : "");
                el.classList.toggle("tight", x.偏紧 && 选择框[i].checked);
                if (选择框[i].checked) { 已选++; if (x.偏紧) 紧++; }
            } catch (e) { el.textContent = e.message; el.classList.remove("tight"); }
        });
        if (!结果 && !待办.size) 概要.textContent = 已选 ? "已选" + 已选 + "段，" + 紧 + "段偏紧。当前仅检查，尚未修改草稿；点「预览重排」查看变化。" : "尚未选择朗读段，当前仅检查。";
    }
    function 改参数() { 清预览(); 刷估时(); }
    预览.onclick = () => {
        清预览();
        if (待办.size) { 错误.textContent = "配音或时间戳读取中，请等待完成后预览"; return; }
        try {
            编辑草.segments.forEach((s, i) => { s.台词参与估时 = 选择框[i].checked && !选择框[i].disabled; });
            结果 = 按台词重排(编辑草, { ...读设置(), 台词段: 选择框.flatMap((入, i) => 入.checked && !入.disabled ? [i] : []) });
            const 新草 = 结果.草稿, 原总 = 草.segments.at(-1).end, 原规划 = Number.isFinite(规划总时长) ? 规划总时长 : 原总;
            概要.textContent = "草稿 " + 草.segments.length + " → " + 新草.segments.length + " 段，" + 原总 + " → " + 新草.brief.总时长 + "秒；规划总时长 " + 原规划 + " → " + 新草.brief.总时长 + "秒。确认后仅更新草稿，不填充执行节点。";
            for (const 变化 of 结果.变化) {
                const 块 = 建("div", "lvp-speech-item");
                块.appendChild(建("p", "", "原第" + (变化.原段 + 1) + "段：" + 变化.原时长 + "秒，台词约" + 变化.估时.toFixed(1) + "秒 → " + 变化.新段下标.length + "段"));
                if (变化.新段下标.length > 1) 块.appendChild(建("p", "lvp-speech-note", "画面与素材沿用，请重新分配各子段动作，避免重复整套动作。"));
                for (const k of 变化.新段下标) {
                    const s = 新草.segments[k];
                    块.appendChild(建("p", "lvp-speech-text", "新第" + (k + 1) + "段 · " + s.start + "–" + s.end + "秒（" + (s.end - s.start) + "秒）\n" + 取台词文本(s)));
                    if (s.配音计时) 块.appendChild(建("p", "lvp-speech-note", "配音切片：" + (s.配音计时.文件起点 || 0).toFixed(2) + "–" + ((s.配音计时.文件起点 || 0) + s.配音计时.时长).toFixed(2) + "秒；整秒段长多出的时间保留为静音。"));
                    const 详情 = 建("details", ""); 详情.append(建("summary", "", "查看同步后的提示词"), 建("p", "lvp-speech-text", s.prompt)); 块.appendChild(详情);
                }
                预览区.appendChild(块);
            }
            应用.disabled = false;
        } catch (e) { 清预览(); 错误.textContent = e.message || "估时失败，原草稿未修改"; }
    };
    取消.onclick = () => 框.close();
    应用.onclick = () => { if (!结果 || 应用.disabled || 待办.size) return; 返回 = 结果.草稿; 框.close(); };
    框.addEventListener("cancel", e => { e.preventDefault(); 框.close(); });
    框.addEventListener("keydown", e => e.stopPropagation()); 框.addEventListener("keyup", e => e.stopPropagation());
    const 完成 = new Promise(resolve => 框.addEventListener("close", () => { 关闭 = true; 导入代++; for (const 取消 of 取消读取) 取消(); 播放器.forEach(p => { p.pause?.(); p.removeAttribute("src"); p.load?.(); }); 框.remove(); resolve(返回); }, { once: true }));
    document.body.appendChild(框); 刷估时();
    try { 框.showModal(); } catch (e) { 框.remove(); throw e; }
    return 完成;
}
