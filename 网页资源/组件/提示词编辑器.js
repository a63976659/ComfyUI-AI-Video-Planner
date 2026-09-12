// contenteditable 提示词；@ 弹参考列表 → 插入 <Picture N>/<Audio J>/<Video K> chip；
// 读回时把 chip 还原为标签文本（与后端 执行/参考素材.py 提取标签 对齐）。
import { 创建画风预设选择 } from "./画风预设选择.js";

const 标签re = /<(Picture|Audio|Video)\s*(\d+)>/gi;
const 单标签re = /^<(Picture|Audio|Video)\s*(\d+)>$/i;
const 槽到标签 = { 图片: "Picture", 音频: "Audio", 视频: "Video" };
const 标签到中文 = { Picture: "图像", Audio: "音频", Video: "视频" };
// 输出分辨率选项：与后端 节点/节点公用.py 分辨率选项 逐字一致（单一真源在 Python，前端为镜像）。
export const 分辨率选项 = [
    "1:1 (方形)", "2:3 (竖照片)", "3:2 (照片)", "3:4 (竖标准)",
    "4:3 (标准)", "9:16 (竖宽屏)", "16:9 (宽屏)", "21:9 (超宽屏)",
];
export const 默认分辨率 = "16:9 (宽屏)";
export const 默认百万像素 = 1.0;
// 标签 → 中文显示名（<Picture 1> → 图像1）；dataset.tag 仍存原始标签，与后端提取标签对齐
function 显示名(标签) {
    const m = 单标签re.exec(标签 || "");
    return m ? `${标签到中文[m[1]]}${m[2]}` : (标签 || "").replace(/[<>]/g, "");
}

