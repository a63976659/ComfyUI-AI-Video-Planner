// 节点内多段时间轴（DOM 富 widget）：分段运行轨道 + 标尺 + 工具条。
// 真源仍是 node.widgets（时间轴数据/参考素材/运行选择 三个 JSON widget 被幽灵化隐藏），
// 本文件只负责「把 widget 里的段画得像个剪辑轨道」——所有读写都经 桥接/节点桥.js 的 真源。
import { 真源, 取widget } from "./桥接/节点桥.js";
import { 任务码 } from "./生成类型选择.js";

const 面板高 = 240;   // 时间轴最小高（弹性布局下限 --comfy-widget-min-height）；节点拉高时自动增大填满
const 节点默认宽 = 420;   // 画布节点最小默认宽，避免 widget 拥挤
const 节点默认高 = 600;   // 画布节点最小默认高
const 幽灵widget = ["时间轴数据", "参考素材", "运行选择"];
const 吸附步 = 0.5;   // 秒，时长编辑吸附网格
// 段卡与标尺格必须同参（min-width/flex/gap 一致），两行才能逐列对齐（改一个必须同步改另一个）。
// min-width:0 + flex:0 0 0 + flexGrow(时长)：N 段按时长比例正好铺满容器宽 → 永不横向溢出、无横向滚动条；
// 卡片变窄时靠容器查询分级隐藏次要元素/控件（见下），保证「始终看得到全部分段」。
const 列间隙 = 4;

// 段色循环（琥珀/天蓝/翠绿/品红）：给每段一个稳定的视觉身份，只用于卡片顶条与「段N」徽标，
// 与「选中＝翠绿描边」分工不同（选中态另叠加外发光，见 .h3dyt-tl-卡.选中）。
const 段色 = ["#ffc850", "#66aaff", "#4fff8f", "#ff7ab8"];

