// 节点内多段时间轴（DOM 富 widget）：分段运行轨道 + 标尺 + 工具条。
// 真源仍是 node.widgets（时间轴数据/参考素材/运行选择 等 multiline JSON widget 被幽灵化隐藏，完整名单见下 幽灵widget；
// 剪辑草稿 真源已迁 node.properties、隔离执行缓存，其 widget 仅幽灵化占位），
// 本文件只负责「把 widget 里的段画得像个剪辑轨道」——所有读写都经 桥接/节点桥.js 的 真源。
import { 真源, 取widget, 解析段素材, 查找共用素材 } from "./桥接/节点桥.js";
import { 任务码 } from "./生成类型选择.js";
import { app } from "../../../scripts/app.js";
import { 创建缓存面板 } from "./缓存面板.js";
import { 分配中间帧 } from "./中间帧.js";

const 面板高 = 210;   // 时间轴最小高（弹性布局下限 --comfy-widget-min-height）；节点拉高时自动增大填满
const 节点默认宽 = 420;   // 画布节点最小默认宽，避免 widget 拥挤
const 节点默认高 = 600;   // 画布节点最小默认高
const 幽灵widget = ["时间轴数据", "参考素材", "运行选择", "剪辑草稿"];
const 吸附步 = 0.5;   // 秒，时长编辑吸附网格
// 段卡与标尺格必须同参（min-width/flex/gap 一致），两行才能逐列对齐（改一个必须同步改另一个）。
// min-width:0 + flex:0 0 0 + flexGrow(时长)：N 段按时长比例正好铺满容器宽（1 倍时永不横向溢出）；
// 放大＝把 内 的宽按比例撑开（见下 缩放视图），超出视口后靠横向滚动/滚轮/标尺拖拽看两端；
// 卡片变窄时靠容器查询分级隐藏次要元素/控件（见下），保证「始终看得到全部分段」。
const 列间隙 = 4;
// 缩放上限（倍）：与 剪辑时间轴.js 的 最大缩放 同源，两处必须一致（测试/测试_常量同步.py 锁死）。
const 最大缩放 = 40;

// 段色循环（琥珀/天蓝/翠绿/品红）：给每段一个稳定的视觉身份，只用于卡片顶条与「段N」徽标，
// 与「选中＝翠绿描边」分工不同（选中态另叠加外发光，见 .lvp-tl-卡.选中）。
const 段色 = ["#ffc850", "#66aaff", "#4fff8f", "#ff7ab8"];