export function 创建提示词编辑器(容器, { 变更, 取参考列表, 分辨率变更, 百万像素变更, 全局提示词变更 }) {
    const 盒 = document.createElement("div");
    盒.className = "h3dyt-提示词";
    const 编辑区 = document.createElement("div");
    编辑区.className = "h3dyt-编辑区";
    编辑区.contentEditable = "true";

    // 工具行：@ 快捷键按钮；后续智能体/规划器/skill 等入口也加在这一行
    const 工具行 = document.createElement("div");
    工具行.className = "h3dyt-工具行";
    const at按钮 = document.createElement("button");
    at按钮.className = "h3dyt-胶囊"; at按钮.type = "button";
    at按钮.textContent = "@"; at按钮.title = "插入参考素材标签";
    at按钮.onclick = () => { 编辑区.focus(); 弹参考列表(at按钮.getBoundingClientRect()); };
    工具行.appendChild(at按钮);

    // @ 按钮后：输出分辨率下拉 + 百万像素数值（与参考节点前端同款，编辑节点同名 widget）
    const 控件样式 = "background:#1c1c1c;color:#ddd;border:1px solid #444;border-radius:3px";
    const 分辨率组 = document.createElement("label");
    分辨率组.style.cssText = "display:flex;align-items:center;gap:4px;margin-left:6px";
    分辨率组.textContent = "输出分辨率";
    const 分辨率sel = document.createElement("select");
    分辨率sel.style.cssText = 控件样式;
    分辨率选项.forEach((名) => {
        const o = document.createElement("option");
        o.value = 名; o.textContent = 名;
        分辨率sel.appendChild(o);
    });
    分辨率sel.onchange = () => 分辨率变更?.(分辨率sel.value);
    分辨率组.appendChild(分辨率sel);

    const 百万像素组 = document.createElement("label");
    百万像素组.style.cssText = "display:flex;align-items:center;gap:4px";
    百万像素组.textContent = "百万像素";
    // 滑块（0.1–4，步 0.1）+ 右侧实时读数；拖动即回写节点 widget
    const 百万像素滑 = document.createElement("input");
    百万像素滑.type = "range";
    百万像素滑.min = "0.1"; 百万像素滑.max = "4"; 百万像素滑.step = "0.1";
    百万像素滑.style.cssText = "width:110px;accent-color:#4a9eff";
    const 百万像素值 = document.createElement("span");
    百万像素值.style.cssText = "min-width:30px;text-align:right;color:#ddd";
    function 刷新百万像素读数() { 百万像素值.textContent = Number(百万像素滑.value).toFixed(1); }
    百万像素滑.oninput = () => { 刷新百万像素读数(); 百万像素变更?.(parseFloat(百万像素滑.value)); };
    百万像素组.append(百万像素滑, 百万像素值);

    工具行.append(分辨率组, 百万像素组);

    // 百万像素右边：画风 + 预设 两个下拉（拼接写回节点「全局提示词」widget，该 widget
    // 在节点上已隐藏）。工具行因此有 5 组控件，窄屏靠 .h3dyt-工具行 的 flex-wrap 换行兜住。
    const 画风预设 = 创建画风预设选择(工具行, { 变更: 全局提示词变更 });

    // 编辑说明行：介绍 @ 用法等编辑方法
    const 说明行 = document.createElement("div");
    说明行.className = "h3dyt-说明行";
    说明行.textContent = "编辑说明：输入 @ 或点上方 @ 按钮弹出参考素材列表，点选插入「图像1/音频1/视频1」标签；回车换行。";

    盒.append(工具行, 编辑区, 说明行);
    容器.appendChild(盒);

    let 弹层 = null;

    function 建chip(标签) {
        const span = document.createElement("span");
        span.className = "h3dyt-chip";
        span.contentEditable = "false";
        span.dataset.tag = 标签;
        span.textContent = 显示名(标签);
        return span;
    }

    function 取纯文本() {
        let out = "";
        const 走 = (节点) => {
            节点.childNodes.forEach((子) => {
                if (子.nodeType === Node.TEXT_NODE) out += 子.textContent;
                else if (子.classList?.contains("h3dyt-chip")) out += 子.dataset.tag || "";
                else if (子.tagName === "BR") out += "\n";
                else if (子.tagName === "DIV" || 子.tagName === "P") {
                    // Chromium contenteditable 回车会插 <div>（Firefox 插 <br>），不补换行则多行合并为一行 →
                    // 写回节点的 prompt 丢行。顶层 编辑区 本身不走此分支（它作 走(编辑区) 入口，不在子循环里）。
                    if (out && !out.endsWith("\n")) out += "\n";
                    走(子);
                }
                else 走(子);
            });
        };
        走(编辑区);
        return out;
    }

    function 设值(文本) {
        编辑区.innerHTML = "";
        const s = 文本 || "";
        let 末 = 0;
        for (const m of s.matchAll(标签re)) {
            if (m.index > 末) 编辑区.appendChild(document.createTextNode(s.slice(末, m.index)));
            编辑区.appendChild(建chip(m[0]));
            末 = m.index + m[0].length;
        }
        if (末 < s.length) 编辑区.appendChild(document.createTextNode(s.slice(末)));
    }

    function 关弹层() { 弹层?.remove(); 弹层 = null; }

    function 弹参考列表(锚rect) {
        关弹层();
        const 素材 = 取参考List_安全();
        弹层 = document.createElement("div");
        弹层.className = "h3dyt-弹层";
        弹层.style.left = (锚rect?.left ?? 100) + "px";
        弹层.style.top = ((锚rect?.bottom ?? 100) + 4) + "px";
        let 有条目 = false;
        for (const 槽 of ["图片", "音频", "视频"]) {
            (素材[槽] || []).forEach((名, i) => {
                有条目 = true;
                const 标签 = `<${槽到标签[槽]} ${i + 1}>`;
                const 项 = document.createElement("div");
                项.textContent = `${显示名(标签)} · ${名}`;
                项.onmousedown = (e) => { e.preventDefault(); 插入chip(标签); 关弹层(); };
                弹层.appendChild(项);
            });
        }
        if (!有条目) {
            const 空 = document.createElement("div");
            空.textContent = "（请先在参考文件区添加素材）";
            空.style.opacity = "0.6";
            弹层.appendChild(空);
        }
        document.body.appendChild(弹层);
    }
    function 取参考List_安全() {
        try { return 取参考列表?.() || { 图片: [], 音频: [], 视频: [] }; }
        catch { return { 图片: [], 音频: [], 视频: [] }; }
    }

    function 插入chip(标签) {
        const sel = window.getSelection();
        if (!sel?.rangeCount) { 编辑区.appendChild(建chip(标签)); 变更?.(取纯文本()); return; }
        const range = sel.getRangeAt(0);
        // 删除触发用的 "@"——必须先捕获 offset！改写 Text.textContent 会按 DOM 规范把以此 Text
        // 为 startContainer 的 Range 边界 offset 重置为 0（Chrome/Firefox 均如此），事后再读
        // range.startOffset 就丢了位置，setStart(节点, -1) 抛 IndexSizeError。
        const 节点 = range.startContainer;
        const 位 = range.startOffset;
        if (节点.nodeType === Node.TEXT_NODE && 位 > 0 &&
            节点.textContent[位 - 1] === "@") {
            节点.textContent = 节点.textContent.slice(0, 位 - 1) + 节点.textContent.slice(位);
            range.setStart(节点, 位 - 1);
            range.collapse(true);
        }
        const chip = 建chip(标签);
        range.insertNode(chip);
        range.setStartAfter(chip); range.collapse(true);
        sel.removeAllRanges(); sel.addRange(range);
        变更?.(取纯文本());
    }

    编辑区.addEventListener("input", () => {
        变更?.(取纯文本());
        const sel = window.getSelection();
        if (!sel?.rangeCount) return;
        const range = sel.getRangeAt(0);
        const 前 = (range.startContainer.textContent || "").slice(0, range.startOffset);
        if (前.endsWith("@")) 弹参考列表(range.getBoundingClientRect());
        else 关弹层();
    });
    编辑区.addEventListener("blur", () => setTimeout(关弹层, 150));
    编辑区.addEventListener("paste", (e) => {
        e.preventDefault();
        const 文本 = (e.clipboardData || window.clipboardData).getData("text");
        document.execCommand("insertText", false, 文本);
    });

    function 设分辨率(v) { 分辨率sel.value = 分辨率选项.includes(v) ? v : 默认分辨率; }
    function 设百万像素(v) {
        const n = parseFloat(v);
        // 钳到滑块范围并对齐 0.1 步长（range 程序赋值不自动 snap），再刷新读数
        const c = Number.isFinite(n) ? Math.round(Math.min(4, Math.max(0.1, n)) * 10) / 10 : 默认百万像素;
        百万像素滑.value = String(c);
        刷新百万像素读数();
    }

    return {
        设值, 取值: 取纯文本, 设分辨率, 设百万像素,
        设全局提示词: (v) => 画风预设.设值(v),
        刷新画风预设: () => 画风预设.刷新选项(),
        刷新弹层: () => { if (弹层) 弹参考列表(弹层.getBoundingClientRect()); },
    };
}