const 样式已注入 = { v: false };
function 注入样式() {
    if (样式已注入.v) return;
    const s = document.createElement("style");
    // 时间轴挂在节点上，可能在状态栏面板（另一处样式注入）之前渲染，故自带独立样式块，
    // 不复用 .h3dyt-胶囊 等状态栏类名。
    s.textContent = `
      .h3dyt-时间轴{--tl-bg:#17181a;--tl-card:#202226;--tl-line:#2e3136;--tl-line2:#4b515a;
        --tl-txt:#e8eaed;--tl-mut:#9aa0a8;--tl-dim:#6d737b;--tl-acc:#4fff8f;--tl-danger:#ff6b6b;
        height:100%;--comfy-widget-min-height:${面板高}px;
        display:flex;flex-direction:column;gap:6px;padding:8px;box-sizing:border-box;overflow:hidden;
        background:linear-gradient(180deg,#1c1e22,#151619);border:1px solid var(--tl-line);border-radius:8px;
        font:11px ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--tl-txt)}
      .h3dyt-时间轴 *{box-sizing:border-box}

      /* ── 工具条 ───────────────────────────────────────── */
      .h3dyt-tl-工具{display:flex;align-items:center;gap:6px;flex:0 0 auto;flex-wrap:wrap}
      .h3dyt-tl-钮{display:inline-flex;align-items:center;gap:4px;padding:4px 9px;border-radius:6px;
        border:1px solid var(--tl-line2);background:linear-gradient(180deg,#2c2f35,#23262b);
        color:var(--tl-txt);font:inherit;cursor:pointer;white-space:nowrap;
        transition:background .12s,border-color .12s,box-shadow .12s,transform .06s}
      .h3dyt-tl-钮:hover{background:linear-gradient(180deg,#363a42,#292d33);border-color:#5d646f}
      .h3dyt-tl-钮:active{transform:translateY(1px)}
      .h3dyt-tl-钮:disabled{opacity:.38;cursor:not-allowed;transform:none}
      .h3dyt-tl-钮.主{border-color:rgba(79,255,143,.42);color:#d8ffe8;
        background:linear-gradient(180deg,#22442f,#1a3325)}
      .h3dyt-tl-钮.主:hover:not(:disabled){border-color:var(--tl-acc);box-shadow:0 0 0 1px rgba(79,255,143,.18)}
      .h3dyt-tl-钮.危:hover:not(:disabled){border-color:var(--tl-danger);color:#ffdada;
        background:linear-gradient(180deg,#3b2426,#2c1c1e)}
      .h3dyt-tl-概要{margin-left:auto;color:var(--tl-mut);white-space:nowrap;font-variant-numeric:tabular-nums}

      /* ── 轨道区（标尺 + 轨道同参逐列对齐；宽度自适应铺满，无横向滚动） ── */
      /* 卷本身是 flex 列：空态的 flex:1 才撑得满（否则 0 段时下面留一块死黑） */
      .h3dyt-tl-卷{flex:1 1 auto;min-height:0;overflow-x:hidden;overflow-y:auto;display:flex;flex-direction:column}
      .h3dyt-tl-卷>.h3dyt-tl-空态{flex:1 1 auto}
      .h3dyt-tl-卷::-webkit-scrollbar{width:8px;height:8px}
      .h3dyt-tl-卷::-webkit-scrollbar-thumb{background:#343a42;border-radius:4px}
      .h3dyt-tl-卷::-webkit-scrollbar-thumb:hover{background:#464d57}
      .h3dyt-tl-卷::-webkit-scrollbar-track{background:transparent}
      .h3dyt-tl-内{display:flex;flex-direction:column;gap:3px;min-width:100%;min-height:100%}

      /* flex-basis 必须为 0：否则基数取内容宽，flexGrow 只是「在内容宽之上再加权」，
         时长比例就失真了（5s 段和 10s 段看着一样宽）。标尺与轨道两行必须同参。 */
      .h3dyt-tl-标尺{display:flex;flex:0 0 auto;height:13px;align-items:flex-end}
      .h3dyt-tl-刻度{position:relative;min-width:0;flex:0 0 0;padding-left:6px;
        color:var(--tl-dim);font-size:10px;line-height:1;font-variant-numeric:tabular-nums}
      .h3dyt-tl-刻度::before{content:"";position:absolute;left:0;bottom:-3px;width:1px;height:6px;
        background:var(--tl-line2)}

      .h3dyt-tl-轨道{display:flex;align-items:stretch;flex:1 1 auto;min-height:148px;padding-bottom:3px}

      /* ── 段卡 ─────────────────────────────────────────── */
      .h3dyt-tl-卡{position:relative;display:flex;flex-direction:column;gap:5px;flex:0 0 0;
        min-width:0;padding-bottom:6px;overflow:hidden;cursor:pointer;
        container-type:inline-size;
        background:linear-gradient(180deg,var(--tl-card),#1b1d21);
        border:1px solid var(--tl-line);border-radius:7px;
        transition:border-color .12s,box-shadow .12s,transform .08s,opacity .14s,filter .14s}
      .h3dyt-tl-卡:hover{border-color:var(--tl-line2);transform:translateY(-1px);
        box-shadow:0 4px 14px rgba(0,0,0,.38)}
      .h3dyt-tl-卡.选中{border-color:var(--tl-acc);
        box-shadow:0 0 0 1px rgba(79,255,143,.26),0 6px 18px rgba(0,0,0,.46)}
      .h3dyt-tl-卡.停{opacity:.4;filter:saturate(.3)}
      .h3dyt-tl-卡.停:hover{opacity:.78;filter:saturate(.6)}
      .h3dyt-tl-顶条{height:3px;flex:0 0 auto;background:var(--seg);opacity:.9}

      .h3dyt-tl-头{display:flex;align-items:center;gap:5px;padding:0 6px;flex:0 0 auto}
      .h3dyt-tl-序号{flex:0 0 auto;height:16px;min-width:17px;padding:0 4px;border-radius:4px;
        display:inline-flex;align-items:center;justify-content:center;
        background:var(--segsoft);color:var(--seg);font-size:10px;font-weight:700}
      .h3dyt-tl-任务{flex:0 0 auto;padding:1px 5px;border-radius:8px;background:#2b2f36;
        color:var(--tl-mut);font-size:10px;letter-spacing:.02em}
      .h3dyt-tl-区间{margin-left:auto;color:var(--tl-dim);font-size:10px;white-space:nowrap;
        font-variant-numeric:tabular-nums}

      /* 首帧图随卡片高度伸缩（flex:1，下限 44px）：节点拉高→卡片变高→缩略图放大铺满，
         避免多余高度堆在提示词区留白（词固定 2 行）；img object-fit:cover 裁切填充。 */
      .h3dyt-tl-图{position:relative;flex:1 1 44px;min-height:44px;margin:0 6px;border-radius:5px;
        overflow:hidden;background:#101114}
      .h3dyt-tl-图 img{width:100%;height:100%;object-fit:cover;display:block}
      .h3dyt-tl-图::after{content:"";position:absolute;inset:0;pointer-events:none;
        background:linear-gradient(180deg,rgba(0,0,0,0) 48%,rgba(0,0,0,.5))}
      .h3dyt-tl-图空{height:100%;display:flex;align-items:center;justify-content:center;
        color:#4e555d;font-size:10px;
        background:repeating-linear-gradient(135deg,#17191c,#17191c 6px,#1c1f23 6px,#1c1f23 12px)}

      .h3dyt-tl-词{flex:0 0 auto;margin:0 6px;color:var(--tl-mut);font-size:10px;
        line-height:1.45;word-break:break-word;overflow:hidden;
        display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
      .h3dyt-tl-词.空{color:#565c64;font-style:italic}

      .h3dyt-tl-脚{display:flex;align-items:center;gap:6px;margin:0 6px;flex:0 0 auto}
      .h3dyt-tl-时长{display:flex;align-items:center;flex:0 0 auto;overflow:hidden;
        border:1px solid var(--tl-line);border-radius:5px;background:#141619}
      .h3dyt-tl-时长 button{width:16px;height:20px;padding:0;border:none;background:transparent;
        color:var(--tl-mut);font:inherit;font-size:12px;line-height:1;cursor:pointer}
      .h3dyt-tl-时长 button:hover{background:#272b31;color:var(--tl-txt)}
      .h3dyt-tl-时长 input{width:30px;height:20px;padding:0;text-align:center;background:transparent;
        border:none;border-left:1px solid var(--tl-line);border-right:1px solid var(--tl-line);
        color:var(--tl-txt);font:inherit;font-size:10px;font-variant-numeric:tabular-nums;
        appearance:textfield;-moz-appearance:textfield}
      .h3dyt-tl-时长 input::-webkit-outer-spin-button,
      .h3dyt-tl-时长 input::-webkit-inner-spin-button{-webkit-appearance:none;margin:0}
      .h3dyt-tl-时长 input:focus{outline:none;background:#1e2228}

      .h3dyt-tl-跑{position:relative;margin-left:auto;display:inline-flex;align-items:center;gap:4px;
        color:var(--tl-dim);font-size:10px;cursor:pointer;user-select:none;flex:0 0 auto}
      .h3dyt-tl-跑字{white-space:nowrap}
      /* 窄卡只留开关（颜色已表意），宽卡才补「运行」二字，避免文字被挤成竖排 */
      @container (max-width:131px){.h3dyt-tl-跑字{display:none}}
      /* 卡片随段数增多而变窄时分级降级，保证「全部分段始终可见、内容不被裁切」：
         ≤118px 收区间+时长步进器（脚只留运行开关）→ ≤76px 收任务标签 → ≤56px 收提示词 → ≤38px 收运行开关。
         要精调某段时长/运行，把节点拉宽即可（widget 宽随节点宽 → 卡片变宽 → 控件复现）。 */
      @container (max-width:118px){.h3dyt-tl-区间,.h3dyt-tl-时长{display:none}}
      @container (max-width:76px){.h3dyt-tl-任务{display:none}}
      @container (max-width:56px){.h3dyt-tl-词{display:none}}
      @container (max-width:38px){.h3dyt-tl-脚{display:none}}
      .h3dyt-tl-跑 input{position:absolute;opacity:0;width:0;height:0;margin:0}
      .h3dyt-tl-滑{position:relative;flex:0 0 auto;width:22px;height:12px;border-radius:6px;
        background:#343a42;transition:background .14s}
      .h3dyt-tl-滑::after{content:"";position:absolute;top:2px;left:2px;width:8px;height:8px;
        border-radius:50%;background:#8b929b;transition:transform .14s,background .14s}
      .h3dyt-tl-跑 input:checked+.h3dyt-tl-滑{background:rgba(79,255,143,.26)}
      .h3dyt-tl-跑 input:checked+.h3dyt-tl-滑::after{transform:translateX(10px);background:var(--tl-acc)}
      .h3dyt-tl-跑 input:checked~.h3dyt-tl-跑字{color:var(--tl-acc)}
      .h3dyt-tl-跑 input:focus-visible+.h3dyt-tl-滑{box-shadow:0 0 0 2px rgba(79,255,143,.34)}

      /* ── 空态 ─────────────────────────────────────────── */
      .h3dyt-tl-空态{flex:1 1 auto;display:flex;flex-direction:column;align-items:center;
        justify-content:center;gap:9px;border:1px dashed var(--tl-line2);border-radius:7px;
        color:var(--tl-dim);background:rgba(255,255,255,.014);text-align:center;padding:10px}
      .h3dyt-tl-空态 b{color:var(--tl-mut);font-weight:600}`;
    document.head.appendChild(s);
    样式已注入.v = true;
}

