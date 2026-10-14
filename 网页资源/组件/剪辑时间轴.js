import { 取操作忙, 开始操作, 结束操作 } from "./操作锁.js";
import { 创建帧更新 } from "./帧更新.js";
// 剪辑时间轴（状态栏 AI规划页中间区）——预演草稿编辑器。
// 真源＝node.properties.剪辑草稿（{brief,segments}，隔离执行缓存），经 桥接/节点桥.js 真源.读/写剪辑草稿 读写。
// 🔒 铁律：本组件**只写剪辑草稿**，绝不写「时间轴数据」；「填充节点」经框架层 应用规划 才落节点真源。
// 统一线性时间坐标：无内边距的段槽按时长分配宽度，卡片间隙留在槽内，时间线/播放头不随局部段宽拉伸。
// 每段起点刻度行已废除（与连续时间线刻度重复），起止时间只出现在卡 title 与连续时间线上。
// 交互参照 AIVideo_node/网页资源/时间线面板.js（边缘把手命中/拖拽状态机）与
//   OpenCut（播放头处分割 split-at-playhead、删除后 ripple 闭拢、trim 为 rolling 边界）。
import { 真源, 捕获节点快照, 提交节点快照, 使节点快照失效, 新段ID, 分配段ID, 取上次编辑, 取下次编辑, 保存编辑记录, 写节点属性 } from "./桥接/节点桥.js";
import { 打开台词时长 } from "./台词时长面板.js";
import { 默认台词设置, 台词估时详情, 取台词文本, 保护台词提示词 } from "./台词时长.js";
import { 分配中间帧 } from "./中间帧.js";
import { 取H3改写资料, 写入提示词生成结果 } from "./H3改写资料.js";
import { 规划结果提示 } from "./规划结果提示.js";
import { 新提示词任务, 创建提示词任务客户端 } from "./提示词任务客户端.js";

const 吸附步 = 0.5;
const 最小时长 = 0.5;
const 最大输入时长 = 99;
const 有效输入时长 = (n) => Number.isFinite(n) && n >= 最小时长 && n <= 最大输入时长;
const 把手px = 6;   // 段卡左右边缘 ±6px 命中 trim 把手（参照 AIVideo_node RESIZE_EDGE=7 量级）
const 列间隙 = 4;
const 段色 = ["#ffc850", "#66aaff", "#4fff8f", "#ff7ab8"];
const 秒数 = (s) => Math.max(0, (s?.end || 0) - (s?.start || 0));
const 一位 = (n) => (Number.isFinite(n) ? n.toFixed(1) : "0.0");
const 时长文本 = (n) => {
    // 起止时间相减会产生浮点尾数；按顺移时的九位精度格式化，保留合法小数，不改原数据。
    const d = Number.isFinite(n) ? Number(n.toFixed(9)) : 0;
    return Number.isInteger(d) ? 一位(d) : String(d);
};
const 吸附 = (t) => Math.round(t / 吸附步) * 吸附步;

// 裁剪/分割时深拷贝 refs：确保两半各自拥有独立素材数组（与 时间轴面板.js 深拷refs 同源）。
function 深拷refs(refs) {
    if (!refs) return undefined;
    const r = { ...refs };
    if (Array.isArray(r.图片)) r.图片 = [...r.图片];
    if (Array.isArray(r.音频)) r.音频 = [...r.音频];
    if (Array.isArray(r.视频)) r.视频 = [...r.视频];
    return r;
}
// 结构性增删/重排后，按各段时长把 start/end 重排成从 0 起的连续时间轴（ripple 闭拢，不留空洞）。
function 重排时间(段组) {
    let t = 0;
    for (const s of 段组) { const d = 秒数(s); s.start = t; s.end = t + d; t += d; }
    return 段组;
}
// 把「选中块」整体移到 目标 插入位（目标为相对原数组的插入下标 0..n），返回新数组。
function 移块(段组, 选中idxs, 目标) {
    const 集 = new Set(选中idxs);
    const 移出 = 段组.filter((_, i) => 集.has(i));
    const 余 = 段组.filter((_, i) => !集.has(i));
    let 插在 = 0;
    段组.forEach((_, i) => { if (i < 目标 && !集.has(i)) 插在++; });
    余.splice(插在, 0, ...移出);
    return 余;
}