const 样式已注入 = { v: false };
function 注入样式() {
    if (样式已注入.v) return;
    const s = document.createElement("style");
    // 时间轴挂在节点上，可能在状态栏面板（另一处样式注入）之前渲染，故自带独立样式块，
    // 不复用 .lvp-胶囊 等状态栏类名。
    s.textContent = `
      .lvp-时间轴{--tl-bg:var(--bg-color,#17181a);--tl-card:var(--comfy-menu-secondary-bg,#202226);--tl-line:var(--border-color,#2e3136);--tl-line2:var(--border-color,#4b515a);
        --tl-txt:var(--fg-color,#e8eaed);--tl-mut:var(--p-text-muted-color,#9aa0a8);--tl-dim:var(--p-text-muted-color,#6d737b);--tl-acc:#4fff8f;--tl-danger:#ff6b6b;
        height:100%;--comfy-widget-min-height:${面板高}px;
        display:flex;flex-direction:column;gap:4px;padding:6px;box-sizing:border-box;overflow:hidden;
        background:linear-gradient(180deg,var(--comfy-menu-bg,#1c1e22),var(--bg-color,#151619));border:1px solid var(--tl-line);border-radius:8px;
        font:11px ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--tl-txt)}
      .lvp-时间轴 *{box-sizing:border-box}

      /* ── 工具条 ───────────────────────────────────────── */
      .lvp-tl-工具{display:flex;align-items:center;gap:4px;flex:0 0 auto;min-width:0;overflow-x:auto}
      .lvp-tl-工具>*,.lvp-tl-工具>.lvp-cache>*{flex-shrink:0}
      .lvp-tl-钮{display:inline-flex;align-items:center;gap:4px;padding:2px 7px;line-height:1.35;border-radius:6px;
        border:1px solid var(--tl-line2);background:linear-gradient(180deg,var(--comfy-menu-bg,#2c2f35),var(--comfy-menu-secondary-bg,#23262b));
        color:var(--tl-txt);font:inherit;cursor:pointer;white-space:nowrap;
        transition:background .12s,border-color .12s,box-shadow .12s,transform .06s}
      .lvp-tl-钮:hover{background:linear-gradient(180deg,var(--comfy-menu-bg,#363a42),var(--comfy-menu-secondary-bg,#292d33));border-color:var(--border-color,#5d646f)}
      .lvp-tl-钮:active{transform:translateY(1px)}
      .lvp-tl-钮:disabled{opacity:.38;cursor:not-allowed;transform:none}
      .lvp-tl-钮.主{border-color:rgba(79,255,143,.42);color:#d8ffe8;
        background:linear-gradient(180deg,#22442f,#1a3325)}
      .lvp-tl-钮.主:hover:not(:disabled){border-color:var(--tl-acc);box-shadow:0 0 0 1px rgba(79,255,143,.18)}
      .lvp-tl-钮.危:hover:not(:disabled){border-color:var(--tl-danger);color:#ffdada;
        background:linear-gradient(180deg,#3b2426,#2c1c1e)}
      .lvp-tl-概要{color:var(--tl-mut);white-space:nowrap;font-variant-numeric:tabular-nums}

      /* 缩放控件（纯视图）：按钮复用 .lvp-tl-钮 款式＝与新增/删除同尺寸同主题；图标描边取 currentColor。
         右推靠撑位（非 margin-left:auto）：有余宽时撑位吃满→缩放组连同概要右靠、缩放条紧贴「共 N 段」左侧；
         工具条溢出（面板变窄）时撑位收成 0，缩放组与概要顺序紧跟左侧按钮整条横向滚，
         不再出现 auto 边距在 overflow 容器里把缩放组钉在右缘、概要文字压上来的重叠。 */
      .lvp-tl-撑{flex:1 1 0;min-width:0}
      .lvp-tl-缩放{display:inline-flex;align-items:center;gap:2px;flex:0 0 auto}
      .lvp-tl-缩放钮{padding:2px 5px;gap:0}
      .lvp-tl-缩放钮 svg{width:13px;height:13px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round;pointer-events:none}
      .lvp-tl-缩放入{appearance:none;width:64px;height:3px;margin:0 2px;border:0;border-radius:2px;background:var(--tl-line2);cursor:pointer;flex:0 0 auto}
      .lvp-tl-缩放入::-webkit-slider-thumb{appearance:none;width:9px;height:14px;border:0;border-radius:3px;background:var(--fg-color,#eee)}
      .lvp-tl-缩放入::-moz-range-thumb{width:9px;height:14px;border:0;border-radius:3px;background:var(--fg-color,#eee)}
      .lvp-tl-缩放入:disabled{opacity:.38;cursor:not-allowed}
      .lvp-tl-缩放钮:focus-visible,.lvp-tl-缩放入:focus-visible{outline:2px solid var(--tl-acc);outline-offset:2px}
      .lvp-tl-倍{color:var(--tl-mut);font-size:10px;min-width:28px;text-align:right;font-variant-numeric:tabular-nums}

      /* 工具条「渐变过渡」开关：外框沿用 .lvp-tl-钮 的胶囊底让它在一排按钮里协调，滑块复用
         .lvp-tl-滑（其基础样式全局可用），仅 :checked 态另立 .lvp-tl-锚 作用域——不触碰
         段卡内 .lvp-tl-跑 的既有规则，避免相互串味。 */
      .lvp-tl-锚{display:inline-flex;align-items:center;gap:5px;flex:0 0 auto;position:relative;
        padding:2px 7px;line-height:1.35;border-radius:6px;border:1px solid var(--tl-line2);cursor:pointer;
        user-select:none;white-space:nowrap;color:var(--tl-mut);font:inherit;font-size:10px;
        background:linear-gradient(180deg,var(--comfy-menu-bg,#2c2f35),var(--comfy-menu-secondary-bg,#23262b));transition:background .12s,border-color .12s}
      .lvp-tl-锚:hover{background:linear-gradient(180deg,var(--comfy-menu-bg,#363a42),var(--comfy-menu-secondary-bg,#292d33));border-color:var(--border-color,#5d646f)}
      .lvp-tl-锚 input{position:absolute;opacity:0;width:0;height:0;margin:0}
      .lvp-tl-锚 input:checked+.lvp-tl-滑{background:rgba(79,255,143,.26)}
      .lvp-tl-锚 input:checked+.lvp-tl-滑::after{transform:translateX(10px);background:var(--tl-acc)}
      .lvp-tl-锚 input:checked~.lvp-tl-锚字{color:var(--tl-acc)}
      .lvp-tl-锚 input:focus-visible+.lvp-tl-滑{box-shadow:0 0 0 2px rgba(79,255,143,.34)}

      /* ── 轨道区（标尺 + 轨道同参逐列对齐；1 倍时宽度自适应铺满，放大后横向滚动细看） ── */
      /* 卷本身是 flex 列：空态的 flex:1 才撑得满（否则 0 段时下面留一块死黑） */
      .lvp-tl-卷{flex:1 1 auto;min-height:0;overflow-x:auto;overflow-y:auto;display:flex;flex-direction:column}
      .lvp-tl-卷>.lvp-tl-空态{flex:1 1 auto}
      .lvp-tl-卷::-webkit-scrollbar{width:8px;height:8px}
      .lvp-tl-卷::-webkit-scrollbar-thumb{background:var(--comfy-menu-bg,#343a42);border-radius:4px}
      .lvp-tl-卷::-webkit-scrollbar-thumb:hover{background:var(--border-color,#464d57)}
      .lvp-tl-卷::-webkit-scrollbar-track{background:transparent}
      /* flex:0 0 auto + align-self:flex-start：内 的显式宽（＝基宽×倍率）不被 flex 收缩、不被拉伸回 100%，
         缩放才可能让内容超出视口；未缩放时 内容宽＝clientWidth，min-width:100% 兑住不出横向滚动条。 */
      .lvp-tl-内{display:flex;flex-direction:column;align-self:flex-start;gap:3px;min-width:100%;min-height:100%;flex:0 0 auto}

      /* flex-basis 必须为 0：否则基数取内容宽，flexGrow 只是「在内容宽之上再加权」，
         时长比例就失真了（5s 段和 10s 段看着一样宽）。标尺与轨道两行必须同参。 */
      /* 标尺＝横向平移把手（按住左右拖，与放大后的内容宽同步），故禁选中以免拖出文字高亮。 */
      .lvp-tl-标尺{display:flex;flex:0 0 auto;height:13px;align-items:flex-end;user-select:none;cursor:grab}
      .lvp-tl-标尺.拖中{cursor:grabbing}
      .lvp-tl-刻度{position:relative;min-width:0;flex:0 0 0;padding-left:6px;
        color:var(--tl-dim);font-size:10px;line-height:1;font-variant-numeric:tabular-nums}
      .lvp-tl-刻度::before{content:"";position:absolute;left:0;bottom:-3px;width:1px;height:6px;
        background:var(--tl-line2)}

      .lvp-tl-轨道{display:flex;align-items:stretch;flex:1 1 auto;min-height:128px;padding-bottom:2px}

      /* ── 段卡 ─────────────────────────────────────────── */
      .lvp-tl-卡{position:relative;display:flex;flex-direction:column;gap:4px;flex:0 0 0;
        min-width:0;padding-bottom:4px;overflow:hidden;cursor:pointer;
        container-type:inline-size;
        background:linear-gradient(180deg,var(--tl-card),var(--bg-color,#1b1d21));
        border:1px solid var(--tl-line);border-left:3px solid var(--rolec,#8c8c8c);border-radius:7px;
        transition:border-color .12s,box-shadow .12s,transform .08s,opacity .14s,filter .14s}
      .lvp-tl-卡:hover{border-color:var(--tl-line2);transform:translateY(-1px);
        box-shadow:0 4px 14px rgba(0,0,0,.38)}
      .lvp-tl-卡.选中{border-color:var(--tl-acc);
        box-shadow:0 0 0 1px rgba(79,255,143,.26),0 6px 18px rgba(0,0,0,.46)}
      .lvp-tl-卡.停{opacity:.4;filter:saturate(.3)}
      .lvp-tl-卡.停:hover{opacity:.78;filter:saturate(.6)}
      .lvp-tl-顶条{height:2px;flex:0 0 auto;background:var(--seg);opacity:.9}

      .lvp-tl-头{display:flex;align-items:center;gap:4px;padding:0 6px;flex:0 0 auto}
      .lvp-tl-序号{flex:0 0 auto;height:16px;min-width:17px;padding:0 4px;border-radius:4px;
        display:inline-flex;align-items:center;justify-content:center;
        background:var(--segsoft);color:var(--seg);font-size:10px;font-weight:700}
      .lvp-tl-任务{flex:0 0 auto;padding:1px 5px;border-radius:8px;background:var(--comfy-input-bg,#2b2f36);
        color:var(--tl-mut);font-size:10px;letter-spacing:.02em}
      .lvp-tl-区间{margin-left:auto;color:var(--tl-dim);font-size:10px;white-space:nowrap;
        font-variant-numeric:tabular-nums}

      /* 首帧图随卡片高度伸缩（flex:1，下限 44px）：节点拉高→卡片变高→缩略图放大铺满，
         避免多余高度堆在提示词区留白（词固定 2 行）；img object-fit:cover 裁切填充。 */
      .lvp-tl-图{position:relative;flex:1 1 44px;min-height:44px;margin:0 6px;border-radius:5px;
        overflow:hidden;background:var(--comfy-input-bg,#101114)}
      .lvp-tl-图 img{width:100%;height:100%;object-fit:cover;display:block}
      .lvp-tl-图::after{content:"";position:absolute;inset:0;pointer-events:none;
        background:linear-gradient(180deg,rgba(0,0,0,0) 48%,rgba(0,0,0,.5))}
      .lvp-tl-图空{height:100%;display:flex;align-items:center;justify-content:center;
        color:var(--p-text-muted-color,#4e555d);font-size:10px;
        background:repeating-linear-gradient(135deg,var(--comfy-input-bg,#17191c),var(--comfy-input-bg,#17191c) 6px,var(--comfy-menu-secondary-bg,#1c1f23) 6px,var(--comfy-menu-secondary-bg,#1c1f23) 12px)}

      .lvp-tl-词{flex:0 0 auto;margin:0 6px;color:var(--tl-mut);font-size:10px;
        line-height:1.45;word-break:break-word;overflow:hidden;
        display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
      .lvp-tl-词.空{color:var(--p-text-muted-color,#565c64);font-style:italic}

      .lvp-tl-标题{flex:0 0 auto;margin:0 6px;color:var(--tl-txt);font-size:10px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .lvp-tl-字幕{flex:0 0 auto;margin:0 6px;color:var(--tl-dim);font-size:10px;font-style:italic;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

      .lvp-tl-脚{display:flex;align-items:center;gap:4px;margin:0 6px;flex:0 0 auto}
      .lvp-tl-时长{display:flex;align-items:center;flex:0 0 auto;overflow:hidden;
        border:1px solid var(--tl-line);border-radius:5px;background:var(--comfy-input-bg,#141619)}
      .lvp-tl-时长 button{width:16px;height:20px;padding:0;border:none;background:transparent;
        color:var(--tl-mut);font:inherit;font-size:12px;line-height:1;cursor:pointer}
      .lvp-tl-时长 button:hover{background:var(--comfy-menu-bg,#272b31);color:var(--tl-txt)}
      .lvp-tl-时长 input{width:30px;height:20px;padding:0;text-align:center;background:transparent;
        border:none;border-left:1px solid var(--tl-line);border-right:1px solid var(--tl-line);
        color:var(--tl-txt);font:inherit;font-size:10px;font-variant-numeric:tabular-nums;
        appearance:textfield;-moz-appearance:textfield}
      .lvp-tl-时长 input::-webkit-outer-spin-button,
      .lvp-tl-时长 input::-webkit-inner-spin-button{-webkit-appearance:none;margin:0}
      .lvp-tl-时长 input:focus{outline:none;background:var(--comfy-input-bg,#1e2228)}

      .lvp-tl-跑{position:relative;margin-left:auto;display:inline-flex;align-items:center;gap:4px;
        color:var(--tl-dim);font-size:10px;cursor:pointer;user-select:none;flex:0 0 auto}
      .lvp-tl-跑字{white-space:nowrap}
      /* 窄卡只留开关（颜色已表意），宽卡才补「运行」二字，避免文字被挤成竖排 */
      @container (max-width:131px){.lvp-tl-跑字{display:none}}
      /* 卡片随段数增多而变窄时分级降级，保证「全部分段始终可见、内容不被裁切」：
         ≤118px 收区间+时长步进器（脚只留运行开关）→ ≤76px 收任务标签 → ≤56px 收提示词 → ≤38px 收运行开关。
         要精调某段时长/运行，把节点拉宽即可（widget 宽随节点宽 → 卡片变宽 → 控件复现）。 */
      @container (max-width:118px){.lvp-tl-区间,.lvp-tl-时长{display:none}}
      @container (max-width:118px){.lvp-tl-字幕{display:none}}
      @container (max-width:76px){.lvp-tl-任务{display:none}}
      @container (max-width:76px){.lvp-tl-标题{display:none}}
      @container (max-width:56px){.lvp-tl-词{display:none}}
      @container (max-width:38px){.lvp-tl-脚{display:none}}
      .lvp-tl-跑 input{position:absolute;opacity:0;width:0;height:0;margin:0}
      .lvp-tl-滑{position:relative;flex:0 0 auto;width:22px;height:12px;border-radius:6px;
        background:var(--comfy-menu-bg,#343a42);transition:background .14s}
      .lvp-tl-滑::after{content:"";position:absolute;top:2px;left:2px;width:8px;height:8px;
        border-radius:50%;background:var(--p-text-muted-color,#8b929b);transition:transform .14s,background .14s}
      .lvp-tl-跑 input:checked+.lvp-tl-滑{background:rgba(79,255,143,.26)}
      .lvp-tl-跑 input:checked+.lvp-tl-滑::after{transform:translateX(10px);background:var(--tl-acc)}
      .lvp-tl-跑 input:checked~.lvp-tl-跑字{color:var(--tl-acc)}
      .lvp-tl-跑 input:focus-visible+.lvp-tl-滑{box-shadow:0 0 0 2px rgba(79,255,143,.34)}

      /* ── 空态 ─────────────────────────────────────────── */
      .lvp-tl-空态{flex:1 1 auto;display:flex;flex-direction:column;align-items:center;
        justify-content:center;gap:9px;border:1px dashed var(--tl-line2);border-radius:7px;
        color:var(--tl-dim);background:rgba(255,255,255,.014);text-align:center;padding:10px}
      .lvp-tl-空态 b{color:var(--tl-mut);font-weight:600}`;
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
    根.className = "lvp-时间轴";
    // 高度不再内联固定：改由 .lvp-时间轴{height:100%} 填满 DOM widget 包裹层，包裹层高＝widget 的
    // computedHeight＝框架弹性布局分给本 widget 的剩余节点高（拉高节点→时间轴跟着变高）。
    // 其余样式全在 .lvp-时间轴 里：内联样式写不了 :hover/伪元素/过渡，是旧版「像调试线框」的主因。

    const widget = node.addDOMWidget("时间轴", "dom", 根, { getValue: () => "", setValue: () => {}, getMinHeight: () => 面板高, serialize: false });
    widget.serialize = false;   // 纯展示 widget：graphToPrompt 按 widget 名写 prompt inputs，未声明的「时间轴」会让交接图判定整图拒绝；存档也不占 widgets_values 槽（08 §1 自建控件口径）。
    // 故意不设 widget.computeSize：布局引擎把「有 computeSize」的 widget 当固定高，只有「仅有
    // computeLayoutSize」的才弹性。DOMWidgetImpl 自带 computeLayoutSize（读 --comfy-widget-min-height
    // 作下限），于是时间轴成为节点内唯一弹性 widget——节点被拉高时剩余空间全归它，拉多高填多高。
    // 强制最小默认宽高：computeSize 自动值偏小会让 widget 拥挤，取下界兑底
    const [算宽, 算高] = node.computeSize();
    node.setSize([Math.max(算宽, 节点默认宽), Math.max(算高, 节点默认高)]);
    node.setDirtyCanvas?.(true, true);   // 幽灵化+DOM 隐藏后强制重排，消除遮挡

    // 重渲染复用缓存控件，保留统计结果及清理中的按钮状态。
    const 缓存条 = document.createElement("div");
    const 缓存面板 = 创建缓存面板(缓存条, {
        取节点: () => node,
        弹确认: (标题, 消息) => app.extensionManager.dialog.confirm({ title: 标题, message: 消息 }),
        toast: (消息, severity = "info") => app?.ui?.toast?.showMessage?.({ message: 消息, severity }),
    });

    function 读段() { return (真源.读时间轴(node).segments) || []; }
    // 落盘＝只写 widget + 通知状态栏回填；写段＝落盘后整树重建（结构性增删才需要）。
    function 落盘(段组) { 真源.写时间轴(node, { segments: 段组 }); 面板?.回填?.(); }
    function 写段(段组) { 落盘(段组); 渲染(); }

    // 多节点解耦：全局「选中段」只承载状态栏**当前绑定节点**的选中（供编辑页回填）；
    // 非绑定节点用实例本地选择，否则点 A 节点分段会经全局键把 B 节点高亮一起切过去（两节点互相触发）。
    function 是绑定() { return 面板?.取节点?.() === node; }
    let 本地选中 = 0;
    function 选中() { return 是绑定() ? (面板?.状态?.取?.("选中段") ?? 0) : 本地选中; }
    function 设选中(i) {
        if (是绑定()) 面板?.状态?.设?.("选中段", i);
        else {
            本地选中 = i;
            // 本地选择不广播，增删后须同步刷新刚重建的卡片高亮。
            刷态();
        }
    }

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
        总秒数 = 段组.reduce((a, s) => a + 秒数(s), 0);
        卡片组.forEach((卡, i) => { 卡.style.flexGrow = String(秒数(段组[i])); });
        刻度组.forEach((格, i) => { 格.style.flexGrow = String(秒数(段组[i])); });
        刷缩放视图();   // 总时长变了：内容宽不变，但「时间→横滚像素」的比例变了，要按新总时长重投影
    }

    function 刷概要() {
        if (!概要) return;
        const 段组 = 读段();
        const 跑 = 段组.filter((s) => s.run).length;
        概要.textContent = 段组.length
            ? `共 ${段组.length} 段 · 运行 ${跑} · ${一位(总秒数)}s`   // 总秒数 与缩放共用一份，概要读数不与横滚换算各说各话
            : "";
    }

    function 刷区间(卡, s) {
        const 元 = 卡.querySelector(".lvp-tl-区间");
        if (元) 元.textContent = `${一位(s?.start || 0)}–${一位(s?.end || 0)}s`;
    }

    // 状态栏编辑提示词/首帧/任务码后，就地刷新对应段卡的「图/词/任务徽标」（不整树重建，保住过渡与焦点）。
    // 卡片还没建（如状态栏在空段组里新建了段）→ 回退整树重建，让新段现身。
    function 刷卡(i) {
        const 卡 = 卡片组[i];
        if (!卡) { 渲染(); return; }
        const 段组 = 读段(), s = 段组[i];
        if (!s) return;
        const 图 = 卡.querySelector(".lvp-tl-图");
        if (图) 填图(图, s, 读素材来源(段组));
        const 词 = 卡.querySelector(".lvp-tl-词");
        if (词) 填词(词, s);
        // 任务徽标与卡 title 同步（任务码切换时只改这两个字段，不重建卡）：
        // 卡 title 格式与 建卡/改时长 一致（段N · task · X–Ys），start/end 未变直接重拼即可。
        const 任 = 卡.querySelector(".lvp-tl-任务");
        if (任) 任.textContent = s.task || "t2v";
        卡.title = `段${i + 1} · ${(s.task || "t2v")} · ${一位(s.start || 0)}–${一位(s.end || 0)}s`;
        if (s.职能色) 卡.style.setProperty("--rolec", s.职能色); else 卡.style.removeProperty("--rolec");
        const 题 = 卡.querySelector(".lvp-tl-标题"), 幕 = 卡.querySelector(".lvp-tl-字幕");
        if ((题 && !s.标题) || (!题 && s.标题) || (幕 && !s.字幕) || (!幕 && s.字幕)) { 渲染(); return; }
        if (题) 题.textContent = s.标题;
        if (幕) 幕.textContent = s.字幕;
    }

    function 建钮(文本, 类名, 提示, fn) {
        const b = document.createElement("button");
        b.className = "lvp-tl-钮" + (类名 ? " " + 类名 : "");
        b.type = "button"; b.textContent = 文本; b.title = 提示; b.onclick = fn;
        return b;
    }

    // 工具条「渐变过渡」开关：真源是节点隐藏 widget「尾帧锚定」（布尔），此处仅读写它。
    // 开启→执行核心沿用默认上下文帧数(22)、以上一段尾帧 latent + 约 1 秒尾音频做续拍条件
    //   锚入下一段（段间连续），接缝零重叠硬切、只对续拍段开头做低频色光衔接；
    //   关闭→上下文帧数=0、各段独立生成、接缝硬切（不做任何过渡）。
    // 每次 渲染() 现读 widget 值，故与节点状态恒同步。
    function 建锚定开关() {
        const 标 = document.createElement("label");
        标.className = "lvp-tl-锚";
        标.title = "渐变过渡：开启则把上一段尾帧画面与约 1 秒尾音频作为续拍条件锚入下一段（官方 AddGuide 同款 latent 直传），接缝零重叠硬切、只对续拍段开头做低频色光衔接；续拍开头优先使用上段尾部，指定新首帧须关闭续拍；关闭则各段独立生成、接缝硬切、不做任何过渡处理（写入节点隐藏 widget「尾帧锚定」）";
        标.onclick = (e) => e.stopPropagation();
        const cb = document.createElement("input");
        cb.type = "checkbox"; cb.checked = 真源.读尾帧锚定(node);
        cb.onchange = () => 真源.写尾帧锚定(node, cb.checked);
        const 滑 = document.createElement("span");
        滑.className = "lvp-tl-滑";
        const 字 = document.createElement("span");
        字.className = "lvp-tl-锚字"; 字.textContent = "渐变过渡";
        标.append(cb, 滑, 字);
        return 标;
    }

    // ── 缩放视图（与 剪辑时间轴.js 同一模型，参照 OpenCut/CapCut 时间轴缩放）──────────
    // 内容宽＝视口宽×倍率：只改 内 的宽，不做 scaleX/transform，故字形始终清晰；
    // 横向位置的唯一真源是「视口左缘对应的时间」(视图起点，单位秒)，scrollLeft 只是它在当前内容宽上的
    // 投影 → 整树重建、改倍率、改总时长都能复原视图。纯视图态：不写 widget、不写草稿、不发请求。
    // 节点时间轴没有播放头也没有 scrub，所以滑块/按钮以「左缘时间」为锚，滚轮以「指针处时间」为锚。
    let 缩放 = 1, 视图起点 = 0, 总秒数 = 0;
    let 卷El = null, 内El = null, 标尺El = null, 收平移 = null;
    let 缩放入 = null, 适配钮 = null, 缩小钮 = null, 放大钮 = null, 倍标 = null;

    // 容器宽＝0 表示「此刻测不出尺寸」（节点折叠、刚重建还没布局）：此时浏览器报的 scrollLeft 不是真值，
    // 一律不得据此回写 视图起点，否则一展开节点视图就跳回 0s（F1/I16 同源坑）。
    const 基宽 = () => 卷El?.clientWidth ?? 0;

    function 记视口起点() {
        const 内容 = 基宽() * 缩放;
        if (内容 > 0 && 总秒数 > 0) 视图起点 = 卷El.scrollLeft / 内容 * 总秒数;
    }

    function 刷缩放控件() {
        if (!缩放入) return;
        const 倍文 = String(Number(缩放.toFixed(2)));
        缩放入.value = String(Math.log2(缩放));   // 滑块走 log2 刻度：等距拖动＝等比缩放，1× 落在正中偏左
        缩放入.title = `时间轴缩放 ${倍文} 倍`;
        缩放入.setAttribute("aria-valuetext", `${倍文} 倍`);
        倍标.textContent = `${倍文}×`;            // 读数紧跟按钮：连续点缩放时每次都看得到结果
        const 禁用 = 总秒数 <= 0;                 // 空时间轴没有可放大的内容，整套禁用（控件仍占位，工具条不跳动）
        缩放入.disabled = 适配钮.disabled = 禁用;
        缩小钮.disabled = 禁用 || 缩放 <= 1;
        放大钮.disabled = 禁用 || 缩放 >= 最大缩放;
    }

    function 刷缩放视图() {
        const 宽 = 基宽(), 内容 = 宽 * 缩放;
        if (内El && 宽 > 0) 内El.style.width = `${内容}px`;
        if (宽 > 0 && 总秒数 > 0) {   // 测不出宽/无段时什么都不写（见上 基宽）
            卷El.scrollLeft = 视图起点 / 总秒数 * 内容;   // 越界由浏览器夹取
            视图起点 = 卷El.scrollLeft / 内容 * 总秒数;     // 回读夹取后的真值，防状态与 DOM 长期背离
        }
        刷缩放控件();
    }

    // 适配＝回到 0s 全景；给了 锚秒/锚偏移 则让该屏幕位置处的时间在缩放前后保持不变；都不给＝左缘时间不动。
    function 设缩放(值, 适配 = false, 锚秒 = null, 锚偏移 = 0) {
        if (收平移) { 刷缩放控件(); return; }   // 拖拽平移中改内容宽会让正在拖的手势跳位，先把手势做完
        const 新 = Math.min(最大缩放, Math.max(1, 值));
        if (!Number.isFinite(新) || 总秒数 <= 0) { 刷缩放控件(); return; }
        const 宽 = 基宽();
        if (适配) 视图起点 = 0;
        else if (锚秒 !== null && 宽 > 0) {
            const 起 = 锚秒 - 锚偏移 / (宽 * 新) * 总秒数;
            if (Number.isFinite(起)) 视图起点 = Math.max(0, 起);
        }
        缩放 = 新;
        刷缩放视图();
    }

    // 滚轮＝缩放（参照 CapCut）；触控板以横滑为主时不截留，交还原生滚动条平移。
    function 滚轮缩放(e) {
        if (收平移) { e.preventDefault(); return; }   // 平移中滚轮既不能变倍率，也不该顺带滚走
        const 宽 = 基宽();
        if (宽 <= 0 || 总秒数 <= 0) return;           // 宽＝0＝容器测不出尺寸（折叠/未布局）或空时间轴，交回宿主
        if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) return;
        e.preventDefault();
        const 偏移 = Math.max(0, e.clientX - 卷El.getBoundingClientRect().left);
        const 锚秒 = (卷El.scrollLeft + 偏移) / (宽 * 缩放) * 总秒数;
        设缩放(缩放 * 2 ** (-e.deltaY * (e.ctrlKey ? 0.01 : 0.0025)), false, 锚秒, 偏移);   // ctrl+滚轮（捏合）更灵敏
    }

    // 标尺拖拽＝横向平移视口：放大后看不到两端的段时，除滚动条外还能像剪辑器那样拖着看。
    // 监听全挂在 标尺 自身＋捕获指针，故指针滑出标尺仍跟随，且松手/取消/重建任一出口都能成对摘掉（不留 window 监听）。
    function 起平移(e) {
        if (收平移 || e.button !== 0 || !卷El || !标尺El || 总秒数 <= 0) return;
        e.preventDefault();
        const 卷 = 卷El, 标尺 = 标尺El, 起点 = e.clientX, 起始 = 卷.scrollLeft;
        标尺.classList.add("拖中");
        标尺.setPointerCapture?.(e.pointerId);
        const 移 = (ev) => {
            if (卷El !== 卷) return 收();   // 整树重建后旧把手不再服务当前视图
            卷.scrollLeft = 起始 - (ev.clientX - 起点);
            记视口起点();
        };
        const 收 = () => {
            标尺.classList.remove("拖中");
            if (标尺.hasPointerCapture?.(e.pointerId)) 标尺.releasePointerCapture(e.pointerId);
            for (const [名, fn] of [["pointermove", 移], ["pointerup", 收], ["pointercancel", 收]])
                标尺.removeEventListener(名, fn);
            if (收平移 === 收) 收平移 = null;
        };
        收平移 = 收;
        标尺.addEventListener("pointermove", 移);
        标尺.addEventListener("pointerup", 收, { once: true });
        标尺.addEventListener("pointercancel", 收, { once: true });
    }

    function 建缩放控件() {
        const 组 = document.createElement("div");
        组.className = "lvp-tl-缩放";
        const 建图标钮 = (名, 路径, 动作) => {
            const b = document.createElement("button");
            b.className = "lvp-tl-钮 lvp-tl-缩放钮"; b.type = "button"; b.title = b.ariaLabel = 名;
            const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
            svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true");
            const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
            path.setAttribute("d", 路径); svg.appendChild(path); b.appendChild(svg);
            b.onclick = 动作;
            return b;
        };
        // 图标只用大写字母（绝对坐标）命令：坐标可被测试逐项核对，杜绝相对位移画出 24×24 视口外的野笔画；
        // 描边取 currentColor，随工具行文字色＝跟随主题（不写死色值）。路径与 剪辑时间轴.js 同源。
        适配钮 = 建图标钮("适配全部", "M4 5V19M20 5V19M8 12H16M11 9L8 12L11 15M13 9L16 12L13 15", () => 设缩放(1, true));
        const 镜 = "M7 11A4 4 0 1 0 15 11A4 4 0 1 0 7 11M14 14L20 20M9 11H13";
        缩小钮 = 建图标钮("缩小", 镜, () => 设缩放(缩放 / Math.SQRT2));
        放大钮 = 建图标钮("放大", 镜 + "M11 9V13", () => 设缩放(缩放 * Math.SQRT2));
        缩放入 = document.createElement("input");
        缩放入.className = "lvp-tl-缩放入";
        缩放入.type = "range"; 缩放入.min = "0"; 缩放入.max = String(Math.log2(最大缩放)); 缩放入.step = "0.01";
        缩放入.ariaLabel = "时间轴缩放";
        缩放入.oninput = () => 设缩放(2 ** Number(缩放入.value));
        倍标 = document.createElement("span");
        倍标.className = "lvp-tl-倍"; 倍标.title = "当前时间轴缩放倍率";
        组.append(适配钮, 缩小钮, 缩放入, 放大钮, 倍标);
        return 组;
    }
    // 缩放控件持久（只建一次）：整树重建时原样挂回工具条，倍率读数与禁用态随 刷缩放视图 复原，
    // 也让「空态↔有段」切换时工具条不新增/删除控件（不跳动）。
    const 缩放组 = 建缩放控件();

    function 建卡(s, i, 来源) {
        const 卡 = document.createElement("div");
        卡.className = "lvp-tl-卡";
        const 色 = 段色[i % 段色.length];
        卡.style.setProperty("--seg", 色);
        卡.style.setProperty("--segsoft", 色 + "24");   // 8 位 hex：14% 不透明度
        if (s.职能色) 卡.style.setProperty("--rolec", s.职能色);   // 无则不设，CSS var(--rolec,兜底) 生效
        卡.title = `段${i + 1} · ${(s.task || "t2v")} · ${一位(s.start || 0)}–${一位(s.end || 0)}s`;
        卡.onclick = () => { 设选中(i); 刷态(); };

        const 顶 = document.createElement("div");
        顶.className = "lvp-tl-顶条";
        卡.appendChild(顶);

        // 头：段号徽标 + 任务码 + 起止区间
        const 头 = document.createElement("div");
        头.className = "lvp-tl-头";
        const 序 = document.createElement("span");
        序.className = "lvp-tl-序号"; 序.textContent = String(i + 1);
        const 任 = document.createElement("span");
        任.className = "lvp-tl-任务"; 任.textContent = s.task || "t2v";
        const 区 = document.createElement("span");
        区.className = "lvp-tl-区间";
        头.append(序, 任, 区);
        卡.appendChild(头);
        刷区间(卡, s);
        if (s.标题) {
            const 题 = document.createElement("div");
            题.className = "lvp-tl-标题"; 题.textContent = s.标题; 题.title = s.标题;
            卡.appendChild(题);
        }

        // 缩略图：按本段 task 门控（见下方 图名Of）取到图名才出图，否则给斜纹占位（避免高度跳动）
        const 图 = document.createElement("div");
        图.className = "lvp-tl-图";
        填图(图, s, 来源);
        卡.appendChild(图);

        // 提示词预览（两行截断）：轨道上一眼能认出哪段是哪段，不必逐段点开状态栏
        const 词 = document.createElement("div");
        填词(词, s);
        卡.appendChild(词);
        if (s.字幕) {
            const 幕 = document.createElement("div");
            幕.className = "lvp-tl-字幕"; 幕.textContent = s.字幕; 幕.title = s.字幕;
            卡.appendChild(幕);
        }

        // 脚：时长步进器 + 运行开关
        const 脚 = document.createElement("div");
        脚.className = "lvp-tl-脚";
        脚.append(建时长(s, i), 建运行(s, i));
        卡.appendChild(脚);

        return 卡;
    }

    function 建图空() {
        const 空 = document.createElement("div");
        空.className = "lvp-tl-图空";
        空.textContent = "无首帧";
        return 空;
    }

    // 段卡「图/词」填充：建卡（整树重建）与 刷卡（局部刷新）共用，避免两处逻辑漂移。
    // 来源与任务分开：参考任务显示共用覆盖/逐键补缺后的首张图片；显式空槽不能回退全局。
    // i2v/fl2v 只显示独立首帧（尾帧不占段卡），取消后不借用图片候选；t2v 恒为占位。
    const 吃首帧任务 = new Set(["i2v", "fl2v"]);
    const 吃参考图任务 = new Set(["r2v", "v2v", "rv2v"]);
    function 读素材来源(段组) {
        const 全局 = 真源.读参考素材(node);
        return { 全局, 共用: 查找共用素材(段组, 全局, 真源.读参考共用(node)) };
    }
    function 图名Of(s, 来源) {
        const 码 = (s?.task || "").toLowerCase();
        if (吃首帧任务.has(码)) return s?.refs?.首帧 || "";
        if (!吃参考图任务.has(码)) return "";
        return 解析段素材(s?.refs, 来源.全局, 来源.共用).图片[0] || "";
    }

    function 填图(图, s, 来源) {
        const 图名 = 图名Of(s, 来源);
        // 图名未变且已有内容 → 不重建 <img>，避免只改提示词时缩略图重载闪烁
        if (图.dataset.名 === 图名 && 图.firstChild) return;
        图.dataset.名 = 图名;
        图.replaceChildren();
        if (图名) {
            const img = document.createElement("img");
            img.src = "/lvp/media/file?name=" + encodeURIComponent(图名);
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
        词.className = "lvp-tl-词" + (文 ? "" : " 空");
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
            卡.title = `段${i + 1} · ${(s.task || "t2v")} · ${一位(s.start || 0)}–${一位(s.end || 0)}s`;
        }
    }

    function 建时长(s, i) {
        const 盒 = document.createElement("div");
        盒.className = "lvp-tl-时长";
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
        标.className = "lvp-tl-跑";
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
        滑.className = "lvp-tl-滑";
        const 字 = document.createElement("span");
        字.className = "lvp-tl-跑字"; 字.textContent = "运行";
        标.append(cb, 滑, 字);
        return 标;
    }

    function 渲染() {
        const 段组 = 读段();
        卡片组 = []; 刻度组 = []; 概要 = null;
        收平移?.();   // 拖拽平移中发生整树重建：先收尾摘掉旧 标尺 上的监听，否则监听随旧节点一起成僵尸
        内El = null; 标尺El = null;
        // 删空后复位缩放：否则下次新增段会停在旧倍率/旧横滚位置（有段时 总秒数 由 刷比例 现算）。
        if (!段组.length) { 缩放 = 1; 视图起点 = 0; 总秒数 = 0; }
        根.replaceChildren();

        // 工具条：主操作（新增）绿、破坏性操作（删除）红悬停，右侧实时概要
        const 工具 = document.createElement("div");
        工具.className = "lvp-tl-工具";
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
        // 裁剪时深拷贝 refs：确保两半各自拥有独立的素材数组，编辑一段不影响另一段
        function 深拷refs(refs) {
            if (!refs) return undefined;
            const r = { ...refs };
            if (Array.isArray(r.图片)) r.图片 = [...r.图片];
            if (Array.isArray(r.音频)) r.音频 = [...r.音频];
            if (Array.isArray(r.视频)) r.视频 = [...r.视频];
            return r;
        }
        const 裁剪 = 建钮("✂裁剪", "", "把选中段从中点一分为二", () => {
            const 段组 = 读段();
            const i = 选中(); const s = 段组[i]; if (!s) return;
            const 中 = s.start + (s.end - s.start) / 2;
            let 子段;
            try {
                子段 = 分配中间帧(s, [
                    { ...s, end: 中, refs: 深拷refs(s.refs) },
                    { ...s, start: 中, refs: 深拷refs(s.refs) },
                ]);
            } catch (e) {
                return app.extensionManager.dialog.confirm({ title: "无法裁剪", message: e.message }).catch(() => {});
            }
            段组.splice(i, 1, ...子段);
            写段(段组);
        });
        const 全选 = 建钮("全选运行", "", "所有段都参与生成", () => { const 段组 = 读段(); 段组.forEach((s) => (s.run = true)); 写段(段组); });
        const 全不选 = 建钮("全不选", "", "所有段都不参与生成", () => { const 段组 = 读段(); 段组.forEach((s) => (s.run = false)); 写段(段组); });
        const 锚定 = 建锚定开关();   // 全局开关，不随「有无段」禁用：无段时也可先设好再建段
        删除.disabled = 裁剪.disabled = !有段;
        全选.disabled = 全不选.disabled = !有段;
        概要 = document.createElement("span");
        概要.className = "lvp-tl-概要";
        缓存面板.同步失效版本();
        const 撑 = document.createElement("div"); 撑.className = "lvp-tl-撑";
        工具.append(新增, 删除, 裁剪, 全选, 全不选, 锚定, 缓存条, 撑, 缩放组, 概要);
        根.appendChild(工具);

        const 卷 = document.createElement("div");
        卷.className = "lvp-tl-卷";
        卷El = 卷;
        卷.addEventListener("scroll", 记视口起点, { passive: true });   // 滚动条/触控板横滑都经这里回写视图起点
        卷.addEventListener("wheel", 滚轮缩放, { passive: false });     // 非 passive：缩放时要 preventDefault 抢下滚轮
        根.appendChild(卷);

        if (!有段) {
            const 空 = document.createElement("div");
            空.className = "lvp-tl-空态";
            const 标 = document.createElement("b");
            标.textContent = "还没有分段";
            const 提 = document.createElement("div");
            提.textContent = "点「＋新增段」建第一段；每段独立填提示词、绑首帧、单独开关运行。";
            const 大 = 建钮("＋新增段", "主", "新建第一段", 新增.onclick);
            空.append(标, 提, 大);
            卷.appendChild(空);
            刷缩放视图();   // 无 内 可写宽，只把控件复位成全禁用＋1× 读数
            刷概要();
            return;
        }

        // 标尺与轨道同参（列间隙 + flex:0 0 0 + flexGrow 时长）→ 两行逐列对齐；
        // 1 倍时宽度自适应铺满视口，放大后 内 变宽＝超出视口 → 横向滚动条/滚轮/标尺拖拽都能看全部分段。
        const 内 = document.createElement("div");
        内.className = "lvp-tl-内";
        const 标尺 = document.createElement("div");
        标尺.className = "lvp-tl-标尺";
        标尺.title = "按住左右拖＝平移时间轴视口（放大后看两端的段）";
        内El = 内; 标尺El = 标尺;
        标尺.addEventListener("pointerdown", 起平移);
        const 轨 = document.createElement("div");
        轨.className = "lvp-tl-轨道";
        轨.style.gap = 标尺.style.gap = `${列间隙}px`;

        const 来源 = 读素材来源(段组);   // 整次渲染只读一次全局素材、只查一次共用源
        段组.forEach((s, i) => {
            const 格 = document.createElement("div");
            格.className = "lvp-tl-刻度";
            格.textContent = `${一位(s.start || 0)}s`;
            标尺.appendChild(格);
            刻度组.push(格);

            const 卡 = 建卡(s, i, 来源);
            轨.appendChild(卡);
            卡片组.push(卡);
        });
        内.append(标尺, 轨);
        卷.appendChild(内);

        刷比例(); 刷概要(); 刷态();
    }

    渲染();
    // 节点被拉宽/拉窄、折叠又展开、画布缩放都会改 卷 的可视宽＝基宽 → 内容宽与横滚投影都要跟着重算，
    // 否则倍率不变而画面停在旧宽度上（右侧留白或滚不到底）。
    const 尺寸观察者 = typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => 刷缩放视图()) : null;
    尺寸观察者?.observe(根);
    // 选中段变化只刷**绑定节点**的时间轴（非绑定节点高亮走本地，不受全局键影响）；
    // 绑定切换（换节点编辑）广播「绑定节点」键，全节点重刷以换选中数据源（全局↔本地）。
    const 退订 = 面板?.状态?.订阅?.((键) => { if (键 === "选中段" && 是绑定()) 刷态(); else if (键 === "绑定节点") 刷态(); });
    面板?.设时间轴刷卡?.(刷卡);   // 供状态栏编辑段提示词/首帧/任务码后回调，局部刷新段卡
    面板?.设时间轴渲染?.(渲染);   // 供计划数据加载后回调，整树重建（段数/顺序都可能变）
    // 3.3(121)：状态桥.订阅 返回 cleanup，旧代码丢弃 → 面板重建（热载）/节点移除后本实例
    // 的订阅成为僵尸监听器，反复 挂载时间轴 会累积（内存泄漏 + 每次广播越刷越慢）。
    // 统一销毁出口：宿主在 node.onRemoved 里调 destroy()，把本实例订阅从状态桥摘掉。
    return { 渲染, 刷卡, destroy: () => { 退订?.(); 尺寸观察者?.disconnect(); } };
}