function 幽灵化(w) {
    if (!w) return;
    w.type = "hidden";
    // 关键：1.51.x 的 Vue 版 DOM widget 只认 hidden 属性来决定是否渲染 .dom-widget 覆盖层。
    // 缺了它，multiline 的 .dom-widget>textarea 会残留（display:block+pointer-events:auto）
    // 叠在画布上拦截后续 widget（步数等）的点击；type="hidden" 与下面的 DOM 引用都指不到它。
    w.hidden = true;
    w.computeSize = () => [0, -4];
    w.draw = () => {};
    // 新版前端 multiline 可能以 DOM 元素渲染，仅 canvas 三层幽灵化遮不住：会残留原始 JSON
    // 文本框（如 运行选择 的 "{}"）并遮挡后续 widget（帧率/…）→ 同步隐藏 DOM 层。
    if (typeof w.hide === "function") { try { w.hide(); } catch { /* 忽略 */ } }
    for (const el of [w.element, w.inputEl, w.el]) {
        if (el && el.style) el.style.display = "none";
    }
}

const 秒数 = (s) => Math.max(0.1, (s?.end || 0) - (s?.start || 0));
const 一位 = (n) => (Number.isFinite(n) ? n.toFixed(1) : "0.0");

export function 挂载时间轴(node, 面板) {
    注入样式();
    幽灵widget.forEach((名) => 幽灵化(取widget(node, 名)));

    const 根 = document.createElement("div");
    根.className = "h3dyt-时间轴";
    // 高度不再内联固定：改由 .h3dyt-时间轴{height:100%} 填满 DOM widget 包裹层，包裹层高＝widget 的
    // computedHeight＝框架弹性布局分给本 widget 的剩余节点高（拉高节点→时间轴跟着变高）。
    // 其余样式全在 .h3dyt-时间轴 里：内联样式写不了 :hover/伪元素/过渡，是旧版「像调试线框」的主因。

    const widget = node.addDOMWidget("时间轴", "dom", 根, { getValue: () => "", setValue: () => {}, getMinHeight: () => 面板高 });
    // 故意不设 widget.computeSize：布局引擎把「有 computeSize」的 widget 当固定高，只有「仅有
    // computeLayoutSize」的才弹性。DOMWidgetImpl 自带 computeLayoutSize（读 --comfy-widget-min-height
    // 作下限），于是时间轴成为节点内唯一弹性 widget——节点被拉高时剩余空间全归它，拉多高填多高。
    // 强制最小默认宽高：computeSize 自动值偏小会让 widget 拥挤，取下界兑底
    const [算宽, 算高] = node.computeSize();
    node.setSize([Math.max(算宽, 节点默认宽), Math.max(算高, 节点默认高)]);
    node.setDirtyCanvas?.(true, true);   // 幽灵化+DOM 隐藏后强制重排，消除遮挡

    function 读段() { return (真源.读时间轴(node).segments) || []; }
    // 落盘＝只写 widget + 通知状态栏回填；写段＝落盘后整树重建（结构性增删才需要）。
    function 落盘(段组) { 真源.写时间轴(node, { segments: 段组 }); 面板?.回填?.(); }
    function 写段(段组) { 落盘(段组); 渲染(); }

    function 选中() { return 面板?.状态?.取?.("选中段") ?? 0; }
    function 设选中(i) { 面板?.状态?.设?.("选中段", i); }

    // 卡片/刻度引用：局部刷新（选中态、比例、概要）只动这些节点，不重建整树——
    // 重建会打断 CSS 过渡并让时长输入框失焦，点一下 ± 就闪一次。
    let 卡片组 = [];
    let 刻度组 = [];
    let 概要 = null;

    function 刷态() {
        const 段组 = 读段();
        const 选 = 选中();
        卡片组.forEach((卡, i) => {
            卡.classList.toggle("选中", i === 选);
            卡.classList.toggle("停", !段组[i]?.run);
        });
    }

    function 刷比例() {
        const 段组 = 读段();
        卡片组.forEach((卡, i) => { 卡.style.flexGrow = String(秒数(段组[i])); });
        刻度组.forEach((格, i) => { 格.style.flexGrow = String(秒数(段组[i])); });
    }

    function 刷概要() {
        if (!概要) return;
        const 段组 = 读段();
        const 跑 = 段组.filter((s) => s.run).length;
        const 总 = 段组.reduce((a, s) => a + 秒数(s), 0);
        概要.textContent = 段组.length
            ? `共 ${段组.length} 段 · 运行 ${跑} · ${一位(总)}s`
            : "";
    }

    function 刷区间(卡, s) {
        const 元 = 卡.querySelector(".h3dyt-tl-区间");
        if (元) 元.textContent = `${一位(s?.start || 0)}–${一位(s?.end || 0)}s`;
    }

    // 状态栏编辑提示词/首帧后，就地刷新对应段卡的「图/词」（不整树重建，保住过渡与焦点）。
    // 卡片还没建（如状态栏在空段组里新建了段）→ 回退整树重建，让新段现身。
    function 刷卡(i) {
        const 卡 = 卡片组[i];
        if (!卡) { 渲染(); return; }
        const s = 读段()[i];
        if (!s) return;
        const 图 = 卡.querySelector(".h3dyt-tl-图");
        if (图) 填图(图, s);
        const 词 = 卡.querySelector(".h3dyt-tl-词");
        if (词) 填词(词, s);
    }

    function 建钮(文本, 类名, 提示, fn) {
        const b = document.createElement("button");
        b.className = "h3dyt-tl-钮" + (类名 ? " " + 类名 : "");
        b.type = "button"; b.textContent = 文本; b.title = 提示; b.onclick = fn;
        return b;
    }

    function 建卡(s, i) {
        const 卡 = document.createElement("div");
        卡.className = "h3dyt-tl-卡";
        const 色 = 段色[i % 段色.length];
        卡.style.setProperty("--seg", 色);
        卡.style.setProperty("--segsoft", 色 + "24");   // 8 位 hex：14% 不透明度
        卡.title = `段${i} · ${(s.task || "t2v")} · ${一位(s.start || 0)}–${一位(s.end || 0)}s`;
        卡.onclick = () => { 设选中(i); 刷态(); };

        const 顶 = document.createElement("div");
        顶.className = "h3dyt-tl-顶条";
        卡.appendChild(顶);

        // 头：段号徽标 + 任务码 + 起止区间
        const 头 = document.createElement("div");
        头.className = "h3dyt-tl-头";
        const 序 = document.createElement("span");
        序.className = "h3dyt-tl-序号"; 序.textContent = String(i);
        const 任 = document.createElement("span");
        任.className = "h3dyt-tl-任务"; 任.textContent = s.task || "t2v";
        const 区 = document.createElement("span");
        区.className = "h3dyt-tl-区间";
        头.append(序, 任, 区);
        卡.appendChild(头);
        刷区间(卡, s);

        // 缩略图：绑了首帧/图片才出图，否则给斜纹占位（避免高度跳动）
        const 图 = document.createElement("div");
        图.className = "h3dyt-tl-图";
        填图(图, s);
        卡.appendChild(图);

        // 提示词预览（两行截断）：轨道上一眼能认出哪段是哪段，不必逐段点开状态栏
        const 词 = document.createElement("div");
        填词(词, s);
        卡.appendChild(词);

        // 脚：时长步进器 + 运行开关
        const 脚 = document.createElement("div");
        脚.className = "h3dyt-tl-脚";
        脚.append(建时长(s, i), 建运行(s, i));
        卡.appendChild(脚);

        return 卡;
    }

    function 建图空() {
        const 空 = document.createElement("div");
        空.className = "h3dyt-tl-图空";
        空.textContent = "无首帧";
        return 空;
    }

    // 段卡「图/词」填充：建卡（整树重建）与 刷卡（局部刷新）共用，避免两处逻辑漂移。
    const 图名Of = (s) => s?.refs?.首帧 || s?.refs?.图片?.[0] || "";

    function 填图(图, s) {
        const 图名 = 图名Of(s);
        // 图名未变且已有内容 → 不重建 <img>，避免只改提示词时缩略图重载闪烁
        if (图.dataset.名 === 图名 && 图.firstChild) return;
        图.dataset.名 = 图名;
        图.replaceChildren();
        if (图名) {
            const img = document.createElement("img");
            img.src = "/h3dyt/media/file?name=" + encodeURIComponent(图名);
            img.alt = 图名;
            img.loading = "lazy";
            img.draggable = false;
            // 图挂了（媒体被删/改名）退回占位，不留浏览器裂图图标；
            // 判 firstChild===img：刷卡换新图后，旧 img 迟到的 onerror 不得覆盖新图
            img.onerror = () => { if (图.firstChild === img) 图.replaceChildren(建图空()); };
            图.appendChild(img);
        } else {
            图.appendChild(建图空());
        }
    }

    function 填词(词, s) {
        const 文 = (s?.prompt || "").trim();
        词.className = "h3dyt-tl-词" + (文 ? "" : " 空");
        词.textContent = 文 || "（未填提示词）";
    }

    // 改时长后不整树重建：就地改 end + 刷比例/区间/概要（保住输入框焦点与 hover 态）。
    function 改时长(i, 新秒) {
        const 段组 = 读段();
        const s = 段组[i];
        if (!s) return;
        s.end = s.start + 新秒;
        落盘(段组);
        刷比例(); 刷概要();
        const 卡 = 卡片组[i];
        if (卡) {
            刷区间(卡, s);
            卡.title = `段${i} · ${(s.task || "t2v")} · ${一位(s.start || 0)}–${一位(s.end || 0)}s`;
        }
    }

    function 建时长(s, i) {
        const 盒 = document.createElement("div");
        盒.className = "h3dyt-tl-时长";
        盒.title = `时长（秒，${吸附步}s 吸附）`;
        const 减 = document.createElement("button");
        减.type = "button"; 减.textContent = "−"; 减.title = "减少 " + 吸附步 + "s";
        const 输 = document.createElement("input");
        输.type = "number"; 输.step = String(吸附步); 输.min = String(吸附步);
        const 加 = document.createElement("button");
        加.type = "button"; 加.textContent = "＋"; 加.title = "增加 " + 吸附步 + "s";

        function 回显() { 输.value = String(Math.round(秒数(读段()[i]) / 吸附步) * 吸附步); }
        function 提交(原始) {
            // spec 层隐藏 bug：`parseFloat(输.value || 吸附步)` 只兜空串，"abc"/undef 会产 NaN；
            // NaN 经 `段.end = start + NaN` → `JSON.stringify` 默默转 `null` 落 widget，
            // 直接损坏后端 `SegmentPlan.end (float)` 契约。非法输入直接丢弃、回显原值。
            if (!Number.isFinite(原始)) { 回显(); return; }
            改时长(i, Math.max(吸附步, Math.round(原始 / 吸附步) * 吸附步));
            回显();   // ± 与手输都回显吸附后的真值，输入框读数不与 widget 不一致
        }
        // 步进按钮/输入框都不该冒泡成「选中本段」以外的行为，但要停掉卡片 onclick 抢焦点
        for (const el of [减, 输, 加]) el.onclick = (e) => e.stopPropagation();
        减.onclick = (e) => { e.stopPropagation(); 提交(秒数(读段()[i]) - 吸附步); };
        加.onclick = (e) => { e.stopPropagation(); 提交(秒数(读段()[i]) + 吸附步); };
        输.onchange = () => 提交(parseFloat(输.value));
        回显();
        盒.append(减, 输, 加);
        return 盒;
    }

    function 建运行(s, i) {
        const 标 = document.createElement("label");
        标.className = "h3dyt-tl-跑";
        标.title = "本段是否参与生成（写入 运行选择/段.run）";
        标.onclick = (e) => e.stopPropagation();
        const cb = document.createElement("input");
        cb.type = "checkbox"; cb.checked = !!s.run;
        cb.onchange = () => {
            const 段组 = 读段();
            if (!段组[i]) return;
            段组[i].run = cb.checked;
            落盘(段组);
            刷态(); 刷概要();   // 不重建：开关动画与卡片过渡才不会被截断
        };
        const 滑 = document.createElement("span");
        滑.className = "h3dyt-tl-滑";
        const 字 = document.createElement("span");
        字.className = "h3dyt-tl-跑字"; 字.textContent = "运行";
        标.append(cb, 滑, 字);
        return 标;
    }

    function 渲染() {
        const 段组 = 读段();
        卡片组 = []; 刻度组 = []; 概要 = null;
        根.replaceChildren();

        // 工具条：主操作（新增）绿、破坏性操作（删除）红悬停，右侧实时概要
        const 工具 = document.createElement("div");
        工具.className = "h3dyt-tl-工具";
        const 有段 = 段组.length > 0;
        // 工具条 onclick 一律现读 读段()：状态栏编辑提示词/首帧只写 widget + 刷卡局部刷新，
        // 不触发 渲染()；若此处沿用渲染时的 段组 快照，写回就会覆盖掉状态栏刚输入的内容（新增段清空 bug）。
        const 新增 = 建钮("＋新增段", "主", "在末尾追加 5s 段", () => {
            const 段组 = 读段();
            const 末 = 段组.length ? 段组[段组.length - 1].end : 0;
            const 当前任务 = 任务码(真源.读任务类型(node));
            段组.push({ task: 当前任务, prompt: "", start: 末, end: 末 + 5, run: true });
            写段(段组); 设选中(段组.length - 1);
        });
        const 删除 = 建钮("🗑删除段", "危", "删除选中段", () => {
            const 段组 = 读段();
            const i = 选中(); 段组.splice(i, 1); 写段(段组); 设选中(Math.max(0, i - 1));
        });
        const 裁剪 = 建钮("✂裁剪", "", "把选中段从中点一分为二", () => {
            const 段组 = 读段();
            const i = 选中(); const s = 段组[i]; if (!s) return;
            const 中 = s.start + (s.end - s.start) / 2;
            段组.splice(i + 1, 0, { ...s, start: 中 });
            段组[i] = { ...s, end: 中 };
            写段(段组);
        });
        const 全选 = 建钮("全选运行", "", "所有段都参与生成", () => { const 段组 = 读段(); 段组.forEach((s) => (s.run = true)); 写段(段组); });
        const 全不选 = 建钮("全不选", "", "所有段都不参与生成", () => { const 段组 = 读段(); 段组.forEach((s) => (s.run = false)); 写段(段组); });
        删除.disabled = 裁剪.disabled = !有段;
        全选.disabled = 全不选.disabled = !有段;
        概要 = document.createElement("span");
        概要.className = "h3dyt-tl-概要";
        工具.append(新增, 删除, 裁剪, 全选, 全不选, 概要);
        根.appendChild(工具);

        const 卷 = document.createElement("div");
        卷.className = "h3dyt-tl-卷";
        根.appendChild(卷);

        if (!有段) {
            const 空 = document.createElement("div");
            空.className = "h3dyt-tl-空态";
            const 标 = document.createElement("b");
            标.textContent = "还没有分段";
            const 提 = document.createElement("div");
            提.textContent = "点「＋新增段」建第一段；每段独立填提示词、绑首帧、单独开关运行。";
            const 大 = 建钮("＋新增段", "主", "新建第一段", 新增.onclick);
            空.append(标, 提, 大);
            卷.appendChild(空);
            刷概要();
            return;
        }

        // 标尺与轨道同参（列间隙 + flex:0 0 0 + flexGrow 时长）→ 两行逐列对齐；宽度自适应铺满，无横向滚动。
        const 内 = document.createElement("div");
        内.className = "h3dyt-tl-内";
        const 标尺 = document.createElement("div");
        标尺.className = "h3dyt-tl-标尺";
        const 轨 = document.createElement("div");
        轨.className = "h3dyt-tl-轨道";
        轨.style.gap = 标尺.style.gap = `${列间隙}px`;

        段组.forEach((s, i) => {
            const 格 = document.createElement("div");
            格.className = "h3dyt-tl-刻度";
            格.textContent = `${一位(s.start || 0)}s`;
            标尺.appendChild(格);
            刻度组.push(格);

            const 卡 = 建卡(s, i);
            轨.appendChild(卡);
            卡片组.push(卡);
        });
        内.append(标尺, 轨);
        卷.appendChild(内);

        刷比例(); 刷概要(); 刷态();
    }

    渲染();
    面板?.状态?.订阅?.((键) => { if (键 === "选中段") 刷态(); });
    面板?.设时间轴刷卡?.(刷卡);   // 供状态栏编辑段提示词/首帧后回调，局部刷新段卡
    return { 渲染, 刷卡 };
}