const 样式已注入 = { v: false };
function 注入样式() {
    if (样式已注入.v) return;
    const s = document.createElement("style");
    s.textContent = `
      .lvp-ct{display:flex;flex-direction:column;gap:4px;flex:1 1 auto;min-width:0;height:100%;box-sizing:border-box;background:var(--comfy-menu-bg,#2b2b2b);padding:6px;border-radius:8px;
        --ct-acc:#4fff8f;--ct-line:var(--border-color,#2e3136);--ct-line2:var(--border-color,#4b515a);
        --ct-mut:var(--p-text-muted-color,#9aa0a8);--ct-dim:var(--p-text-muted-color,#6d737b);--ct-danger:#ff6b6b;
        font:11px ui-sans-serif,system-ui,"Segoe UI",sans-serif;color:var(--fg-color,#e8eaed)}
      .lvp-ct *{box-sizing:border-box}
      .lvp-ct-行{display:flex;align-items:center;gap:4px;flex:0 0 auto;flex-wrap:nowrap}
            .lvp-ct-工具{min-width:0;overflow-x:auto}
            .lvp-ct-工具>.lvp-ct-钮{flex-shrink:0}
      /* 按钮皮肤全部取宿主主题变量（与节点时间轴 .lvp-tl-钮 同一套），切浅色主题不再留暗块；
         line-height 固定 + emoji 收进 .lvp-ct-图，避免表情字体的大行盒把个别按钮撑高。 */
      .lvp-ct-钮{display:inline-flex;align-items:center;gap:4px;padding:2px 7px;border-radius:6px;
        border:1px solid var(--ct-line2);background:linear-gradient(180deg,var(--comfy-menu-bg,#2c2f35),var(--comfy-menu-secondary-bg,#23262b));color:inherit;
        font:inherit;line-height:1.35;cursor:pointer;white-space:nowrap;transition:background .12s,border-color .12s,transform .06s}
      .lvp-ct-图{font-size:10px;line-height:1}
      .lvp-ct-钮:hover:not(:disabled){border-color:var(--border-color,#5d646f)}
      .lvp-ct-钮:active:not(:disabled){transform:translateY(1px)}
      .lvp-ct-钮:disabled{opacity:.38;cursor:not-allowed}
      .lvp-ct-钮.主{border-color:color-mix(in srgb,var(--ct-acc) 42%,transparent);color:var(--ct-acc);
        background:linear-gradient(180deg,color-mix(in srgb,var(--ct-acc) 18%,var(--comfy-menu-bg)),color-mix(in srgb,var(--ct-acc) 10%,var(--comfy-menu-secondary-bg)))}
      .lvp-ct-钮.危:hover:not(:disabled){border-color:var(--ct-danger);color:var(--ct-danger)}
      /* 禁用字幕开关：label 包住 checkbox＋文字，外观跟 .lvp-ct-钮 同一套配方（等高、不换行、主题变量取色）。 */
      .lvp-ct-开关{display:inline-flex;align-items:center;gap:4px;flex-shrink:0;padding:2px 7px;border-radius:6px;
        border:1px solid var(--ct-line2);background:linear-gradient(180deg,var(--comfy-menu-bg,#2c2f35),var(--comfy-menu-secondary-bg,#23262b));
        color:var(--ct-mut);font:inherit;line-height:1.35;cursor:pointer;white-space:nowrap}
      .lvp-ct-开关:hover:not(.关禁){border-color:var(--border-color,#5d646f)}
      .lvp-ct-开关.关禁{opacity:.38;cursor:not-allowed}
      .lvp-ct-开关框{appearance:auto;width:11px;height:11px;margin:0;flex:0 0 auto;cursor:inherit}
      .lvp-ct-选{padding:2px 5px;background:var(--comfy-input-bg,#1c1c1c);color:var(--fg-color,#ddd);
        border:1px solid var(--ct-line);border-radius:6px;font:11px system-ui;min-width:0;max-width:120px}
      .lvp-ct-标{color:var(--ct-mut);font-size:10px;white-space:nowrap}
      .lvp-ct-概要{color:var(--ct-mut);white-space:nowrap;font-variant-numeric:tabular-nums}
      .lvp-ct-应用状态{font-size:10px;line-height:1.4;color:var(--ct-mut);flex:0 0 auto}
      .lvp-ct-台词{flex:0 0 auto;color:var(--ct-mut);font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      /* 缩放组右推靠撑位（非 margin-left:auto）：有余宽时撑位吃满→缩放组连同概要右靠；
         工具条溢出（面板变窄）时撑位 flex-basis:0 收成 0，缩放组与概要顺序紧跟左侧按钮、整条横向滚，
         不再出现 auto 边距在 overflow 容器里把缩放组钉在右缘、概要文字压上来的重叠。 */
      .lvp-ct-撑{flex:1 1 0;min-width:0}
      .lvp-ct-缩放{display:flex;align-items:center;gap:4px;flex:0 0 auto}
      .lvp-ct-倍{color:var(--ct-mut);font-size:10px;min-width:28px;text-align:right;font-variant-numeric:tabular-nums}
      .lvp-ct-缩放钮{padding:2px 5px;gap:0}
      .lvp-ct-缩放钮 svg{width:13px;height:13px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round;pointer-events:none}
      /* 同装的其他节点（radiance）会注入未加作用域的全局规则 input[type=range]{width:100%!important;
         height:16px!important;background:transparent!important} 及 thumb/track 的 !important 覆写，
         让本条细线被拉成整行宽、盖住右侧概要文字。input[type=range] 权重 0-1-1 高于单类，
         故须同时抬到两层类（0-2-0）并对被覆写的属性补 !important 才压得住。 */
      .lvp-ct-缩放 .lvp-ct-缩放入{appearance:none!important;width:61px!important;height:3px!important;margin:0 2px;border:0;border-radius:2px;background:var(--ct-line2)!important;cursor:pointer;flex:0 0 auto}
      .lvp-ct-缩放 .lvp-ct-缩放入::-webkit-slider-runnable-track{height:3px!important;background:transparent!important;border:none!important}
      .lvp-ct-缩放 .lvp-ct-缩放入::-webkit-slider-thumb{appearance:none!important;width:9px!important;height:14px!important;border:0!important;border-radius:3px!important;background:var(--fg-color,#eee)!important;margin-top:-5.5px!important}
      .lvp-ct-缩放 .lvp-ct-缩放入::-moz-range-thumb{width:9px!important;height:14px!important;border:0!important;border-radius:3px!important;background:var(--fg-color,#eee)!important}
      .lvp-ct-缩放入:disabled{opacity:.38;cursor:not-allowed!important}
      .lvp-ct-缩放钮:focus-visible,.lvp-ct-缩放入:focus-visible{outline:2px solid var(--ct-acc);outline-offset:2px}
      .lvp-ct-卷{flex:1 1 auto;min-height:0;overflow-x:auto;overflow-y:auto;display:flex;flex-direction:column}
      .lvp-ct-卷::-webkit-scrollbar{width:8px;height:8px}
      .lvp-ct-卷::-webkit-scrollbar-thumb{background:var(--ct-line2,#343a42);border-radius:4px}
      .lvp-ct-卷::-webkit-scrollbar-track:horizontal{background:color-mix(in srgb,var(--fg-color,#e8eaed) 8%,var(--comfy-menu-bg,#2b2b2b));border-radius:4px}
      .lvp-ct-卷::-webkit-scrollbar-thumb:horizontal{background:color-mix(in srgb,var(--fg-color,#e8eaed) 58%,var(--comfy-menu-bg,#2b2b2b))}
      .lvp-ct-卷::-webkit-scrollbar-thumb:horizontal:hover{background:color-mix(in srgb,var(--fg-color,#e8eaed) 75%,var(--comfy-menu-bg,#2b2b2b))}
      .lvp-ct-卷::-webkit-scrollbar-thumb:horizontal:active{background:var(--fg-color,#e8eaed)}
      .lvp-ct-内{position:relative;display:flex;flex-direction:column;align-self:flex-start;gap:3px;min-width:100%;min-height:100%;flex:0 0 auto}
      .lvp-ct-时间线{position:relative;flex:0 0 auto;height:14px;overflow:hidden;user-select:none;cursor:grab}
      .lvp-ct-时间线.拖中{cursor:grabbing}
      .lvp-ct-时刻{position:absolute;top:0;bottom:0;padding-left:4px;color:var(--ct-dim);
        font-size:10px;line-height:1;font-variant-numeric:tabular-nums;white-space:nowrap}
      .lvp-ct-时刻::before{content:"";position:absolute;left:0;top:0;bottom:0;width:1px;background:var(--ct-line2)}
      .lvp-ct-轨道{display:flex;align-items:stretch;flex:1 1 auto;min-height:92px;padding-bottom:2px;
              background:rgba(255,255,255,.03);border:1px solid var(--ct-line);border-radius:6px}
      .lvp-ct-播放头{position:absolute;top:0;bottom:2px;width:1px;background:var(--ct-acc);pointer-events:none;opacity:.9;z-index:3}
      .lvp-ct-播放头::before{content:"";position:absolute;top:-1px;left:-4px;width:9px;height:9px;
        background:var(--ct-acc);clip-path:polygon(0 0,100% 0,50% 100%)}
      .lvp-ct-播放hit{position:absolute;top:0;height:17px;width:11px;margin-left:-5px;cursor:ew-resize;z-index:5}
      .lvp-ct-插入线{position:absolute;top:0;bottom:2px;width:2px;background:#66aaff;pointer-events:none;z-index:4}
      .lvp-ct-槽{position:relative;flex:0 0 0;min-width:0;overflow:hidden}
      .lvp-ct-槽:last-child>.lvp-ct-卡{right:0}
      .lvp-ct-卡{position:absolute;inset:0 ${列间隙}px 0 0;display:flex;flex-direction:column;gap:3px;min-width:0;
        padding:3px 5px;overflow:hidden;cursor:pointer;container-type:size;
        background:linear-gradient(180deg,var(--comfy-menu-secondary-bg,#202226),var(--bg-color,#1b1d21));
        border:1px solid var(--ct-line);border-left:3px solid var(--rolec,#8c8c8c);border-radius:6px;
        transition:border-color .12s,box-shadow .12s,opacity .14s,filter .14s}
      .lvp-ct-卡,.lvp-ct-卡 *{-webkit-user-select:none;user-select:none}
      .lvp-ct-卡:hover{border-color:var(--ct-line2)}
      .lvp-ct-卡.选中{border-color:var(--ct-acc);box-shadow:0 0 0 1px rgba(79,255,143,.26)}
      .lvp-ct-卡.多选{border-color:#66aaff;box-shadow:0 0 0 1px rgba(102,170,255,.3)}
      .lvp-ct-卡.停{opacity:.4;filter:saturate(.3)}
            .lvp-ct-卡.禁{opacity:.45;filter:saturate(.35);border-style:dashed}
      .lvp-ct-顶{height:2px;flex:0 0 auto;background:var(--seg);opacity:.9;margin:-3px -5px 0}
      .lvp-ct-头{display:flex;align-items:center;gap:4px}
      .lvp-ct-序{height:15px;min-width:16px;padding:0 4px;border-radius:4px;display:inline-flex;
        align-items:center;justify-content:center;background:var(--segsoft);color:var(--seg);font-size:10px;font-weight:700}
      .lvp-ct-区间{position:relative;z-index:3;display:inline-flex;align-items:center;min-width:0;margin-left:auto;color:var(--ct-dim);font-size:10px;font-variant-numeric:tabular-nums}
      .lvp-ct-卡 .lvp-ct-时长入{min-width:0;max-width:100%;padding:0 1px;border:1px solid transparent;border-radius:3px;background:transparent;color:inherit;font:inherit;text-align:right;cursor:text;-webkit-user-select:text;user-select:text}
      .lvp-ct-时长入:hover,.lvp-ct-时长入:focus{background:var(--comfy-input-bg,#1c1c1c);color:var(--fg-color,#ddd);border-color:var(--ct-line2);outline:none}
      .lvp-ct-时长入[aria-invalid="true"]{border-color:var(--ct-danger)}
      .lvp-ct-标题{flex:0 0 auto;color:var(--fg-color,#e8eaed);font-size:10px;font-weight:600;
        white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .lvp-ct-素材{flex:0 0 auto;color:var(--ct-mut);font-size:9px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      @container (max-width:76px){.lvp-ct-素材{display:none}}
      .lvp-ct-角色{flex:0 1 auto;min-width:0;color:var(--seg);font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .lvp-ct-对白{flex:0 0 auto;color:var(--ct-dim);font-size:10px;font-style:italic;
        white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .lvp-ct-验收{flex:0 0 auto;font-size:9px;line-height:1.3;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
      .lvp-ct-词{flex:1 1 auto;min-height:0;color:var(--ct-mut);font-size:10px;line-height:1.35;overflow:hidden;
        display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;word-break:break-word}
      .lvp-ct-把手{position:absolute;top:0;bottom:0;width:min(${把手px * 2}px,34%);cursor:ew-resize;z-index:2}
      .lvp-ct-把手.左{left:0}
      .lvp-ct-把手.右{right:0}
      .lvp-ct-把手::after{content:"";position:absolute;top:50%;transform:translateY(-50%);
        width:2px;height:18px;border-radius:1px;background:transparent;transition:background .12s}
      .lvp-ct-把手.左::after{left:${把手px - 1}px}
      .lvp-ct-把手.右::after{right:${把手px - 1}px}
      .lvp-ct-卡:hover .lvp-ct-把手::after{background:var(--ct-line2)}
      @container (max-width:110px){.lvp-ct-对白{display:none}}
      @container (max-width:76px){.lvp-ct-标题{display:none}}
      @container (max-width:60px){.lvp-ct-区间:not(:focus-within){display:none}.lvp-ct-头:focus-within .lvp-ct-序,.lvp-ct-头:focus-within .lvp-ct-角色{display:none}}
      @container (max-width:44px){.lvp-ct-角色{display:none}.lvp-ct-词{-webkit-line-clamp:1}}
      @container (max-width:34px){.lvp-ct-把手{display:none}}
      /* min-width 按内容盒与窄卡档互补，避免高度查询覆盖窄卡的 2 行/1 行降级。 */
      @container (min-height:100px) and (min-width:111px){.lvp-ct-词{-webkit-line-clamp:4}}
      @container (min-height:140px) and (min-width:111px){.lvp-ct-词{-webkit-line-clamp:7}}
      @container (min-height:180px) and (min-width:111px){.lvp-ct-词{-webkit-line-clamp:10}}
      .lvp-ct.忙 .lvp-ct-把手,.lvp-ct.忙 .lvp-ct-时长入,.lvp-ct.忙 .lvp-ct-选,.lvp-ct.忙 .lvp-ct-开关{pointer-events:none;opacity:.45}`;
    document.head.appendChild(s);
    样式已注入.v = true;
}

