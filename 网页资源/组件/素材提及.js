// AI规划页「内容」框：contenteditable 编辑器 ＋ @ 提及弹层。
// 打 `@` 弹出规划素材清单，点选/回车 → 插入带背景色的 `@素材名` 引用块（chip），
// 观感与 提示词编辑器.js 的 <Picture N> 引用一致：一眼看得出「这条引用插进去了」。
// 叶子组件（同 媒体预览.js 口径）：零 import、样式自持、不吃上下文；清单由宿主 取素材() 现读，
// 所以在素材墙删掉一张图后，下一次打 @ 的列表就是新的，不需要额外通知。
//
// ⚠️ 为什么插的是 `@素材名` 而不是 <图片 1> 这类尖括号标签：
//   后端 规划/规划器.py 把 详细要求 原样拼进请求（`## 详细要求`），同一条请求里已带
//   `## 可用素材` 的 `- 名称（类型）` 清单，system 还要求 AI「只能逐字引用清单中的名称」，
//   段级 使用素材 最终也要拿同一份名单做白名单过滤。⇒ 前端的职责只有一个：把**逐字同名**的
//   引用写进去。自造标签格式既过不了后端过滤，又会和执行期 <Picture N> 槽位解析混叠。
//
// ⚠️ 为什么这个框从 textarea 换成 contenteditable（用户 2026-09-30）：
//   textarea 是纯文本控件，行内文字拿不到背景色，「插进去没有视觉确认」在 textarea 里无解。
//   代价：框内内容不再是 `.value`，读写一律走本组件的 取文()/设文()（chip ↔ `@素材名` 双向还原），
//   宿主与后端拿到的仍是同一段纯文本，草稿 brief 的结构不变。
const 样式已注入 = { v: false };
function 注入样式() {
    if (样式已注入.v) return;
    const s = document.createElement("style");
    s.textContent = `
      /* 层用块级布局、行自然撑高：原先 flex 列 + 行 overflow:hidden 时，flex 项在主轴的自动最小尺寸
         归 0，行会被竖向压扁 → 文字只剩上半截（用户 2026-09-30 反馈）。 */
      .lvp-提及层{position:fixed;z-index:9999;max-width:min(340px,90vw);max-height:200px;overflow-y:auto;padding:2px;background:var(--comfy-input-bg,#1c1c1c);border:1px solid var(--border-color,#444);border-radius:6px;font:11px/1.5 system-ui}
      .lvp-提及项{padding:2px 8px;border-radius:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--fg-color,#ddd);cursor:pointer}
      .lvp-提及项:hover,.lvp-提及选{background:var(--p-primary-color,#4a9eff);color:var(--p-primary-contrast-color,#fff)}
      .lvp-提及空{padding:2px 8px;color:var(--p-text-muted-color,#9aa0a8)}
      /* 音频的 ♪ 上绿（用户 2026-09-30，与 规划素材区 的角标同色同 token）：只有这个文本字形吃 color，
         图像/视频/文本三类是 emoji，加类也不会变色。色值走 var() 兜底（本文件白名单为空，禁裸 hex）。
         高亮/悬停行整行反白（蓝底），绿字压蓝底对比太差 ⇒ 跟整行一起转白；双类权重(0-2-0)盖过单类(0-1-0)。 */
      .lvp-提及音{color:var(--p-green-400,#7ee0a3)}
      .lvp-提及项:hover .lvp-提及音,.lvp-提及选 .lvp-提及音{color:var(--p-primary-contrast-color,#fff)}
      /* 引用 chip：配色与 编辑页面板.js 的 .lvp-chip 同源（那边是裸 hex 白名单功能色），
         但样式必须自持——页面板互不 import、注入顺序不保证，借规则会在编辑页未创建时变成无底色纯文字。 */
      .lvp-提及chip{display:inline-block;margin:0 2px;padding:0 6px;border-radius:8px;background:var(--lvp-chip-bg,#3a5f8a);color:var(--lvp-chip-fg,#cfe6ff)}`;
    document.head.appendChild(s);
    样式已注入.v = true;
}

const 转义 = (文) => String(文).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// 输入 = contenteditable 元素；{ 取素材, 图标表 } 由宿主注入（取素材() → [{名,类型}]，图标表 = 类型→角标字符）。
// 返回 { 关, 取文, 设文 }：宿主换绑节点/切走时必须调 关()，否则弹层里是上一节点的素材名；
// 取文/设文 取代原来直接读 textarea 的 .value。
export function 挂素材提及(编辑区, { 取素材, 图标表 }) {
    注入样式();
    let 弹层 = null, 项表 = [], 行表 = [], 高亮 = 0;

    function 关() {
        if (!弹层) return;
        弹层.remove();
        弹层 = null; 项表 = []; 行表 = []; 高亮 = 0;
    }

    // ── 纯文本 ↔ 框内 DOM ──
    // chip 是 contenteditable=false 的原子块，取文 时还原成 dataset.tag（`@素材名`）；
    // 回车在 Chromium 里会插 <div>（Firefox 插 <br>），不补换行则多行合并成一行的口径同 提示词编辑器.js。
    function 取文() {
        let 出 = "";
        const 走 = (节) => {
            节.childNodes.forEach((子) => {
                if (子.nodeType === 3) 出 += 子.textContent;
                else if (子.classList?.contains("lvp-提及chip")) 出 += 子.dataset.tag || "";
                else if (子.tagName === "BR") 出 += "\n";
                else if (子.tagName === "DIV" || 子.tagName === "P") {
                    if (出 && !出.endsWith("\n")) 出 += "\n";
                    走(子);
                }
                else 走(子);
            });
        };
        走(编辑区);
        return 出;
    }

    function 建chip(名) {
        const 块 = document.createElement("span");
        块.className = "lvp-提及chip";
        块.contentEditable = "false";
        块.dataset.tag = `@${名}`;
        块.textContent = `@${名}`;   // 显示文本＝写回文本，逐字同名，不做中文改名
        return 块;
    }

    // 只有**当前素材清单里的名字**才 chip 化：素材被删掉后 `@旧名` 退回纯文字，
    // 视觉上和"没被认识的引用"一致，也如实告诉用户这条引用后端拿不到名单。
    function 引用re() {
        const 名单 = (取素材() || []).map((m) => String(m?.名 ?? "")).filter(Boolean)
            .sort((a, b) => b.length - a.length);   // 长名优先，避免 `@图` 抢在 `@图.png` 前吃掉前缀
        return 名单.length ? new RegExp(`@(${名单.map(转义).join("|")})`, "g") : null;
    }

    function 设文(文本) {
        关();
        编辑区.textContent = "";
        const 文 = 文本 || "";
        if (!文) return;
        const re = 引用re();
        let 末 = 0;
        if (re) for (const m of 文.matchAll(re)) {
            if (m.index > 末) 编辑区.appendChild(document.createTextNode(文.slice(末, m.index)));
            编辑区.appendChild(建chip(m[1]));
            末 = m.index + m[0].length;
        }
        if (末 < 文.length) 编辑区.appendChild(document.createTextNode(文.slice(末)));
    }

    // 空框归一：清空后 Chromium 常留一个 <br> 或空文本节点，`:empty` 一破占位文案就回不来了；
    // 摘掉残余后把光标放回框首，免得用户以为还能继续在原处打字。
    function 归一空框() {
        if (取文() || !编辑区.childNodes.length) return;
        编辑区.textContent = "";
        const 域 = document.createRange();
        域.selectNodeContents(编辑区); 域.collapse(true);
        const 选 = window.getSelection();
        选?.removeAllRanges(); 选?.addRange(域);
    }

    // ── 弹层 ──
    // 光标**左侧**文本里以 @ 开头、尚未被空白截断的片段才算提及 token：光标不在 @ 后面（回改正文、
    // 点选中间）不弹，已插好的 chip 后面（尾随空格）也不会回头再弹。
    function 取token() {
        const 选 = window.getSelection?.();
        if (!选 || !选.rangeCount) return null;
        const 域 = 选.getRangeAt(0);
        if (!编辑区.contains(域.startContainer) || !编辑区.contains(域.endContainer)) return null;
        const 前 = document.createRange();
        前.selectNodeContents(编辑区);
        前.setEnd(域.endContainer, 域.endOffset);
        const m = /@([^\s@]*)$/.exec(前.toString());
        return m ? { 关键词: m[1], 域 } : null;
    }

    function 同步() {
        const token = 取token();
        if (!token) { 关(); return; }
        const 全 = 取素材() || [];
        const 键 = token.关键词.toLowerCase();
        项表 = 全.filter((m) => !键 || String(m.名 ?? "").toLowerCase().includes(键));
        if (!弹层) {
            弹层 = document.createElement("div");
            弹层.className = "lvp-提及层";
            弹层.style.visibility = "hidden";   // 量完尺寸定好位再显形，免得在错误位置闪一下
            document.body.appendChild(弹层);
        }
        填(全.length, token.关键词);
        定位(token.域.getBoundingClientRect());
    }

    function 填(素材数, 关键词) {
        高亮 = 0; 行表 = [];
        弹层.textContent = "";
        const 空行 = (文) => {
            const 行 = document.createElement("div");
            行.className = "lvp-提及空";
            行.textContent = 文;
            弹层.appendChild(行);
        };
        // 两种空态要分开说：没上传素材＝去左侧上传；有素材但没匹配上＝改关键词。
        // 尤其输入法组词途中会临时匹配不到，写「请先上传」是把人往错的方向赶。
        if (!素材数) { 空行("还没有规划素材，先在左侧「规划素材」上传"); return; }
        if (!项表.length) { 空行(`无匹配「${关键词}」的素材`); return; }
        项表.forEach((m, i) => {
            const 行 = document.createElement("div");
            行.className = "lvp-提及项";
            // 图标自成 span：只有音频的 ♪ 是文本字形、吃 CSS color，绿色只给它（其余三类是 emoji，加了也不变）。
            const 符 = document.createElement("span");
            符.textContent = 图标表[m.类型] || "";
            if (m.类型 === "音频") 符.classList.add("lvp-提及音");
            行.append(符, document.createTextNode(` ${m.名}（${m.类型}）`));
            行.title = `插入 @${m.名}`;
            // 拦默认行为才不夺走编辑区焦点：焦点一丢，光标位置就没了，插入位置也就没了。
            行.onmousedown = (e) => { e.preventDefault(); 插入(m.名); };
            if (i === 0) 行.classList.add("lvp-提及选");
            行表.push(行);
            弹层.appendChild(行);
        });
    }

    // 默认**向上展开**（用户 2026-09-30）：内容框占右列整块，光标多半落在下半屏，往下弹容易顶出视口。
    // 上方放不下而下方更宽裕时退回下方，两侧都紧则把 max-height 收到可用高度，让层自带的
    // overflow-y 接管滚动（flip + size，同 提示词编辑器.js 的 定位弹层 口径）。
    function 定位(锚) {
        const 框 = 编辑区.getBoundingClientRect();
        if (!框.width) { 关(); return; }   // 面板未布局/被隐藏（切 Tab）时一切几何都是 0，别把弹层甩到左上角
        // 光标落在空行时 Chromium 可能返回全 0 的 collapsed rect；退用框首行，层仍旧开在框上方而不是漂走。
        if (!锚.height && !锚.width) 锚 = { left: 框.left + 3, top: 框.top, bottom: 框.top };
        const 边距 = 8, 间隙 = 4;
        const 视高 = window.innerHeight, 视宽 = window.innerWidth;
        const 高 = 弹层.offsetHeight, 宽 = 弹层.offsetWidth;
        const 上空间 = 锚.top - 边距 - 间隙, 下空间 = 视高 - 锚.bottom - 边距 - 间隙;
        let top, 可用高;
        if (上空间 >= 高 || 上空间 >= 下空间) { 可用高 = 上空间; top = 锚.top - 间隙 - Math.min(高, 可用高); }
        else { 可用高 = 下空间; top = 锚.bottom + 间隙; }
        if (高 > 可用高) 弹层.style.maxHeight = Math.max(60, 可用高) + "px";
        let left = 锚.left;
        if (left + 宽 > 视宽 - 边距) left = Math.max(边距, 视宽 - 边距 - 宽);
        弹层.style.left = left + "px";
        弹层.style.top = Math.max(边距, top) + "px";
        弹层.style.visibility = "";
    }

    function 移高亮(步) {
        高亮 = (高亮 + 步 + 行表.length) % 行表.length;   // 首尾循环，长清单不用一直按到底
        行表.forEach((行, i) => 行.classList.toggle("lvp-提及选", i === 高亮));
        行表[高亮].scrollIntoView({ block: "nearest" });  // 收到 maxHeight 的层里，键盘选中项要跟着露出来
    }

    // 把光标前的 `@关键词` 换成 chip ＋ 一个尾随空格。空格＝下一次 input 的 token 正则不再命中，
    // 弹层不会插完立刻自己重开；chip 是原子块，退格一次整块删掉，不会留下半截 `@`。
    // 注：DOM 插入不经 execCommand，因此不保证进浏览器原生撤销栈（同 提示词编辑器.js 的 chip 插入），
    // 误选的引用直接退格删块即可。
    function 插入(名) {
        const token = 取token();
        关();
        if (!token) return;
        编辑区.focus();
        const 选 = window.getSelection();
        if (!选 || !选.rangeCount) return;
        const 域 = 选.getRangeAt(0);
        const 节 = 域.startContainer;
        if (节.nodeType !== 3) return;   // 光标紧贴 chip/换行元素：文本节点之外没有可替换的 `@关键词`
        const 止 = 域.startOffset;
        const m = /@[^\s@]*$/.exec(节.textContent.slice(0, 止));
        if (!m) return;
        const 插 = document.createRange();
        插.setStart(节, 止 - m[0].length);
        插.setEnd(节, 止);
        插.deleteContents();
        const chip = 建chip(名);
        插.insertNode(chip);
        const 尾 = document.createTextNode(" ");
        const 补 = document.createRange();
        补.setStartAfter(chip); 补.collapse(true);
        补.insertNode(尾);
        域.setStartAfter(尾); 域.collapse(true);
        选.removeAllRanges(); 选.addRange(域);
        编辑区.dispatchEvent(new Event("input", { bubbles: true }));
    }

    编辑区.addEventListener("input", () => { 归一空框(); 同步(); });
    编辑区.addEventListener("scroll", 关);   // 滚动会让光标像素位漂移，直接收层（同 提示词编辑器.js 口径）
    编辑区.addEventListener("blur", 关);     // 焦点离开即收；点条目走 mousedown+preventDefault，不会触发 blur
    编辑区.addEventListener("paste", (e) => {
        e.preventDefault();   // 富文本粘贴会把 Word/网页的 HTML 灌进 contenteditable，取文 只能按纯文本还原
        const 文 = (e.clipboardData || window.clipboardData).getData("text");
        document.execCommand("insertText", false, 文);
    });
    编辑区.addEventListener("keydown", (e) => {
        // 输入法组词期间一律放行：那时 Enter 是「确认候选词」、↑↓ 是「翻候选页」，
        // 被劫持就打不出中文（踩坑手册 §N 同类）。代价：候选框占用 ↑↓ 时弹层只能用鼠标点。
        if (e.isComposing) return;
        if (!弹层) return;
        if (e.key === "Escape") { e.preventDefault(); 关(); return; }
        if (!行表.length) return;   // 空态（没素材/没匹配）：↑↓ Enter 全数放行，正文该换行还换行
        if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); 移高亮(e.key === "ArrowDown" ? 1 : -1); }
        else if (e.key === "Enter") {
            const m = 项表[高亮];
            if (!m) return;
            e.preventDefault();   // 弹层开着时 Enter＝选中，不再换行
            插入(m.名);
        }
    });

    return { 关, 取文, 设文 };
}