// ctx（由 提示词时间轴页面板.js 注入，均为延迟求值 getter/回调）：取节点() / 状态 / 应用规划(segments) / 弹确认(标题,消息)
// 返回：{渲染, 刷active}
export function 创建剪辑时间轴(容器, ctx) {
    注入样式();
    const { 取节点, 状态, 应用规划, 弹确认 } = ctx;

    let 播放头 = 0;
    let 缩放 = 1, 视图节点 = null;
    let 视图起点 = 0;   // 视口左缘对应的「时间」＝横滚状态唯一真源；scrollLeft 只是它在当前内容宽上的投影（重建 DOM/改倍率都能复原）
    const 最大缩放 = 40;
    let 卷El = null, 缩放入 = null, 适配钮 = null, 缩小钮 = null, 放大钮 = null, 倍标 = null;
    let 选择集 = new Set();     // 多选索引集（Ctrl/Shift）
    let 拖 = null;               // 拖拽状态机 {型:"trim"|"移"|"scrub"|"平移",...}（参照 AIVideo_node this.drag）
    let 收平移 = null, 收scrub = null;
    let 显示总秒数 = 0, 待缩放 = null;
    const 缩放更新 = 创建帧更新(值 => { 待缩放 = null; 设缩放(值); });
    function 排缩放(值) {
        if (拖) return;
        待缩放 = Math.min(最大缩放, Math.max(1, 值));
        缩放更新.请求(待缩放);
    }
    let 忙 = false;              // I1：AI 生成提示词期间只冻结结构编辑（trim/重排/分割/增删/启用/时长/台词/填充），浏览类（滚动/缩放/平移/scrub/点选看卡）放行，批窗口内可即时查看已生成结果

    const 根 = document.createElement("div");
    根.className = "lvp-ct";
    容器.appendChild(根);

    // 模型由配置页按用途保存，技能固定为通用提示词改写。
    let 生成行El = null, b提示 = null, b填充 = null, 停止生成 = null, 停止中 = false;
    let 当前提示词任务 = null, 任务节点 = null, 待接回 = null;
    let b台词 = null;
    let 台词撤销 = null; // 仅在本次估时后的草稿仍完全相同时可撤销，不覆盖后续编辑。

    function 操作忙() { return 忙 || 取操作忙(状态); }
    状态.订阅(键 => {
        if (键 === "统一操作锁" || 键 === "LLM请求在途") {
            根.classList.toggle("忙", 操作忙());
            if (!忙) 渲染(); // 流式生成期间保留进度按钮与读取器，不能重建整棵树。
        }
    });

    function 读草稿() { const n = 取节点(); return n ? 真源.读剪辑草稿(n) : { brief: {}, segments: [] }; }
    function 写草稿(段组, 顶层补丁) {
        const n = 取节点(); if (!n || 操作忙()) return;
        const 草 = 读草稿();
        // NaN 守卫（P-3 同源）：进 JSON.stringify 前挡非法数值，防转 null 损坏后端 float 契约
        for (const s of 段组) {
            if (!Number.isFinite(s.start)) s.start = 0;
            if (!Number.isFinite(s.end)) s.end = s.start;
            if (!(s.end > s.start)) s.end = s.start + 最小时长;   // I5：挡负/零时长，防后端静默补 5s
            if (typeof s.台词 === "string") Object.assign(s, 保护台词提示词(s));
        }
        真源.写剪辑草稿(n, { ...草, ...顶层补丁, brief: 草.brief || {}, segments: 段组 });
    }
    function 段组() { return 读草稿().segments || []; }
    function 总时长Of(g) { return g && g.length ? (g[g.length - 1].end || 0) : 0; }
    function 显示段组() { return 拖?.型 === "trim" ? 拖.段组 : 段组(); }
    function 总时长() { return 拖?.型 === "trim" ? 总时长Of(拖.段组) : 显示总秒数; }
    function active() { return 状态.取("剪辑选中段") ?? 0; }   // 🔒 与节点时间轴的「选中段」解耦：剪辑草稿用独立键，两条链路互不触发（详 状态栏面板.回填 拆分）
    function 设active(i) { 状态.设("剪辑选中段", i); }

    let 卡片组 = [], 槽组 = [], 内 = null, 轨El = null, 播放头El = null, 播放hit = null, 概要El = null, 插入线 = null, 时间线El = null;
    let 渲染代 = 0;

    // ── 缩放视图：内容宽 = 视口宽 × 倍率，横向位置完全交给原生 scrollLeft（滚动条/横滑/时间线拖拽）──
    // 不缩放字形（无 scaleX/transform），只改 内 的宽，故文字始终清晰；坐标换算仍走 rect，
    //   所以 scrub/分割/trim/重排在任意倍率下天然正确（参照 OpenCut/CapCut 时间轴缩放与 d3-zoom 的 translateTo 锚点保持）。
    function 边宽() { return (轨El?.clientLeft || 0) * 2; }
    function 基宽() {
        const 宽 = 卷El?.clientWidth ?? 卷El?.getBoundingClientRect().width ?? 0;
        return Math.max(0, 宽 - 边宽());
    }
    function 内容宽(倍 = 缩放, 宽 = 基宽()) { return 宽 * 倍; }
    function 秒到内容px(秒, 总, 内容) { return 总 > 0 ? 秒 / 总 * 内容 : 0; }
    // 锚点＝绿色定位线「当前屏幕上」的位置（内容位置减横滚），故与倍率无关：放大缩小时定位线不动，向两边伸缩。
    // 用户已横滚到定位线之外时改锚视口中心，避免缩放把视图猛拉回定位线。
    // 按总＝该偏移成立所依据的总时长（改总时长后要用旧总时长反推「此刻屏幕上看到的时间」）。
    function 取锚(内容, 宽, 按总 = 总时长()) {
        const 线 = Math.min(播放头, 按总);
        const 偏移 = 秒到内容px(线, 按总, 内容) - (卷El ? 卷El.scrollLeft : 0);
        return (卷El && 偏移 >= 0 && 偏移 <= 宽)
            ? { 秒: 线, 偏移 }
            : { 秒: 按总 && 内容 > 0 ? (卷El.scrollLeft + 宽 / 2) / 内容 * 按总 : 0, 偏移: 宽 / 2 };
    }
    function 视口起点秒(内容, 总) { return 卷El && 内容 > 0 && 总 > 0 ? 卷El.scrollLeft / 内容 * 总 : 0; }
    function 记视口起点() { if (基宽() > 0) 视图起点 = 视口起点秒(内容宽(), 总时长()); }
    function 刷缩放视图() {
        const 总 = 总时长(), 宽 = 基宽(), 内容 = 内容宽(缩放, 宽);
        if (内 && 宽 > 0 && 内.style.width !== `${内容 + 边宽()}px`) 内.style.width = `${内容 + 边宽()}px`;
        if (卷El && 总 > 0 && 宽 > 0) {
            卷El.scrollLeft = 秒到内容px(视图起点, 总, 内容);   // 越界由浏览器夹取
            视图起点 = 视口起点秒(内容, 总);                     // 回读夹取值，防状态与 DOM 长期背离
        }
        if (!缩放入) return;
        const 倍文 = String(Number(缩放.toFixed(2)));
        缩放入.value = String(Math.log2(缩放));
        缩放入.title = `时间轴缩放 ${倍文} 倍`;
        缩放入.setAttribute("aria-valuetext", `${倍文} 倍`);
        if (倍标) 倍标.textContent = `${倍文}×`;
        const 禁用 = !总;   // 缩放是浏览动作，忙期不锁（I1 只锁结构编辑）
        缩放入.disabled = 适配钮.disabled = 禁用;
        缩小钮.disabled = 禁用 || 缩放 <= 1;
        放大钮.disabled = 禁用 || 缩放 >= 最大缩放;
    }
    function 设缩放(值, 适配 = false) {
        if (拖 || !总时长()) { 刷缩放视图(); return; }
        const 新值 = Math.min(最大缩放, Math.max(1, 值));
        if (!Number.isFinite(新值)) return;
        const 宽 = 基宽(), 总 = 总时长(), 新内容 = 内容宽(新值, 宽);
        // 适配＝回到 0s 全景；否则把「定位线此刻的屏幕位置」换算成新倍率下的视口左缘时间
        if (适配) 视图起点 = 0;
        else {
            const 锚 = 取锚(内容宽(缩放, 宽), 宽), 起 = 锚.秒 - 锚.偏移 / 新内容 * 总;
            视图起点 = Number.isFinite(起) ? Math.max(0, 起) : 0;   // 窄容器（新内容 0）时退回全景
        }
        缩放 = 新值;
        刷缩放视图();
        刷时间线();
    }
    function 建缩放控件() {
        const 组 = document.createElement("div"); 组.className = "lvp-ct-缩放";
        const 节点 = 取节点(), 代 = 渲染代;
        const 可操作 = () => 节点 && 取节点() === 节点 && 代 === 渲染代;
        const 建图标钮 = (名, 路径, 动作) => {
            const b = document.createElement("button");
            b.className = "lvp-ct-钮 lvp-ct-缩放钮"; b.type = "button"; b.title = b.ariaLabel = 名;
            const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
            svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true");
            const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
            path.setAttribute("d", 路径); svg.appendChild(path); b.appendChild(svg);
            b.onclick = () => { if (可操作()) { 缩放更新.刷新(); 动作(); } };
            return b;
        };
        // 图标只用大写字母（绝对坐标）命令：坐标可被测试逐项核对，杜绝相对位移画出 24×24 视口外的野笔画；
        // 描边取 currentColor，随工具行文字色＝跟随主题（不写死色值）。
        适配钮 = 建图标钮("适配全部", "M4 5V19M20 5V19M8 12H16M11 9L8 12L11 15M13 9L16 12L13 15", () => 设缩放(1, true));
        const 镜 = "M7 11A4 4 0 1 0 15 11A4 4 0 1 0 7 11M14 14L20 20M9 11H13";
        缩小钮 = 建图标钮("缩小", 镜, () => 设缩放(缩放 / Math.SQRT2));
        放大钮 = 建图标钮("放大", 镜 + "M11 9V13", () => 设缩放(缩放 * Math.SQRT2));
        const 入 = document.createElement("input"); 入.className = "lvp-ct-缩放入";
        入.type = "range"; 入.min = "0"; 入.max = String(Math.log2(最大缩放)); 入.step = "0.01";
        入.ariaLabel = "时间轴缩放";
        入.oninput = () => { if (可操作()) 排缩放(2 ** Number(入.value)); };
        缩放入 = 入;
        倍标 = document.createElement("span"); 倍标.className = "lvp-ct-倍"; 倍标.title = "当前时间轴缩放倍率";
        组.append(适配钮, 缩小钮, 入, 放大钮, 倍标);
        return 组;
    }

    // ── 局部刷新（承 时间轴面板.js：结构变才整树重建，态/比例/概要/预览就地刷） ──
    function 刷比例(g = 段组()) {
        const 总 = 总时长Of(g);
        显示总秒数 = 总;
        槽组.forEach((槽, i) => { 槽.style.flexGrow = String(总 > 0 ? 秒数(g[i]) / 总 * 100 : 1); });
        刷缩放视图();
        排时间线();   // 时长变 → 像素/秒 变 → 时间线刻度步长重算
    }
    function 刷播放头() {
        if (!播放头El) return;
        const px = 时间到X(Math.min(播放头, 总时长())) + "px";
        播放头El.style.left = px;
        if (播放hit) 播放hit.style.left = px;
    }
    // 时间线（轨道上方的连续时间标尺）：刻度步长按 像素/秒 在 1s→…→1min→… 间自适应——
    // 时间线被拉长（总时长小/容器宽）显示秒刻度，被压缩（总时长大/容器窄）递进到分钟刻度（对标 OpenCut/CapCut 标尺）。
    const 刻度步长 = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1200, 3600];
    const 空轨刻度秒 = 30;   // 0 段空草稿的刻度保底跨度：空轴也常显 0–30s 连续刻度（2026-09-24 用户订正「保持剪辑时间轴刻度」）
    function 时刻文本(t, 步长) {
        if (步长 < 60) return `${Number(t.toFixed(6))}s`;
        const m = Math.floor(t / 60), s = Math.round(t % 60);
        return `${m}:${String(s).padStart(2, "0")}`;
    }
    function 刷时间线() {
        if (时间线raf) { cancelAnimationFrame(时间线raf); 时间线raf = 0; }
        刷播放头();
        if (!时间线El) return;
        let 总 = 总时长();
        const 几何 = 时间几何(), 宽 = 几何.width;
        if (!宽) return;
        if (总 <= 0) 总 = 空轨刻度秒;   // 0 段常显刻度：不按段组总时长早退
        const 最小步 = 总 / Math.max(1, 宽 / 48);
        const 步长 = 刻度步长.find((s) => s >= 最小步) ?? 最小步;
        const 视口 = 卷El.getBoundingClientRect();
        const 首 = Math.max(0, Math.floor((视口.left - 几何.left) / 宽 * 总 / 步长));
        const 末 = Math.min(Math.floor(总 / 步长 + 1e-9), Math.ceil((视口.right - 几何.left) / 宽 * 总 / 步长));
        const 偏移 = 几何.left - 内left();
        const 签名 = `${总}/${宽}/${偏移}/${步长}/${首}/${末}`;
        if (签名 === 刻度签名) return;
        const 新刻度 = new Map();
        for (let k = 首; k <= 末; k++) {
            const t = k * 步长;
            const 键 = `${步长}/${k}/${Math.abs(t - 总) < 1e-6}`;
            let 格 = 刻度节点.get(键);
            if (!格) {
                格 = document.createElement("div");
                格.className = "lvp-ct-时刻";
                格.textContent = 时刻文本(t, 步长);
                if (Math.abs(t - 总) < 1e-6) {
                    const 标签 = document.createElement("span"); 标签.textContent = 格.textContent;
                    标签.style.display = "inline-block"; 标签.style.transform = "translateX(-100%)";
                    格.style.paddingLeft = "0"; 格.replaceChildren(标签);
                }
            }
            格.style.left = `${偏移 + t / 总 * 宽}px`;
            新刻度.set(键, 格);
        }
        const 旧组 = [...刻度节点.values()], 新组 = [...新刻度.values()];
        if (旧组.length !== 新组.length || 新组.some((格, i) => 格 !== 旧组[i])) 时间线El.replaceChildren(...新组);
        刻度节点 = 新刻度; 刻度签名 = 签名;
    }
    let 刻度节点 = new Map(), 刻度签名 = "";
    let 时间线raf = 0;
    function 排时间线() {
        if (时间线raf) return;
        时间线raf = requestAnimationFrame(() => { 时间线raf = 0; 刷时间线(); });
    }
    function 刷概要(g = 段组()) {
        if (!概要El) return;
        const 跑 = g.filter((s) => s.run).length;
        概要El.textContent = g.length ? `共 ${g.length} 段 · 运行 ${跑} · ${一位(总时长Of(g))}s · 选 ${选择集.size}` : "";
    }
    function 刷态() {
        const g = 段组(); const a = active();
        卡片组.forEach((卡, i) => {
            卡.classList.toggle("选中", i === a);
            卡.classList.toggle("多选", 选择集.has(i) && i !== a);
            卡.classList.toggle("停", !g[i]?.run);
            卡.classList.toggle("禁", g[i]?.启用 === false);
            if (g[i]?.职能色) 卡.style.setProperty("--rolec", g[i].职能色); else 卡.style.removeProperty("--rolec");   // 同步职能色左边框（对标旧 时间轴面板.刷卡）：刷active 局部刷新即更新 --rolec，避免整树重建缩略图闪烁
        });
        刷概要();
    }
    function 刷active() { 刷态(); 刷播放头(); }
    function 刷区间(g = 显示段组(), 保留输入 = null) {
        卡片组.forEach((卡, k) => {
            const 入 = 卡.querySelector(".lvp-ct-时长入");
            if (!入 || !g[k]) return;
            if (入 !== 保留输入) 入.value = 时长文本(秒数(g[k]));
            入.style.width = `${Math.max(3, Math.min(10, 入.value.length + 0.5))}ch`;
            卡.title = `段${k + 1} · ${g[k].task || "t2v"} · ${一位(g[k].start)}–${一位(g[k].end)}s`;
        });
    }

    function 建时长输入(s, i) {
        const 区 = document.createElement("span"); 区.className = "lvp-ct-区间";
        const 入 = document.createElement("input"); 入.className = "lvp-ct-时长入";
        入.type = "text"; 入.inputMode = "decimal"; 入.value = 时长文本(秒数(s));
        入.ariaLabel = `第${i + 1}段时长（秒）`;
        入.title = `点击输入时长；回车或失焦提交，Esc取消；支持小数，范围${最小时长}–${最大输入时长}秒`;
        入.disabled = 操作忙();
        const 单位 = document.createElement("span"); 单位.textContent = "s";
        区.append(入, 单位);
        const 节点 = 取节点(), 代 = 渲染代;
        let 取消 = false;
        const 可编辑 = () => !操作忙() && 节点 && 取节点() === 节点 && 代 === 渲染代;
        const 取输入时长 = () => {
            const 文 = 入.value.trim();
            return /^(?:\d+(?:\.\d+)?|\.\d+)$/.test(文) ? Number(文) : NaN;
        };
        const 更新 = (d) => {
            if (!可编辑() || !有效输入时长(d)) return false;
            const g = 段组(); if (!g[i]) return false;
            const 新末 = g[i].start + d, 差 = 新末 - g[i].end;
            if (差 === 0) return true;
            g[i].end = 新末;
            for (let k = i + 1; k < g.length; k++) {
                g[k].start = Number((g[k].start + 差).toFixed(9));
                g[k].end = Number((g[k].end + 差).toFixed(9));
            }
            if (!g.every(x => Number.isFinite(x.start) && Number.isFinite(x.end) && x.end > x.start)) return false;
            写草稿(g);
            播放头 = Math.min(播放头, 总时长Of(g));
            刷比例(g); 刷区间(g, 入); 刷概要(g); 刷播放头();
            return true;
        };
        入.addEventListener("pointerdown", e => e.stopPropagation());
        入.onfocus = () => { 取消 = false; };
        入.oninput = () => {
            if (!可编辑()) return;
            const d = 取输入时长();
            const 有效 = 有效输入时长(d);
            入.ariaInvalid = String(!有效);
            入.setCustomValidity(有效 ? "" : `请输入${最小时长}–${最大输入时长}之间的完整秒数`);
        };
        入.onblur = () => {
            if (!可编辑()) return;
            if (!取消) 更新(取输入时长());
            入.value = 时长文本(秒数(段组()[i]));
            入.ariaInvalid = "false"; 入.setCustomValidity("");
            刷区间();
        };
        入.onkeydown = e => {
            e.stopPropagation();
            if (e.key === "Escape") { e.preventDefault(); 取消 = true; 入.blur(); }
            else if (e.key === "Enter") { e.preventDefault(); 入.blur(); }
        };
        入.onkeyup = e => e.stopPropagation();
        return 区;
    }

    // 前导 emoji 单独收进 .lvp-ct-图（字号压小、行盒锁 1）：表情字体（Segoe UI Emoji）默认行盒比
    // 中文字体高，会让 ✨/🔁/⬆ 三颗按钮比 分割/删除 胖一圈。span + 余文两个节点拼出的
    // textContent 与传入字符串逐字节一致，按按钮文字断言的测试不受影响。
    const 前导emoji = /^([\u2190-\u2BFF\uFE0F\u{1F000}-\u{1FAFF}]+)(\s+)([\s\S]*)$/u;
    function 建钮(文本, 类名, 提示, fn) {
        const b = document.createElement("button");
        b.className = "lvp-ct-钮" + (类名 ? " " + 类名 : "");
        b.type = "button"; b.title = 提示; b.onclick = fn;
        const m = 前导emoji.exec(文本);
        if (m) {
            const 图 = document.createElement("span");
            图.className = "lvp-ct-图"; 图.textContent = m[1];
            b.append(图, m[2] + m[3]);
        } else {
            b.textContent = 文本;
        }
        return b;
    }

    // 生成按钮只建一次，重绘时间轴时保留按钮状态。
    function 建生成行() {
        if (生成行El) return 生成行El;
        const 生成 = document.createElement("div"); 生成.className = "lvp-ct-行";
        b提示 = 建钮("✨ AI生成提示词", "主", "逐段优化启用段的已有提示词，每次一段；仅用主题、当前目标和本段资料，生成后立即回写", (e) => 停止生成 ? 停止生成() : 生成提示词(e.currentTarget));
        b填充 = 建钮("⬆ 填充节点", "", "把启用草稿段一键填充到节点时间轴（覆盖确认后写「时间轴数据」用于生成）；非全启用时仅填充启用段并闭拢时间，全部启用时填充所有段", 填充节点);
        生成.append(b提示, b填充);
        生成行El = 生成;
        return 生成行El;
    }

    // ── 指针交互 ──
    // I6：时间坐标只由轨道内容宽度和总时长决定；卡片 padding/gap 不参与秒数映射。
    function 卡rects() { return 卡片组.map((c) => c.getBoundingClientRect()); }
    function 内left() { return 内 ? 内.getBoundingClientRect().left : 0; }
    function 时间几何() {
        const r = 轨El?.getBoundingClientRect();
        const 边 = 轨El?.clientLeft || 0;
        return { left: (r?.left || 0) + 边, width: Math.max(0, (r?.width || 0) - 边 * 2) };
    }
    function x到时间(cx) {          // clientX → 时间
        const r = 时间几何();
        return r.width > 0 ? Math.min(1, Math.max(0, (cx - r.left) / r.width)) * 总时长() : 0;
    }
    function x到插入位(cx, rs) {        // clientX → 拖移插入位（0..n），以卡片中点为界
        for (let i = 0; i < rs.length; i++) { const r = rs[i]; if (cx < (r.left + r.right) / 2) return i; }
        return rs.length;
    }
    function 时间到X(t, 按总 = 总时长()) {   // 时间 → 相对「内」的 px（播放头/连续刻度定位；口径＝显示段组，trim 拖拽预览中跟预览值；刷时间线 传 按总 以支持 0 段保底跨度）
        const r = 时间几何();
        return r.left - 内left() + (按总 > 0 ? Math.min(1, Math.max(0, t / 按总)) * r.width : 0);
    }
    function 画插入线(目标, rs) {
        if (!插入线 || !内) return;
        let px = 0;
        if (rs.length) px = 目标 >= rs.length ? rs[rs.length - 1].right - 内left() : rs[目标].left - 内left();
        插入线.style.left = px + "px";
        插入线.style.display = "block";
    }

    function 起trim(e, i, 边) {
        if (操作忙() || e.button !== 0) return;
        缩放更新.刷新();
        e.stopPropagation(); e.preventDefault();
        const g = 段组(); const rect = 时间几何();
        拖 = { 型: "trim", i, 边, startX: e.clientX, 内宽: rect.width, 总时长: 总时长(),
               原边界: 边 === "右" ? g[i].end : g[i].start, 段组: g, 改: false };
        window.addEventListener("pointermove", 排trim);
        window.addEventListener("pointerup", 收trim, { once: true });
        window.addEventListener("pointercancel", 收trim, { once: true });   // I3
    }
    function 移trim(e) {
        if (!拖 || 拖.型 !== "trim") return;
        const g = 拖.段组; const i = 拖.i;
        const dt = 拖.总时长 * (e.clientX - 拖.startX) / (拖.内宽 || 1);
        let t = 吸附(拖.原边界 + dt);
        if (拖.边 === "右") {
            const lo = g[i].start + 最小时长;
            const hi = i < g.length - 1 ? g[i + 1].end - 最小时长 : Infinity;   // rolling：补偿下一段 start
            if (hi < lo) return;                                              // I5：相邻两段合跨度不足，拒绝本次移动（防 end<start）
            t = Math.min(hi, Math.max(lo, t));
            if (g[i].end === t) return;
            g[i].end = t; if (i < g.length - 1) g[i + 1].start = t;
        } else {
            const hi = g[i].end - 最小时长;
            const lo = i > 0 ? g[i - 1].start + 最小时长 : 0;                    // 首段左缘锁 0
            if (hi < lo) return;                                              // I5：同上
            t = Math.min(hi, Math.max(lo, t));
            if (g[i].start === t) return;
            g[i].start = t; if (i > 0) g[i - 1].end = t;
        }
        拖.改 ||= t !== 拖.原边界;
        播放头 = Math.min(播放头, 总时长Of(g));
        刷比例(g); 刷区间(g); 刷概要(g); 刷时间线();
    }
    function 收trim() {
        裁剪更新.刷新();
        window.removeEventListener("pointermove", 排trim);
        window.removeEventListener("pointerup", 收trim);
        window.removeEventListener("pointercancel", 收trim);
        if (拖?.型 === "trim" && 拖.改) { 写草稿(拖.段组); 渲染(); }
        拖 = null;
    }
    const 裁剪更新 = 创建帧更新(移trim);
    const 排trim = e => 裁剪更新.请求({ clientX: e.clientX });

    function 起卡(e, i) {
        if (e.button !== 0) return;
        缩放更新.刷新();
        e.stopPropagation(); e.preventDefault();   // 阻止拖动时的原生文字选择
        const rect = 内.getBoundingClientRect();
        // 选择语义：Ctrl/Cmd 切换、Shift 连选、普通单选（并置 active）
        if (e.ctrlKey || e.metaKey) { if (选择集.has(i)) 选择集.delete(i); else 选择集.add(i); 设active(i); }
        else if (e.shiftKey) { const a = active(); const lo = Math.min(a, i), hi = Math.max(a, i); 选择集 = new Set(); for (let k = lo; k <= hi; k++) 选择集.add(k); }
        else { 选择集 = new Set([i]); 设active(i); }
        刷active();
        if (操作忙()) return;   // I1：忙期点选查看放行（只改 UI 选中态，不写草稿），重排拖拽禁止
        拖 = { 型: "移", i, startX: e.clientX, 内宽: rect.width, 总时长: 总时长(), 移动: false, 目标: null };
        window.addEventListener("pointermove", 排移卡);
        window.addEventListener("pointerup", 收卡, { once: true });
        window.addEventListener("pointercancel", 收卡, { once: true });   // I3
    }
    function 移卡(e) {
        if (!拖 || 拖.型 !== "移") return;
        if (!拖.移动 && Math.abs(e.clientX - 拖.startX) < 4) return;   // 阈值内视作点击，不进入拖移
        拖.移动 = true;
        const rs = 卡rects();
        拖.目标 = x到插入位(e.clientX, rs);
        画插入线(拖.目标, rs);
    }
    function 收卡() {
        移卡更新.刷新();
        window.removeEventListener("pointermove", 排移卡);
        window.removeEventListener("pointerup", 收卡);
        window.removeEventListener("pointercancel", 收卡);
        if (拖?.型 === "移" && 拖.移动 && 拖.目标 != null) {
            const g = 段组();
            const 选中 = [...(选择集.size ? 选择集 : new Set([拖.i]))].sort((a, b) => a - b);
            const 首段 = g[选中[0]];              // 移块/重排时间 均保引用，故可按身份回查新位
            const 新组 = 重排时间(移块(g, 选中, 拖.目标));
            写草稿(新组);
            const 新位 = 新组.indexOf(首段);
            选择集 = new Set(新位 >= 0 ? [新位] : []);
            if (新位 >= 0) 设active(新位);
            渲染();
        }
        if (插入线) 插入线.style.display = "none";
        拖 = null;
    }
    const 移卡更新 = 创建帧更新(移卡);
    const 排移卡 = e => 移卡更新.请求({ clientX: e.clientX });

    function 起scrub(e) {
        if (e.button !== 0) return;   // 播放头是浏览态，忙期放行
        缩放更新.刷新();
        收scrub?.();
        e.stopPropagation(); e.preventDefault();
        const rect = 内.getBoundingClientRect();
        拖 = { 型: "scrub", 内宽: rect.width, 总时长: 总时长(), left: rect.left };
        const mv = (ev) => {
            if (!拖 || 拖.型 !== "scrub") return;
            播放头 = Math.min(拖.总时长, Math.max(0, x到时间(ev.clientX)));
            刷播放头();
        };
        const scrub更新 = 创建帧更新(mv);
        const 排scrub = ev => scrub更新.请求({ clientX: ev.clientX });
        const up = () => {
            scrub更新.刷新();
            window.removeEventListener("pointermove", 排scrub);
            window.removeEventListener("pointerup", up);
            window.removeEventListener("pointercancel", up);
            拖 = null; 收scrub = null;
        };
        收scrub = up;
        window.addEventListener("pointermove", 排scrub);
        window.addEventListener("pointerup", up, { once: true });
        window.addEventListener("pointercancel", up, { once: true });   // I3
        mv(e);   // 点击即跳转
    }

    // 标尺（连续时间刻度那条）拖拽＝横向平移视口：放大后看不到两端的段时，除了滚动条还能像剪辑器那样拖着看。
    function 起平移(e) {
        if (拖 || e.button !== 0 || !卷El || !总时长()) return;   // 平移是浏览动作，忙期放行（请求发起时入口已 收平移?.() 取消在途拖拽）
        缩放更新.刷新();
        e.preventDefault();
        const 卷 = 卷El, 线 = 时间线El, 节点 = 取节点(), 代 = 渲染代;
        const 起点 = e.clientX, 起始 = 卷.scrollLeft;
        const 本次 = 拖 = { 型: "平移" };
        线.classList.add("拖中");
        const 平移更新 = 创建帧更新(x => {
            if (拖 !== 本次 || 取节点() !== 节点 || 渲染代 !== 代) { 收(); return; }
            卷.scrollLeft = 起始 - (x - 起点);
            记视口起点(); 刷时间线();
        });
        const 移 = ev => 平移更新.请求(ev.clientX);
        const 收 = () => {
            平移更新.刷新();
            线.classList.remove("拖中");
            window.removeEventListener("pointermove", 移);
            window.removeEventListener("pointerup", 收);
            window.removeEventListener("pointercancel", 收);
            if (拖 === 本次) 拖 = null;
            if (收平移 === 收) 收平移 = null;
        };
        收平移 = 收;
        window.addEventListener("pointermove", 移);
        window.addEventListener("pointerup", 收, { once: true });
        window.addEventListener("pointercancel", 收, { once: true });
    }

    // 滚轮缩放（参照 CapCut：时间轴上滚轮＝缩放）；触控板横滑（deltaX 为主）不截留，交给原生滚动条平移。
    function 滚轮缩放(e) {
        if (拖?.型 === "平移") { e.preventDefault(); return; }
        if (拖 || !总时长()) return;   // 滚轮缩放是浏览动作，忙期放行
        if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) return;
        e.preventDefault();
        排缩放((待缩放 ?? 缩放) * 2 ** (-e.deltaY * (e.ctrlKey ? 0.01 : 0.0025)));
    }

    // ── 工具动作（一律现读 段组()，写草稿后整树重建） ──
    async function 分割() {
        if (操作忙()) return;
        const g = 段组(); const 总 = 总时长();
        const p = 吸附(Math.min(总, Math.max(0, 播放头)));   // I4：分割点吸附 0.5s 网格
        const i = g.findIndex((s) => p - s.start >= 最小时长 && s.end - p >= 最小时长);
        if (i < 0) { if (g.length) await 弹确认("无法分割", "分割点需距所在段两端各 ≥0.5s。"); return; }
        const s = g[i];
        if (s.配音计时 || s.refs?.台词配音) {
            await 弹确认("请按配音句界拆段", "此段已有配音切片。请在「台词估时」导入句级时间戳后预览重排，避免手动分割重复整段配音。");
            return;
        }
        // 分割产生两个新实体：必须各自铸一个全新 segment_id（A3）。
        //   不能沿用父段 id：展开 {...s} 会把父 id 复制给两半（重复），故显式重赋两个不同新 id。
        const 左 = { ...s, end: p, refs: 深拷refs(s.refs), segment_id: 新段ID() };
        const 右 = { ...s, start: p, refs: 深拷refs(s.refs), segment_id: 新段ID() };
        let 子段;
        try { 子段 = 分配中间帧(s, [左, 右]); }
        catch (e) { await 弹确认("无法分割", e.message); return; }
        g.splice(i, 1, ...子段);
        写草稿(g); 选择集 = new Set([i + 1]); 设active(i + 1); 渲染();
    }
    // 手动新建：不经「生成规划」也能直接在时间轴上补一段空白段供编辑（参照 时间轴面板.js 的「＋新增段」）。
    // 末尾追加 5s（与节点侧同参，且兑住后端 I5 的静默补 5s）；全新实体须铸 segment_id（A3）供拖动/分割/保存往返保持身份。
    function 新建() {
        if (操作忙() || !取节点()) return;   // 未绑定节点时写入是空操作（写草稿 内 !n 直接 return），与 生成提示词 同套节点守卫
        const g = 段组();
        const 末 = g.length ? g[g.length - 1].end : 0;
        g.push({ task: "t2v", prompt: "", start: 末, end: 末 + 5, run: true, 启用: true, segment_id: 新段ID() });
        写草稿(g); 选择集 = new Set([g.length - 1]); 设active(g.length - 1); 渲染();
    }
    function 删除() {
        if (操作忙()) return;
        const g = 段组();
        const idx = [...(选择集.size ? 选择集 : new Set([active()]))].sort((a, b) => b - a);
        idx.forEach((i) => g.splice(i, 1));
        重排时间(g);   // ripple 闭拢
        写草稿(g); 选择集 = new Set(); 设active(Math.max(0, Math.min(active(), g.length - 1))); 渲染();
    }
    // 启用管理（item2）：影响「AI生成提示词」覆盖范围与「填充节点」的填充范围，与节点侧视频生成的 run 开关无关。
    // 触发方式承旧「运行/停」：选中（或多选）后点击切换；未显式置 false 的段一律视为启用（兼容旧草稿无该字段）。
    const 是启用 = (s) => s?.启用 !== false;
    function 切启用() {
        if (操作忙()) return;
        const g = 段组();
        const idx = [...(选择集.size ? 选择集 : new Set([active()]))];
        const 目标 = !idx.every((i) => 是启用(g[i]));   // 有任一未启用 → 全启用；否则全不启用
        idx.forEach((i) => { if (g[i]) g[i].启用 = 目标; });
        写草稿(g); 渲染();
    }
    function 全选() {
        if (操作忙()) return;
        const g = 段组();
        选择集 = new Set(g.map((_, i) => i));
        刷态();
    }
    // 提示词生成（A6 批级 SSE＝唯一 LLM 入口 POST /lvp/plan/prompts/stream）：
    //   全部启用 → body 不带 目标段ids；非全启用 → 带 启用段id清单（A2 定位语义不变，全部段仅供本地定位，
    //   模型不接收邻段）。服务端始终逐段处理，改写及审查不传前段成稿，
    //   每批完成即推 batch 事件；前端现读真源、按 segment_id 增量写回草稿，批内降级段保留原画面草稿。
    //   整合局部重试原设计：文档/规格/2026-09-21-AI生成提示词整合局部重试-设计.md
    //   分批流式方案：文档/计划/2026-09-28-提示词生成分批流式-实现计划.md
    // B4 批内回显：流式期间不能调 渲染()（根.replaceChildren 会重建 DOM，摘掉正显示 k/N 进度的按钮），
    //   故按 segment_id 定位卡片、只改 .lvp-ct-词 文本。忙期结构编辑面冻结（无增删/重排），卡片下标与 段组() 同序。
    function 刷段卡验收(卡, 段) {
        if (!卡) return;
        const 报告 = 段?.提示词生成;
        let 标签 = 卡.querySelector?.(".lvp-ct-验收");
        if (typeof 报告?.完成 !== "boolean") { 标签?.remove(); return; }
        if (!标签) {
            标签 = document.createElement("div"); 标签.className = "lvp-ct-验收";
            卡.insertBefore(标签, 卡.querySelector?.(".lvp-ct-词"));
        }
        标签.textContent = 报告.完成 ? "已生成" : "生成失败 · 保留原稿";
        标签.title = 报告.完成 ? "本段已直接生成并更新提示词" : (报告.问题 || []).join("；");
        标签.style.color = 报告.完成 ? "#78cf9c" : "#f1b66a";
    }

    function 刷段卡提示词(新词表) {
        新词表.forEach((词, id) => {
            const i = 段组().findIndex((seg) => String(seg?.segment_id ?? "") === id);
            const 词El = i >= 0 ? 卡片组[i]?.querySelector?.(".lvp-ct-词") : null;
            if (词El) 词El.textContent = 词.trim() || "（未填提示词）";
            if (i >= 0) 刷段卡验收(卡片组[i], 段组()[i]);
        });
    }

    async function 生成提示词(钮, 恢复 = null) {
        if (操作忙()) return;
        if (取操作忙(状态)) { await 弹确认("另一项 AI 请求进行中", "请等待当前 AI 请求完成后再发起。"); return; }
        const n = 取节点(); if (!n || 操作忙()) return;
        const 草 = 读草稿(); const g = 草.segments || [];
        if (!g.length) { await 弹确认("无草稿段", "请先「生成规划」得到草稿段。"); return; }
        // item2：仅对「启用」段跑 AI；未启用段保持原 prompt 不动
        const 启用idx = [];
        g.forEach((s, i) => { if (是启用(s)) 启用idx.push(i); });
        if (!启用idx.length) { await 弹确认("无启用段", "所有段均未启用，请选中需要的段后点击「启用」，或先「全选」再点击「启用」。"); return; }
        // 旧草稿缺 id 的段：发起前补齐（分配段ID 幂等只补缺）并落盘——重试契约的目标定位不再弹窗拦截
        if (g.some((s) => s && (typeof s.segment_id !== "string" || !s.segment_id))) {
            分配段ID(g);
            // 补齐定位ID不是内容编辑，不触发台词保护改写；失败时原提示词必须保持原样。
            真源.写剪辑草稿(n, { ...草, segments: g }, { 记录历史: false });
        }
        const 提醒 = 规划结果提示(草.规划资料);
        if (!恢复 && 提醒.待完善) await 弹确认("规划尚有待完善项", `${提醒.说明 || "请检查人物、台词和素材是否定稿。"}\n本次仅处理当前启用段，未解决的剧情或来源问题请回 AI规划完善。`);
        if (取节点() !== n || 操作忙() || JSON.stringify(读草稿()) !== JSON.stringify(草)) return;
        const 全启用 = 启用idx.length === g.length;
        const 目标ids = 全启用 ? [] : 启用idx.map((i) => String(g[i].segment_id));
        // 禁用字幕仅约束生成画面的屏上文字，不影响台词和声音计划。
        const 禁用字幕 = 草.禁用字幕 === true;
        const 上传段 = (段) => {
            if (!禁用字幕) return 段;
            const { 台词时长提示: _删, ...其余 } = 段 || {};
            if (typeof _删 === "string" && _删) {
                其余.prompt = String(其余.prompt || "").replaceAll(_删, "");
            }
            return 其余;
        };
        const 待改写 = ctx.取填充段?.(g, 草) || g;
        const body = {
            brief: 草.brief || {}, segments: 待改写.map(上传段),
            风格技能: "通用提示词改写", 禁用字幕,
            改写资料: 取H3改写资料(草, n),
        };
        if (!全启用) body.目标段ids = 目标ids;
        写节点属性(n, "提示词任务缓存", 恢复 || 新提示词任务(body, n.properties.剪辑草稿));
        const 缓存 = n.properties.提示词任务缓存;
        任务节点 = n;
        使节点快照失效(n);
        收平移?.();
        忙 = true; 根.classList.add("忙");   // I1：冻结结构编辑面（批窗口内增删/重排/时长等一律被守卫拒绝，按批增量写回安全）；浏览类交互放行，批结果可即时查看
        状态.设("LLM请求在途", true);   // B3：跨入口互斥旗标（生成规划/应用规划/加载计划据此早退）
        b填充.disabled = true;
        const 原内容 = [...钮.childNodes];
        const 编辑批次 = 缓存.id;
        let 已收批 = 0, 降级数 = 缓存.降级数 || 0, 落地过 = !!缓存.已完成.length, 致命 = null, 结束事件 = null;
        const 完成目标 = new Set(缓存.已完成);
        const 生成问题 = [];
        // 目标段集＝本单允许改写的段：批事件只带目标段，但前端仍按清单过滤——
        //   非目标段（如未启用的段）即使出现在响应里也不落盘，承旧「响应篡改禁用段 prompt 不生效」锁。
        const 目标集 = new Set(全启用 ? g.map((s) => String(s.segment_id)) : 目标ids);
        // 每批保护原节点和草稿版本；切换界面只断开连接，实际修改草稿才拒绝写回。
        let 基线 = 捕获节点快照(n);
        const 写批次 = (段批, 批状态) => {
            const 现 = 取节点();
            if (现 !== n) throw Object.assign(new Error("界面已切换，后台继续生成"), { 断开: true });
            if (!基线 || n.properties.提示词任务缓存 !== 缓存) return false;
            // 换绑只改变界面；草稿值、对象身份和写入版本仍必须与上一批一致。
            基线.代数 = 捕获节点快照(n)?.代数;
            let 落地 = false;
            const 新词表 = new Map();   // B4：本批真正落盘的 id→新词，提交成功后就地刷段卡
            const 已提交 = 提交节点快照(基线, 现, (目标) => {
                const 草现 = 真源.读剪辑草稿(目标);
                const 按ID = new Map();
                (段批 || []).forEach((s) => {
                    const id = s?.segment_id;
                    if (id != null && 目标集.has(String(id))) 按ID.set(String(id), s);
                });
                (草现.segments || []).forEach((seg) => {
                    const id = seg.segment_id != null ? String(seg.segment_id) : null;
                    if (id == null || !按ID.has(id)) return;   // 非本批段不动
                    const 新词 = 按ID.get(id)?.prompt;
                    const 新段 = 按ID.get(id);
                    if (批状态[id] === "degraded" || 新段?.提示词生成?.完成 === false || typeof 新词 !== "string" || !新词.trim()) {
                        写入提示词生成结果(seg, 新段);
                        生成问题.push(`${seg.标题 || id}：${(新段?.提示词生成?.问题 || ["未返回完整提示词"]).join("；")}`);
                        新词表.set(id, seg.prompt || "");
                        降级数++; return;
                    }
                    if (!写入提示词生成结果(seg, 新段)) seg.prompt = 新词;
                    新词表.set(id, seg.prompt);
                });
                真源.写剪辑草稿(目标, 草现, { 编辑批次, 记录历史: !恢复?.已完成.length });
                落地 = true;
            });
            if (!已提交 || !落地) return false;
            刷段卡提示词(新词表);   // B4：批落地即回显，不等整单结束（用户能看见进度落在哪段）
            const 新基线 = 捕获节点快照(现);
            基线 = 新基线;
            缓存.原稿签名 = n.properties.剪辑草稿;
            缓存.降级数 = 降级数;
            落地过 = true;
            ctx.回填当前段?.();
            return true;
        };
        let 用户停止 = false;
        停止中 = false;
        const 处理事件 = (名, 数据) => {
            if (取节点() !== n) throw Object.assign(new Error("界面已切换，后台继续生成"), { 断开: true });
            if (名 === "reconnecting") {
                钮.title = 数据.阶段;
            } else if (名 === "progress") {
                if (!停止中) 钮.title = `点击停止生成 · ${数据.批次}/${数据.总批数} 段 · ${数据.阶段} · 调用 ${数据.调用}`;
            } else if (名 === "batch") {
                const 本批 = (数据.segments || []).filter(s => 目标集.has(String(s?.segment_id)) && !完成目标.has(String(s.segment_id)));
                if (!本批.length) return;
                已收批 += 1;
                if (!写批次(本批, 数据.promptStatus || {})) {
                    致命 = `节点或草稿已变化，第 ${已收批} 段起结果被丢弃${落地过 ? `，前 ${已收批 - 1} 段已保留` : ""}，请重试`;
                } else {
                    本批.forEach(s => 完成目标.add(String(s.segment_id)));
                    缓存.已完成 = [...完成目标];
                    if (!停止中) 钮.title = `点击停止生成 · 已处理 ${完成目标.size}/${目标集.size} 段`;
                }
            } else if (名 === "fatal") {
                const 类 = 数据?.category;
                const 建议 = ["network", "deadline", "server", "rate_limited", "busy"].includes(类) ? "连接或服务未完成；未完成段保留原文，请检查连接后再次生成。" : 类 === "auth" || 类 === "config" ? "请检查时间轴模型配置及凭据。" : 类 === "parse" ? "模型响应格式无效；本段保留原文，请再次生成。" : "";
                致命 = (落地过 ? `已有 ${完成目标.size} 段结果保留。` : "") + (数据?.error || "提示词生成失败") + (建议 ? `\n${建议}` : "") + (数据?.requestId ? `\n请求编号：${数据.requestId}` : "");
            } else if (名 === "done") {
                结束事件 = 数据;
            }
            // 已写回批次保留；结束事件与目标覆盖共同确认完整结束。
            if (致命 && 名 === "batch") throw Object.assign(new Error(致命), { 内容变化: true });
        };
        const 客户端 = 创建提示词任务客户端({ 任务: 缓存, 更新: 处理事件 });
        当前提示词任务 = 客户端;
        let 取消请求 = null;
        停止生成 = () => {
            if (停止中) return;
            用户停止 = 停止中 = true;
            b提示.disabled = true;
            b提示.title = "正在停止，已完成结果保留";
            取消请求 = 客户端.停止();
            取消请求.catch(() => {});
        };
        b提示.textContent = "停止生成"; b提示.title = "保留已完成段，停止后续处理"; b提示.disabled = false;
        try {
            await 客户端.运行();
            if (致命) throw new Error(致命);
            if (用户停止) throw new Error("已停止本次生成");
            if (!结束事件 || 完成目标.size !== 目标集.size || 结束事件.stopped) throw new Error(`任务未完整结束：已处理 ${完成目标.size} 段，剩余 ${目标集.size - 完成目标.size} 段未处理；已有结果保留，请处理剩余段。`);
            if (!完成目标.size) throw new Error("流式响应未包含任何批次，未修改草稿，请重试");
            // fix18a4：提示词已写回草稿，重发「剪辑选中段」订阅 → 状态栏面板.回填规划页() 按新草稿
            //   active 段回填右列（标题/台词/提示词），否则右列仍显示生成前的旧 prompt。
            //   与「生成规划」重置为 0 不同：此处保持当前 active 不变（用户可能正查看某一段）；
            //   状态桥.设 无同值短路，重发即可触发回填。
            状态.设("剪辑选中段", active());
            if (降级数) await 弹确认("部分提示词未更新",
                `${降级数} 段生成失败，已保留原文。${生成问题.length ? "\n" + 生成问题.join("\n") : ""}`);
            写节点属性(n, "提示词任务缓存", undefined);
        } catch (e) {
            if (!e.断开) {
                let 停止错误 = "";
                try { await (取消请求 || 客户端.停止()); } catch (err) { 停止错误 = `\n${err.message}`; }
                if (!停止错误) 写节点属性(n, "提示词任务缓存", undefined);
                if (取节点() === n) await 弹确认(用户停止 ? "已停止本次生成" : "AI生成提示词失败",
                    (用户停止 ? `已处理 ${完成目标.size} 段，剩余 ${目标集.size - 完成目标.size} 段未处理，已有结果及原稿保留。` : e.message || "生成失败") + 停止错误);
            }
        } finally {
            客户端.断开();
            当前提示词任务 = null; 任务节点 = null;
            停止生成 = null; 停止中 = false;
            忙 = false; 根.classList.remove("忙");
            钮.replaceChildren(...原内容);
            状态.设("LLM请求在途", false);
            渲染();
        }
    }

    function 切换编辑历史(前进 = false) {
        if (操作忙()) return;
        const n = 取节点(), 取记录 = 前进 ? 取下次编辑 : 取上次编辑;
        const 当前历史 = 前进 ? "草稿前进历史" : "草稿编辑历史";
        const 返回历史 = 前进 ? "草稿编辑历史" : "草稿前进历史";
        const 操作名 = 前进 ? "下一步" : "上一步";
        if (!n || !取记录(n)) return;
        const 快照 = 捕获节点快照(n);
        const 令牌 = 开始操作(状态, 操作名);
        if (!令牌) return;
        let 恢复规划表单 = false;
        收平移?.();
        try {
            if (!提交节点快照(快照, 取节点(), target => {
                const entry = 取记录(target);
                if (!entry) throw new Error(`暂无可${前进 ? "返回" : "撤销"}的编辑`);
                const previous = entry.草稿, cached = entry.分集编辑;
                const current = 真源.读剪辑草稿(target);
                恢复规划表单 = JSON.stringify(current.brief) !== JSON.stringify(previous.brief)
                    || JSON.stringify(current.规划资料) !== JSON.stringify(previous.规划资料);
                保存编辑记录(target, 返回历史);
                真源.写剪辑草稿(target, previous, { 记录历史: false });
                target.properties[当前历史] = target.properties[当前历史].slice(0, -1);
                const meta = previous.规划资料;
                if (meta?.任务引用?.id && meta.任务引用.token) {
                    target.properties.规划成果任务 = { ...meta.任务引用, stages: meta.阶段成果 || [], status: "completed" };
                } else delete target.properties.规划成果任务;
                delete target.properties.规划任务缓存;
                delete target.properties.提示词任务缓存;
                if (cached?.项目 === meta?.项目 && cached?.分集) {
                    target.properties.规划分集编辑 = JSON.parse(JSON.stringify(cached));
                } else delete target.properties.规划分集编辑;
            })) throw new Error("节点或草稿已变化，未覆盖当前内容，请重试");
            const i = Math.max(0, Math.min(active(), (读草稿().segments || []).length - 1));
            台词撤销 = null; 选择集 = new Set([i]); 播放头 = Math.min(播放头, 读草稿().segments?.at(-1)?.end || 0); 设active(i);
            if (恢复规划表单) ctx.恢复规划界面?.();
            ctx.回填当前段?.();
        } catch (e) {
            if (取节点() === n) void 弹确认(`${操作名}未完成`, e.message);
        } finally {
            结束操作(状态, 令牌); 渲染();
        }
    }

    async function 台词估时() {
        if (操作忙()) return;
        const n = 取节点(), 草 = 读草稿();
        if (!n || !草.segments?.length) return;
        const 快照 = 捕获节点快照(n);
        const 令牌 = 开始操作(状态, "台词估时");
        if (!令牌) return;
        const 原规划时长 = ctx.取规划总时长?.();
        收平移?.();
        忙 = true; 根.classList.add("忙"); 渲染();
        try {
            const 新草 = await 打开台词时长(草, ctx.取规划总时长?.());
            if (!新草) return;
            if (!提交节点快照(快照, 取节点(), 目标 => 真源.写剪辑草稿(目标, 新草))) {
                await 弹确认("台词重排未应用", "节点或草稿已变化，请重新打开台词估时并预览。");
                return;
            }
            ctx.同步台词总时长?.(新草.brief.总时长);
            台词撤销 = { 节点: n, 原草稿: 草, 原规划时长, 新值: JSON.stringify(读草稿()) };
            选择集 = new Set([0]); 设active(0);
        } catch (e) {
            await 弹确认("台词估时失败", e.message || "未能完成估时，请重试");
        } finally {
            结束操作(状态, 令牌);
            忙 = false; 根.classList.remove("忙"); 渲染();
            if (取节点() === n && !b台词.disabled) b台词.focus();
        }
    }
    function 撤销台词估时() {
        if (操作忙() || !台词撤销 || 取节点() !== 台词撤销.节点 || JSON.stringify(读草稿()) !== 台词撤销.新值) return;
        const 原 = 台词撤销;
        保存编辑记录(原.节点, "草稿前进历史");
        真源.写剪辑草稿(原.节点, 原.原草稿, { 记录历史: false });
        原.节点.properties.草稿编辑历史 = (原.节点.properties.草稿编辑历史 || []).slice(0, -1);
        if (Number.isFinite(原.原规划时长)) ctx.同步台词总时长?.(原.原规划时长);
        台词撤销 = null; 选择集 = new Set([0]); 设active(0); 渲染();
    }
    async function 填充节点() {
        if (操作忙()) return;
        const g = 段组();
        if (!g.length) { await 弹确认("无草稿段", "草稿为空，无可填充内容。"); return; }
        // 非全启用 → 仅填充启用段并按 ripple 闭拢时间（同手动删除未启用段的落点）；
        //   全启用（含旧草稿无 启用 字段）→ 原样填充全部段，效果与旧版逐字节一致。
        const 启用组 = g.filter(是启用);
        if (!启用组.length) { await 弹确认("无启用段", "所有段均未启用，请选中需要的段后点击「启用」，或先「全选」再点击「启用」。"); return; }
        const 待填 = JSON.parse(JSON.stringify(启用组));   // 先深拷再改 start/end，绝不回写草稿真源
        if (启用组.length !== g.length) 重排时间(待填);
        收平移?.();
        忙 = true; 根.classList.add("忙");
        b提示.disabled = b填充.disabled = true;
        try {
            await 应用规划(待填);   // 复用框架层：覆盖确认 → 写时间轴数据 → 全刷
        } finally {
            忙 = false; 根.classList.remove("忙");
            渲染();
        }
    }

    function 建卡(s, i) {
        const 卡 = document.createElement("div");
        卡.className = "lvp-ct-卡";
        const 色 = 段色[i % 段色.length];
        卡.style.setProperty("--seg", 色);
        卡.style.setProperty("--segsoft", 色 + "24");
        if (s.职能色) 卡.style.setProperty("--rolec", s.职能色);
        卡.title = `段${i + 1} · ${s.task || "t2v"} · ${一位(s.start)}–${一位(s.end)}s`;
        const 顶 = document.createElement("div"); 顶.className = "lvp-ct-顶"; 卡.appendChild(顶);
        const 头 = document.createElement("div"); 头.className = "lvp-ct-头";
        const 序 = document.createElement("span"); 序.className = "lvp-ct-序"; 序.textContent = String(i + 1);
        const 区 = 建时长输入(s, i);
        头.appendChild(序);
        // 职能块（2026-09-18 契约键改名）：内容是 钩子/递进/高潮… 叙事职能而非人物角色；数据键与 UI 文案统一为「职能」
        if (s.职能) { const 角 = document.createElement("span"); 角.className = "lvp-ct-角色"; 角.textContent = s.职能; 角.title = s.职能; 头.appendChild(角); }
        头.appendChild(区); 卡.appendChild(头);
        // 详情直接上卡（标题/职能/台词/提示词）：取消下方摘要条与素材图后，段卡即信息载体（条件渲染，无则不建元素；窄卡按容器查询逐级隐藏）。
        if (s.标题) { const 题 = document.createElement("div"); 题.className = "lvp-ct-标题"; 题.textContent = s.标题; 题.title = s.标题; 卡.appendChild(题); }
        if (Array.isArray(s.使用素材) && s.使用素材.length) { const 素 = document.createElement("div"); 素.className = "lvp-ct-素材"; 素.textContent = "🎞 " + s.使用素材.join("、"); 素.title = "本段分配素材：" + s.使用素材.join("、"); 卡.appendChild(素); }
        if (s.台词) { const 文 = document.createElement("div"); 文.className = "lvp-ct-对白"; 文.textContent = s.台词; 文.title = s.台词; 卡.appendChild(文); }
        if (取台词文本(s).trim()) {
            const 估 = document.createElement("div"); 估.className = "lvp-ct-台词";
            try {
                const x = 台词估时详情(s, { ...默认台词设置, ...读草稿().台词设置 });
                估.textContent = "台词约" + x.秒数.toFixed(1) + "秒 · " + (x.偏紧 ? "偏紧" : "可容纳") + (s.台词拆段待核查 ? " · 核查画面" : "");
                估.title = 取台词文本(s) + "\n" + x.来源 + "；慢／正常／快：" + [x.慢, x.正常, x.快].map(n => n.toFixed(1)).join(" / ") + "秒";
            } catch (e) { 估.textContent = e.message; }
            卡.appendChild(估);
        }
        const 词 = document.createElement("div"); 词.className = "lvp-ct-词"; 词.textContent = (s.prompt || "").trim() || "（未填提示词）"; 卡.appendChild(词);
        刷段卡验收(卡, s);
        if (i > 0) { const h = document.createElement("div"); h.className = "lvp-ct-把手 左"; h.addEventListener("pointerdown", (e) => 起trim(e, i, "左")); 卡.appendChild(h); }
        const hr = document.createElement("div"); hr.className = "lvp-ct-把手 右"; hr.addEventListener("pointerdown", (e) => 起trim(e, i, "右")); 卡.appendChild(hr);
        卡.addEventListener("pointerdown", (e) => 起卡(e, i));
        return 卡;
    }

    function 渲染() {
        if (当前提示词任务 && 取节点() !== 任务节点) 当前提示词任务.断开();
        收scrub?.();
        缩放更新.取消(); 待缩放 = null;
        裁剪更新.取消(); 移卡更新.取消();
        for (const [名, fn] of [["pointermove", 排trim], ["pointerup", 收trim], ["pointercancel", 收trim],
            ["pointermove", 排移卡], ["pointerup", 收卡], ["pointercancel", 收卡]]) window.removeEventListener(名, fn);
        刻度节点 = new Map(); 刻度签名 = "";
        const g = 段组(), 节点 = 取节点();
        显示总秒数 = 总时长Of(g);
        if (节点 !== 视图节点 || !g.length) {
            缩放 = 1; 播放头 = 0; 视图起点 = 0;
        }
        视图节点 = 节点;
        渲染代++;
        卡片组 = []; 槽组 = [];
        播放头El = null; 播放hit = null;   // M2：复位，防整树重建后持有已脱离 DOM 的僵尸节点
        收平移?.();
        拖 = null;                                        // I3 兜底：整树重建时清拖拽残态
        根.replaceChildren();

        // 工具行
        const 工具 = document.createElement("div"); 工具.className = "lvp-ct-行 lvp-ct-工具";
        const 有段 = g.length > 0;
        // I2：外部整树重建（如生成规划换新草稿）后，按下标存的选择集/active 会越界错位 → 收敛
        选择集 = new Set([...选择集].filter((i) => i < g.length));
        if (active() > g.length - 1) 设active(Math.max(0, g.length - 1));
        // 新建不受「有无段」限制：只要绑定了节点，空草稿也能建第一段（此为本功能核心）；未绑定/忙时禁用，避免「可点却无效」的死按钮。
        const b新建 = 建钮("➕ 新建", "", "在末尾添加一个空白分段，可直接手动编辑（无需先生成规划）", 新建);
        const b分割 = 建钮("✂ 分割", "", "在播放头处把当前段一分为二", 分割);
        const b全选 = 建钮("全选", "", "选中全部分段，可批量删除或切换启用状态", 全选);
        const b删除 = 建钮("🗑 删除", "危", "删除选中段（多选批量），其余段 ripple 闭拢", 删除);
        const b启用 = 建钮("启用", "", "切换选中段（或多选）是否参与 AI 生成提示词", 切启用);
        const b上一步 = 建钮("上一步", "", "后退一步，撤销最近一次内容操作；一次AI生成算一步，最多保留20步", () => 切换编辑历史());
        b上一步.disabled = 操作忙() || !节点 || !取上次编辑(节点);
        if (!取上次编辑(节点)) b上一步.title = "暂无可撤销的编辑";
        const b下一步 = 建钮("下一步", "", "返回后退前的内容；进行新的内容修改后，前进记录清空", () => 切换编辑历史(true));
        b下一步.disabled = 操作忙() || !节点 || !取下次编辑(节点);
        if (!取下次编辑(节点)) b下一步.title = "暂无可返回的编辑";
        // 禁用字幕开关（2026-09-28，规格 §6）：真源＝剪辑草稿顶层 禁用字幕，故每次 渲染() 现读、不自设闭包缓存
        //   （与节点时间轴「渐变过渡」开关同范式）——拆分/删除/启用切换/台词估时等任何写草稿路径都不会与 UI 失同步。
        //   只作用于「✨ AI 生成提示词」的画面文字；台词照常朗读和估时。
        const 字幕开关 = document.createElement("label"); 字幕开关.className = "lvp-ct-开关";
        const 字幕框 = document.createElement("input");
        字幕框.type = "checkbox"; 字幕框.className = "lvp-ct-开关框";
        字幕框.checked = 读草稿().禁用字幕 === true;
        字幕框.disabled = 操作忙() || !节点 || !有段;         // 生成期间不得改，避免与在途请求的 body 语义不一致；零段时与「台词估时」同口径禁用（勾了无处生效，且只含开关的空草稿会被计划存档判成「缺草稿」而在加载时丢掉）
        字幕框.onchange = () => {
            // 忙期 checkbox 未被程序禁用（禁用只在 渲染() 设，而 生成提示词() 进 忙 时不重渲染）；
            //   CSS `.lvp-ct.忙 .lvp-ct-开关{pointer-events:none}`（pointer-events 可继承，连内部 input 一起挡）
            //   挡得住鼠标、挡不住 Tab+Space，故在入口拒绝并回退真源。
            if (操作忙()) { 字幕框.checked = 读草稿().禁用字幕 === true; return; }
            写草稿(段组(), { 禁用字幕: 字幕框.checked });
        };
        字幕开关.title = "仅用于本页「AI生成提示词」，要求生成画面不出现字幕、标题字等屏上文字；不影响规划、编辑页提示词优化和台词估时。后期字幕请在「视频制作」页设置。";
        字幕开关.append(字幕框, "禁用字幕");
        if (字幕框.disabled) 字幕开关.classList.add("关禁");
        b台词 = 建钮("台词估时", "", "按语速检查台词／旁白，预览段长与拆分结果，确认后只更新草稿", 台词估时);
        b台词.disabled = 操作忙() || !节点 || !有段;
        b新建.disabled = 操作忙() || !节点;   // 节点 已在 渲染() 头部取好（取节点()）；与空草稿常显面板（Item1）配合：有节点即可建首段
        b分割.disabled = b全选.disabled = b删除.disabled = b启用.disabled = 操作忙() || !有段;
        概要El = document.createElement("span"); 概要El.className = "lvp-ct-概要";
        工具.append(b新建, b分割, b全选, b删除, b启用, b上一步, b下一步, 字幕开关, b台词);
        if (台词撤销?.节点 === 节点) {
            const 撤 = 建钮("撤销估时", "", "恢复最近一次台词调整；后续编辑后不可撤销，避免覆盖新内容", 撤销台词估时);
            撤.disabled = 操作忙() || JSON.stringify(读草稿()) !== 台词撤销.新值;
            工具.appendChild(撤);
        }
        根.appendChild(工具);

        // 生成行（AI生成提示词 + 填充节点）：持久元素，只建一次（C1）；模型在配置页管理。
        const 撑El = document.createElement("div"); 撑El.className = "lvp-ct-撑";
        工具.append(建生成行(), 撑El, 建缩放控件(), 概要El);
        b填充.disabled = 操作忙() || !有段;
        b提示.disabled = 停止生成 ? 停止中 : 操作忙() || !有段;
        if (!停止生成) b提示.title = "对每个启用段一次直接生成提示词，完成即回写";
        if (有段 && 节点) {
            const 应用态 = document.createElement("div"); 应用态.className = "lvp-ct-应用状态"; 应用态.setAttribute("aria-live", "polite");
            const 执行段 = 真源.读时间轴(节点).segments || [];
            const 待填 = JSON.parse(JSON.stringify(g.filter(是启用)));
            if (待填.length !== g.length) 重排时间(待填);
            const 排键 = 值 => Array.isArray(值) ? 值.map(排键) : 值 && typeof 值 === "object" ? Object.fromEntries(Object.keys(值).sort().map(k => [k, 排键(值[k])])) : 值;
            const 内容签名 = 组 => JSON.stringify(组.map(s => [s.segment_id, s.start, s.end, s.prompt, s.task || "t2v", s.i2v比例模式 || "裁剪", 排键(s.refs || {})]));
            const 预期 = ctx.取填充段?.(待填, 读草稿()) || 待填;
            应用态.textContent = 内容签名(预期) === 内容签名(执行段) ? "当前草稿已填充节点" : "草稿尚未填充节点 · 修改仅保存在草稿，确认后点「填充节点」";
            根.appendChild(应用态);
        }

        // 卷 → 内（时间线 + 轨道 + 播放头 + 插入线）
        const 卷 = document.createElement("div"); 卷.className = "lvp-ct-卷";
        卷.addEventListener("scroll", () => { 记视口起点(); 排时间线(); });   // 横滚（滚动条/触控板/拖拽）＝唯一改写视图起点的入口
        卷.addEventListener("wheel", 滚轮缩放, { passive: false });   // 滚轮＝缩放（CapCut 同款），横向滚则留给原生滚动条
        卷El = 卷;
        内 = document.createElement("div"); 内.className = "lvp-ct-内";
        卷.appendChild(内); 根.appendChild(卷);

        插入线 = document.createElement("div"); 插入线.className = "lvp-ct-插入线"; 插入线.style.display = "none";

        // Item1：草稿为空也常显时间轴面板（刻度尺+轨道），不退回整块空态、不放提示文字；
        // 0 段时刻度按 空轨刻度秒 保底铺出（2026-09-24 修复「剪辑时间轴不显示」＝刷时间线 总≤0 早退致刻度带空白）。
        时间线El = document.createElement("div"); 时间线El.className = "lvp-ct-时间线";
        时间线El.addEventListener("pointerdown", 起平移);
        const 轨 = document.createElement("div"); 轨.className = "lvp-ct-轨道";
        轨El = 轨;
        g.forEach((s, i) => {
            const 槽 = document.createElement("div"); 槽.className = "lvp-ct-槽";
            const 卡 = 建卡(s, i); 槽.appendChild(卡); 轨.appendChild(槽);
            卡片组.push(卡); 槽组.push(槽);
        });
        内.append(时间线El, 轨);

        // 播放头/scrub 把手仅在有段（有时长意义）时挂载；0 段纯空轨道不留播放头竖线。
        if (有段) {
            播放头El = document.createElement("div"); 播放头El.className = "lvp-ct-播放头";
            播放hit = document.createElement("div"); 播放hit.className = "lvp-ct-播放hit"; 播放hit.title = "拖动 scrub 预览";
            播放hit.addEventListener("pointerdown", 起scrub);
            内.append(播放头El, 播放hit);
            // 点击轨道空白处 scrub（把播放头移到点击点）
            轨.addEventListener("pointerdown", (e) => { if (e.target === 轨) 起scrub(e); });
        }
        内.appendChild(插入线);

        播放头 = Math.min(播放头, 总时长());
        刷比例(); 刷区间(); 刷概要(); 刷态(); 刷播放头(); 刷时间线();
        const pending = 节点?.properties?.提示词任务缓存;
        if (pending && !当前提示词任务 && !操作忙() && 待接回 !== pending) {
            待接回 = pending;
            Promise.resolve().then(async () => {
                try {
                    if (操作忙() || 取节点() !== 节点 || 节点.properties.提示词任务缓存 !== pending) return;
                    if (节点.properties.剪辑草稿 === pending.原稿签名) void 生成提示词(b提示, pending);
                    else {
                        await 创建提示词任务客户端({ 任务: pending, 更新() {} }).停止();
                        if (节点.properties.提示词任务缓存 === pending) delete 节点.properties.提示词任务缓存;
                        if (取节点() === 节点) await 弹确认("草稿已变化", "后台提示词生成已停止，已修改的草稿保持原样。");
                    }
                } catch (e) {
                    if (取节点() === 节点) await 弹确认("后台停止未确认", e.message);
                } finally { 待接回 = null; }
            });
        }
    }

    渲染();
    // 容器宽变化（面板拉伸/折叠/窗口 resize）→ 像素/秒 变 → 时间线刻度步长重算（秒↔分钟）
    const 尺寸更新 = 创建帧更新(() => { 刷缩放视图(); 刷时间线(); });
    if (typeof ResizeObserver !== "undefined") new ResizeObserver(() => 尺寸更新.请求()).observe(根);
    return {
        渲染, 刷active,
        取忙: () => 忙,
        重置视图: () => {
            收平移?.(); 缩放 = 1; 播放头 = 0; 视图起点 = 0;
            选择集 = new Set(); 拖 = null; 台词撤销 = null; 渲染();
        },
    };
}
