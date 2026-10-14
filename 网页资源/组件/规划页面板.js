import { 取操作忙, 开始操作, 结束操作 } from "./操作锁.js";
import { 真源, 取widget, 捕获节点快照, 提交节点快照, 使节点快照失效, 分配段ID, 修改节点, 写节点属性 } from "./桥接/节点桥.js";
// 标签→任务码 镜像（同 编辑页/时间轴 用法）：brief 下拉显示中文标签，但发给后端的必须是码
import { 任务码, 默认任务标签 } from "./生成类型选择.js";
import { 创建规划素材区, 图标 as 素材图标 } from "./规划素材区.js";
import { 挂素材提及 } from "./素材提及.js";
import { 创建规划任务客户端 } from "./规划任务客户端.js";
import { 保存分集编辑, 切换分集草稿 } from "./规划草稿版本.js";
import { 需求卡片, 取需求分类, 匹配需求卡片, 合并旧需求, 采集需求正文 } from "./规划需求卡片.js";
import { 创建参考图设置, 合并生成参考图 } from "./参考图设置.js";
import { 创建规划阶段成果 } from "./规划阶段成果.js";
import { 规划结果提示, 可交付规划 } from "./规划结果提示.js";

// AI规划页（Tab「AI规划」）专属样式：左=素材区（全局/段素材，见 规划素材区.js），
// 右=brief 表单区（两列网格 + 末行生成钮（模型在配置页管理））。
// 规划操作按钮复用框架层的 `.lvp-胶囊` 基元（状态栏面板.js 注入），本文件统一尺寸与圆角。
// 🔒 `.lvp-brief网格` 列模板必须是 minmax(0,1fr)：1fr＝minmax(auto,1fr)，auto 最小值＝列内 min-content，
// 使用零最小宽度，避免较长控件文字把单列撑宽而与上方两列错位（详 11 §I12）。
// 矮框只收留白；下限和密度阈值须同时容纳单行消息、原生控件缩放舍入及窄页滚动占高。
const 样式已注入 = { v: false };
// 面板重建（模块热重载 / 状态栏入口 DOM 级防重复重建）时用来摘掉上一轮 window 监听。
let 上轮停止 = null;
function 注入样式() {
    if (样式已注入.v) return;
    const s = document.createElement("style");
    s.textContent = `
      .lvp-brief区{display:flex;flex-direction:row;gap:8px;grid-column:span 2;min-width:0;box-sizing:border-box;background:var(--comfy-menu-bg,#2b2b2b);padding:0px;border-radius:8px;min-height:0;container-type:size}
      /* 素材、需求卡片、规划设置、统一需求四区等宽；内距放到各列以保证实际外宽一致。 */
      .lvp-brief表单列{display:flex;flex-direction:column;gap:3px;flex:1 1 0;min-width:0;min-height:0;box-sizing:border-box;padding:6px;overflow-y:auto}
      .lvp-brief内容列{display:flex;flex-direction:column;gap:3px;flex:1 1 0;min-width:0;min-height:0;box-sizing:border-box;padding:6px}
      .lvp-需求卡片列{display:flex;flex-direction:column;gap:6px;flex:1 1 0;min-width:0;min-height:0;box-sizing:border-box;padding:6px;background:var(--comfy-menu-bg,#2b2b2b);border-radius:8px}
      .lvp-规划列标题{margin:0;color:var(--fg-color,#ddd);font:600 12px system-ui;line-height:18px;flex:0 0 auto}
      /* 九宫格在紧凑高度内收缩封面，名称保留完整字号，九项同时可见。 */
      .lvp-需求卡片网格{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));grid-template-rows:repeat(3,minmax(0,1fr));gap:4px;flex:0 1 246px;height:246px;max-height:246px;min-height:0;padding:2px;overflow:visible}
      .lvp-需求卡片{position:relative;display:grid;grid-template-rows:minmax(0,1fr) 20px;padding:0;text-align:center;min-width:0;min-height:0;overflow:hidden;cursor:pointer;border:1px solid var(--border-color,#444);border-radius:5px;background:var(--comfy-input-bg,#1c1c1c);color:var(--fg-color,#ddd);transition:border-color .15s,background .15s}
      .lvp-需求卡片:hover{border-color:var(--p-primary-color,#4a9eff)}
      .lvp-需求卡片:focus-visible{outline:2px solid var(--p-primary-color,#4a9eff);outline-offset:1px}
      .lvp-需求卡片[aria-pressed="true"]{border-color:var(--p-primary-color,#4a9eff);box-shadow:inset 0 0 0 1px var(--p-primary-color,#4a9eff)}
      .lvp-需求卡片[aria-pressed="true"]::after{content:"✓";position:absolute;top:4px;right:4px;width:16px;height:16px;text-align:center;line-height:16px;font-size:11px;border-radius:3px;background:var(--p-primary-color,#4a9eff);color:var(--p-primary-contrast-color,#fff)}
      .lvp-需求封面{width:100%;height:100%;min-height:0;object-fit:cover;display:block;background:var(--comfy-menu-bg,#2b2b2b)}
      .lvp-需求卡片文字{display:flex;justify-content:center;align-items:center;padding:2px 1px;min-width:0;box-sizing:border-box}
      .lvp-需求卡片名称{font:600 11px system-ui;line-height:16px;white-space:nowrap}
      .lvp-需求卡片说明{display:none}
      .lvp-brief行{display:flex;align-items:center;gap:4px}
      .lvp-brief网格{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:3px 10px;container-type:inline-size;container-name:lvp-brief网格}
      @container lvp-brief网格 (max-width:480px){
        .lvp-总时长格{flex-wrap:wrap;row-gap:0}
        .lvp-总时长格>.lvp-brief入{flex-basis:0}
        .lvp-总时长格>.lvp-自动时长提示{flex:0 0 calc(100% - 40px);margin-left:40px}
        .lvp-brief网格>.lvp-brief行{align-self:start}
      }
      .lvp-brief网格>.跨{grid-column:1/-1}
      .lvp-参考图行{padding-left:40px;box-sizing:border-box}
      .lvp-参考图行[hidden]{display:none}
      .lvp-参考图勾选{display:flex;align-items:center;gap:4px;font:11px system-ui;color:var(--fg-color,#ddd);cursor:pointer}
      .lvp-参考图勾选 input{margin:0;accent-color:var(--p-primary-color,#4a9eff)}
      .lvp-参考图齿轮{width:24px;height:24px;padding:0;flex:0 0 24px;font-size:16px;line-height:1}
      .lvp-参考图弹窗{width:min(360px,85vw);max-height:85vh;box-sizing:border-box;padding:14px;border:1px solid var(--border-color,#444);border-radius:8px;background:var(--comfy-menu-bg,#2b2b2b);color:var(--fg-color,#ddd)}
      .lvp-参考图弹窗::backdrop{background:rgba(0,0,0,.5)}
      .lvp-参考图弹窗 h3{font:600 14px system-ui;margin:0 0 10px}
      .lvp-参考图弹窗 select,.lvp-参考图弹窗 textarea{display:block;box-sizing:border-box;width:100%;margin-bottom:10px;resize:vertical;min-width:0;font-size:12px}
      .lvp-参考图弹窗 textarea[hidden]{display:none}
      .lvp-brief标{color:var(--p-text-muted-color,#9aa0a8);font-size:10px;white-space:nowrap;flex:0 0 36px;width:36px;text-align:right}
      .lvp-brief单位{color:var(--p-text-muted-color,#9aa0a8);font-size:10px;flex:0 0 auto;white-space:nowrap}
      .lvp-brief入,.lvp-brief选{padding:2px 4px;background:var(--comfy-input-bg,#1c1c1c);color:var(--fg-color,#ddd);border:1px solid var(--border-color,#444);border-radius:4px;font:11px system-ui;flex:1;min-width:0}
      .lvp-brief入.短,.lvp-brief选.短{flex:0 0 44px;width:44px}
      .lvp-brief入.中,.lvp-brief选.中{flex:0 0 78px;width:78px}
      /* 长消息不得换行挤占固定表单高度，完整内容由 title 承载。 */
      .lvp-brief错{color:var(--p-error-color,#ff6b6b);font-size:10px;min-height:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .lvp-规划分栏{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;flex:1 1 auto;min-width:0;min-height:0}
      .lvp-素材栏{min-width:0;min-height:0;display:flex}
      /* 内容框＝contenteditable（用户 2026-09-30：引用要带背景色，textarea 做不到），行为见 素材提及.js。
         resize:vertical 需 overflow 非 visible 才出把手，故显式 overflow-y:auto；折行规则贴近原 textarea。 */
      .lvp-brief详细{flex:1;min-height:44px;overflow-y:auto;resize:vertical;background:var(--comfy-input-bg,#1c1c1c);color:var(--fg-color,#ddd);border:1px solid var(--border-color,#444);border-radius:4px;font:11px system-ui;line-height:1.3;padding:3px 5px;box-sizing:border-box;white-space:pre-wrap;overflow-wrap:break-word}
      /* contenteditable 没有 placeholder 属性，占位文案走 :empty::before（框清空时由 素材提及.js 摘掉残余节点以保住 :empty）。 */
      .lvp-brief详细:empty::before{content:attr(data-ph);color:var(--p-text-muted-color,#9aa0a8)}
      .lvp-规划操作{display:grid;grid-template-columns:subgrid;grid-column:1/-1;align-items:center}
      .lvp-规划操作>.lvp-胶囊{margin-left:40px;min-width:0;box-sizing:border-box;white-space:nowrap;padding:2px 10px;font-size:11px;font-weight:600;border-radius:6px;line-height:1.35}
      .lvp-规划进度{display:flex;flex-direction:column;gap:3px;flex:0 0 auto;font:10px system-ui}
      .lvp-规划进度[hidden]{display:none}
      .lvp-规划进度行{display:flex;gap:5px;align-items:center;min-width:0}
      .lvp-规划阶段{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .lvp-规划进度 progress{width:100%;height:6px;accent-color:var(--p-primary-color,#4a9eff)}
      .lvp-规划小钮{font:10px system-ui;padding:1px 5px;border:1px solid var(--border-color,#444);border-radius:4px;background:var(--comfy-input-bg,#1c1c1c);color:var(--fg-color,#ddd);white-space:nowrap}
      .lvp-brief内容列>[hidden]{display:none}
      /* A5 知识库来源回执行（常驻灰字；原内联样式移进类里，好让下面的 :empty 能收起占位。
         恒一行＋省略号，同上方 .lvp-brief错 的行高封顶口径；完整来源清单本来就在 title 上） */
      .lvp-brief回执{color:var(--p-text-muted-color,#9aa0a8);font-size:10px;min-height:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .lvp-brief错:empty,.lvp-brief回执:empty{display:none}
      /* 阈值按内容盒计算，退出时须容纳恢复的内距、行距和两条信息行占位。 */
      @container (max-height:225px){
        .lvp-brief网格{gap:2px 10px}
        .lvp-brief入,.lvp-brief选{padding:1px 4px}
        .lvp-brief错:empty,.lvp-brief回执:empty{display:none}
      }
      /* 3.3(122)：窄面板分区折叠。规划页（lvp-页面 lvp-规划页，display:flex）作为容器查询根；
         宽度 ≤480px 时左右分栏改纵向堆叠（素材区在上、brief 区在下各占整行），
         避免两列 50% 布局在窄宿主下溢出或被裁。*/
      .lvp-规划页{container-type:inline-size;container-name:lvp-规划页}
      @container lvp-规划页 (max-width:1100px){
        .lvp-brief网格{grid-template-columns:minmax(0,1fr)}
      }
      @container lvp-规划页 (max-width:480px){
        .lvp-规划分栏{display:flex;flex-direction:column;overflow-y:auto;min-height:0}
        .lvp-素材栏{flex:0 0 auto;min-height:100px;max-height:180px}
        .lvp-brief区{flex:1 1 100%;flex-direction:column;width:100%}
        .lvp-brief区{flex:0 0 auto;overflow:visible;container-type:normal}
        .lvp-brief表单列{flex:0 0 auto;overflow:visible}
        .lvp-brief网格{grid-template-columns:repeat(2,minmax(0,1fr))}
        .lvp-brief内容列{flex:0 0 auto;min-height:150px}
        .lvp-brief详细{min-height:120px;max-height:240px}
        .lvp-需求卡片列{flex:0 0 auto}
        .lvp-需求卡片网格{flex:0 0 216px;height:216px;max-height:none}
      }`;
    document.head.appendChild(s);
    样式已注入.v = true;
}

// 上下文（由 状态栏面板.js 注入，均为延迟求值的 getter/回调）：
//   取节点()  → 当前绑定节点（未绑定为 null；⚠️ 每次用都要重新取，不得缓存）
//   状态      → 状态桥（读/写「剪辑选中段」；与节点时间轴的「选中段」解耦，item3）
//   应用规划(segments) → 框架层公共动作（覆盖确认 → 写时间轴 → 全刷）；本面板不再调用（透传剪辑时间轴的职责已随 剪辑 迁入 提示词时间轴页面板.js）
//   重渲染时间轴页() → 框架层跨页转发到 提示词时间轴页面板.重渲染（生成规划写草稿后整树重绘剪辑，避免子面板互 import）
export function 创建规划页面板(规划页, 上下文) {
    注入样式();
    const { 取节点, 状态, 重渲染时间轴页 } = 上下文;
    const 上轮结束 = 上轮停止?.();
    let 当前任务 = null;
    let 任务节点 = null, 本轮结束 = Promise.resolve(上轮结束);
    let 生成中 = false, 停止中 = false;
    const 停任务 = () => {
        if (!当前任务 || 停止中) return;
        停止中 = true;
        隐藏进度();
        生成钮.disabled = true;
        当前任务.停止().catch(() => {});
    };
    上轮停止 = () => { 阶段成果.销毁(); if (当前任务?.断开) 当前任务.断开(); else 停任务(); return 本轮结束; };

    let 静态枚举已填 = false;   // 平台/钩子/任务 为代码常量（静态），仅首次装配填充一次

    // 左右分栏：左=素材区（规划素材区.js，设计 §3.3），右=brief 表单区
    const 分栏 = document.createElement("div");
    分栏.className = "lvp-规划分栏";
    规划页.appendChild(分栏);
    const 素材容器 = document.createElement("div");
    素材容器.className = "lvp-素材栏";
    分栏.appendChild(素材容器);
    const 素材区 = 创建规划素材区(素材容器, { 取节点, 状态 });
    const brief区 = document.createElement("div");
    brief区.className = "lvp-brief区";
    分栏.appendChild(brief区);
    // 需求卡片位于规划设置左侧；四个区域统一使用等宽列。
    const 左列 = document.createElement("div"); 左列.className = "lvp-brief表单列"; brief区.appendChild(左列);
    const 右列 = document.createElement("div"); 右列.className = "lvp-brief内容列"; brief区.appendChild(右列);
    const 卡片列 = document.createElement("section"); 卡片列.className = "lvp-需求卡片列"; 分栏.insertBefore(卡片列, brief区);
    const 设置标题 = document.createElement("h3"); 设置标题.className = "lvp-规划列标题"; 设置标题.textContent = "规划设置"; 左列.appendChild(设置标题);

    function brief行(父) { const d = document.createElement("div"); d.className = "lvp-brief行"; (父 || 左列).appendChild(d); return d; }
    function brief标(父, 文) { const l = document.createElement("label"); l.className = "lvp-brief标"; l.textContent = 文; 父.appendChild(l); return l; }
    function 填下拉(el, 选项, 默认, 保留) {
        const 旧 = 保留 ? el.value : null;   // 保留=true 时记住重填前的选中值（用于动态枚举刷新不重置用户选择）
        el.innerHTML = "";
        (选项 || []).forEach((o) => { const op = document.createElement("option"); op.value = typeof o === "object" ? o.名 || o : o; op.textContent = typeof o === "object" ? o.名 || o : o; el.appendChild(op); });
        if (旧 != null && [...el.options].some((op) => op.value === 旧)) el.value = 旧;   // 旧值仍在新选项中 → 保留
        else if (默认 != null) el.value = 默认;
    }

    const brief字段 = {};
    // 详细内容（大量详细要求，入草稿 brief 持久化；规划与提示词生成共用，设计 §3.3/§5.3）
    //   独占右列整块：右列＝标签行 + 满高内容框（contenteditable，@ 引用带背景色），其余表单全留在左列。
    const 内容头 = document.createElement("div"); 内容头.className = "lvp-brief行"; 右列.appendChild(内容头);
    const 内容标题 = document.createElement("h3"); 内容标题.className = "lvp-规划列标题"; 内容标题.textContent = "你的需求"; 内容头.appendChild(内容标题);
    const 详细el = document.createElement("div"); 详细el.className = "lvp-brief详细"; 详细el.contentEditable = "true";
    详细el.setAttribute("role", "textbox"); 详细el.setAttribute("aria-label", "你的需求"); 详细el.setAttribute("aria-multiline", "true");
    详细el.dataset.ph = "想做什么视频？写下想法，或粘贴小说、剧本、文案。\n\n补充必须出现的画面、台词与限制。输入 @ 引用左侧素材。";
    右列.appendChild(详细el);
    // @ 提及（用户 2026-09-30）：内容框打 @ 弹规划素材清单，选中插带背景色的 `@素材名` 引用块。
    // 素材走 真源 现读（不缓存），所以在素材墙增删后下一次打 @ 列到的就是新清单。
    // ⚠️ 框内内容不是 textarea 的 .value：读写一律过 提及.取文()/设文()，chip ↔ 纯文本由组件互转。
    const 提及 = 挂素材提及(详细el, {
        取素材: () => { const n = 取节点(); return n ? (真源.读剪辑草稿(n).素材 || []) : []; },
        图标表: 素材图标,
    });
    // 其余字段：两列网格（grid 列轨道统一 → 两列竖向对齐）
    const 网格 = document.createElement("div"); 网格.className = "lvp-brief网格"; 左列.appendChild(网格);
    function 网格格(标签) { const cell = brief行(网格); brief标(cell, 标签); return cell; }
    function 入控(类, 型) { const e = document.createElement(型 === "选" ? "select" : "input"); e.className = 类; if (型 !== "选") e.type = 型; return e; }
    // 保留时长、生成任务等设置，内容分类由需求卡片直接选择。
    const 时长格 = 网格格("总时长:"); 时长格.classList.add("lvp-总时长格");
    const 时长el = 入控("lvp-brief入", "number"); 时长el.value = 0; 时长el.min = 0; 时长el.max = 60; 时长el.step = "any"; 时长格.appendChild(时长el);
    时长el.title = "0=自动分配；非零值为目标总时长（分钟），按完整内容、动作与台词容量确定最终时长";
    const 时长单位 = document.createElement("span"); 时长单位.className = "lvp-brief单位"; 时长单位.textContent = "分钟"; 时长格.appendChild(时长单位);
    const 自动时长提示 = document.createElement("span"); 自动时长提示.className = "lvp-brief单位 lvp-自动时长提示"; 自动时长提示.textContent = "0=自动分配"; 自动时长提示.title = 时长el.title; 时长格.appendChild(自动时长提示);
    brief字段.总时长 = 时长el;   // 0 自动；非零按 5..3600 秒校验，另受调用预算约束。
    const 任务el = 入控("lvp-brief选", "选"); 网格格("任务:").appendChild(任务el); brief字段.默认任务 = 任务el;
    const 钩el = 入控("lvp-brief选", "选"); 网格格("钩子:").appendChild(钩el); brief字段.钩子 = 钩el;
    // 语言枚举＝MiniMax H3 官方稳定支持的 11 种对白语言（GitHub MiniMax-AI/MiniMax-H3 README），各用母语自称
    const 言el = 入控("lvp-brief选", "选"); 填下拉(言el, ["中文", "English", "日本語", "한국어", "العربية", "Français", "Deutsch", "Italiano", "Português", "Русский", "Español"], "中文"); 网格格("语言:").appendChild(言el); brief字段.语言 = 言el;
    const 风格el = 入控("lvp-brief入", "text"); 风格el.placeholder = "电影感"; 网格格("风格:").appendChild(风格el); brief字段.风格 = 风格el;
    const 平台el = 入控("lvp-brief选", "选"); 网格格("平台:").appendChild(平台el); brief字段.平台 = 平台el;
    const 受众el = 入控("lvp-brief入", "text"); 受众el.placeholder = "新手"; 网格格("受众:").appendChild(受众el); brief字段.受众 = 受众el;
    const 参考图控件 = 创建参考图设置(网格, 保存当前表单);
    任务el.addEventListener("change", () => 参考图控件.设任务(任务码(任务el.value)));
    let 当前分类 = 取需求分类(), 当前卡片 = "auto", 原始需求 = null, 需求已编辑 = false;
    详细el.addEventListener("input", () => { 需求已编辑 = true; });
    const 卡片标题 = document.createElement("h3"); 卡片标题.className = "lvp-规划列标题"; 卡片标题.textContent = "选择视频需求"; 卡片列.appendChild(卡片标题);
    const 卡片网格 = document.createElement("div"); 卡片网格.className = "lvp-需求卡片网格"; 卡片网格.setAttribute("aria-label", "视频需求类型"); 卡片列.appendChild(卡片网格);
    const 卡片按钮 = new Map();
    function 刷新卡片() {
        for (const [id, 按钮] of 卡片按钮) 按钮.setAttribute("aria-pressed", String(id === 当前卡片));
    }
    for (const c of 需求卡片) {
        const 按钮 = document.createElement("button"); 按钮.type = "button"; 按钮.className = "lvp-需求卡片"; 按钮.dataset.需求 = c.id; 按钮.title = c.说明; 按钮.setAttribute("aria-label", `${c.名称}，${c.说明}`);
        const 封面 = document.createElement("img"); 封面.className = "lvp-需求封面"; 封面.src = c.封面; 封面.alt = ""; 封面.decoding = "async"; 按钮.appendChild(封面);
        const 文字 = document.createElement("span"); 文字.className = "lvp-需求卡片文字";
        const 名称 = document.createElement("span"); 名称.className = "lvp-需求卡片名称"; 名称.textContent = c.名称;
        const 说明 = document.createElement("span"); 说明.className = "lvp-需求卡片说明"; 说明.textContent = c.说明; 文字.append(名称, 说明); 按钮.appendChild(文字);
        按钮.onclick = () => { 当前分类 = 取需求分类(c); 当前卡片 = c.id; 刷新卡片(); 保存当前表单(); };
        卡片按钮.set(c.id, 按钮); 卡片网格.appendChild(按钮);
    }
    刷新卡片();
    const brief错 = document.createElement("div"); brief错.className = "lvp-brief错";
    // 矮框档错误行只显示一行（CSS 省略号），完整文案挂 title，免得长文案换行把末两格挤出圆角框。
    const 报brief错 = (文本, 警告 = false) => { brief错.textContent = 文本; brief错.title = 文本; brief错.style.color = 警告 ? "var(--p-warning-color,#e0a458)" : ""; };
    // A5：知识库来源回执（仅列实际进入请求的资料 + 截断/缺失回显）；来自 /lvp/plan 的 response.knowledge，
    // 非错误行故用常驻灰字，无回执则留空。样式走 `.lvp-brief回执`（原内联 cssText 无法被 :empty 收起）。
    const 来源回执 = document.createElement("div"); 来源回执.className = "lvp-brief回执";
    function 显示来源回执(k) {
        // 🔒 回执恒一行（CSS 省略号）⇒ `title` 是唯一能看到全文的地方，任何清空/改写都要同步处理 title，
        //    否则空行仍会悬浮出上一节点/上一轮的内容。
        if (!k || typeof k !== "object" || k.error) { 来源回执.textContent = k && k.error ? "知识库加载失败，本次未注入来源" : ""; 来源回执.title = ""; return; }
        const 列 = (arr) => (Array.isArray(arr) ? arr.filter(Boolean) : []);
        const 入 = 列(k.included), 截 = 列(k.truncated), 跳 = 列(k.skipped), 缺 = 列(k.missing);
        const 素 = k.素材, 有知 = 入.length || 截.length || 跳.length || 缺.length;
        const 有素 = !!素 && (素.入 || 素.截断 || 素.过滤 || (素.缺失 || []).length);   // 设计 §5.2：knowledge 可仅含素材回执（未选技能）
        if (!有知 && !有素) { 来源回执.textContent = ""; 来源回执.title = ""; return; }
        const 部 = 有知 ? [`来源 ${入.length}`] : [];
        if (有素) 部.push(`素材 ${素.入}${素.过滤 ? `·过滤 ${素.过滤}` : ""}${素.截断 ? `·截断 ${素.截断}` : ""}${(素.缺失 || []).length ? `·缺失 ${素.缺失.length}` : ""}`);
        if (截.length) 部.push(`截断 ${截.length}`);
        if (跳.length) 部.push(`超预算跳过 ${跳.length}`);
        if (缺.length) 部.push(`缺失 ${缺.length}`);
        来源回执.textContent = (有知 ? "知识库：" : "素材使用：") + 部.join(" · ");
        来源回执.title = "实际进入请求：" + (入.join("、") || "无")
            + (有素 ? `
素材：入 ${素.入}${素.过滤 ? `，幻觉过滤 ${素.过滤}` : ""}${素.截断 ? `，正文截断 ${素.截断}` : ""}${(素.缺失 || []).length ? `，缺失：${素.缺失.join("、")}` : ""}` : "")
            + (截.length ? "\n截断：" + 截.join("、") : "")
            + (跳.length ? "\n超预算跳过：" + 跳.join("、") : "")
            + (缺.length ? "\n缺失：" + 缺.join("、") : "");
    }
    // 模型统一在配置页选择。
    const 生成钮 = document.createElement("button"); 生成钮.className = "lvp-胶囊 lvp-生成"; 生成钮.type = "button"; 生成钮.textContent = "生成规划";
    生成钮.style.cssText = "background:var(--p-primary-color,#4a9eff);color:var(--p-primary-contrast-color,#fff);border-color:var(--p-primary-color,#4a9eff);flex:1";
    const 生成格 = document.createElement("div"); 生成格.className = "lvp-规划操作"; 网格.appendChild(生成格); 生成格.appendChild(生成钮);
    生成钮.style.minWidth = "0";
    const 导入钮 = document.createElement("button"); 导入钮.type = "button"; 导入钮.className = "lvp-胶囊 lvp-载入规划";
    导入钮.textContent = "载入规划"; 导入钮.title = "重新载入后台保存的原始分镜，当前编辑可后退一步恢复"; 导入钮.style.cssText = "flex:1;min-width:0"; 生成格.appendChild(导入钮);
    let 导入中 = false;
    const 进度区 = document.createElement("div"); 进度区.className = "lvp-规划进度"; 进度区.hidden = true; 左列.appendChild(进度区);
    const 进度行 = document.createElement("div"); 进度行.className = "lvp-规划进度行"; 进度区.appendChild(进度行);
    const 阶段文 = document.createElement("span"); 阶段文.className = "lvp-规划阶段"; 进度行.appendChild(阶段文);
    const 进度条 = document.createElement("progress"); 进度条.max = 1; 进度条.setAttribute("aria-label", "规划阶段进度"); 进度区.appendChild(进度条);
    左列.append(brief错, 来源回执);
    function 隐藏进度() {
        进度区.hidden = true;
        进度条.value = 0;
        阶段文.textContent = ""; 阶段文.title = "";
    }
    function 更新进度(data) {
        if (!生成中 || 停止中) return;
        if (data.status === "cancelled") { 隐藏进度(); return; }
        const p = data.progress || {};
        const stage = data.status === "completed" ? (规划结果提示(data.result?.规划资料).待完善 ? "规划已输出，待完善" : "规划完成") : data.status === "cancelled" ? "已停止" : data.status === "failed" ? "规划失败" : p.阶段 || "准备规划";
        阶段文.textContent = `${stage}${p.集号 ? ` · 第${p.集号}/${p.集数}集` : ""}${p.总数 ? ` ${p.已完成}/${p.总数}` : ""}${p.复用检查点 ? " · 复用存档" : ""}${p.修复 ? " · 修复" : ""}${p.调用次数 ? ` · 已调用 ${p.调用次数} 次（上限 ${p.调用上限}）` : ""}`;
        阶段文.title = 阶段文.textContent;
        if (p.调用次数) 阶段文.title += "\n调用次数是模型调用尝试（含排队、修复及网络失败），不等于供应商已计费次数；复用检查点不增加次数。";
        if (data.status === "completed") 进度条.value = 1;
        else if (p.总数 && p.已完成 > 0) 进度条.value = p.已完成 / p.总数;
        else 进度条.removeAttribute("value");
    }
    // 四步成果导航留在规划设置列底部；矮面板沿用设置列滚动，不挤占其它三列。
    const 阶段成果 = 创建规划阶段成果(左列, { 取节点 });
    // 暂存保留小数秒，换绑优先暂存；加载计划则只丢弃当前节点旧暂存。
    const 暂存 = new WeakMap();
    let 暂存节点 = null;
    const 下拉默认 = { 平台: "通用", 钩子: "悬念钩", 语言: "中文", 默认任务: "t2v" };
    const 待恢复下拉 = new Map();
    let 枚举中 = 0;
    for (const 键 of Object.keys(下拉默认)) brief字段[键].addEventListener("change", () => 待恢复下拉.delete(键));
    function 读下拉(键) {
        if (待恢复下拉.has(键)) return 待恢复下拉.get(键);
        const 值 = brief字段[键].value;
        return 值 ? (键 === "默认任务" ? 任务码(值) : 值) : 下拉默认[键];
    }
    function 设下拉(键, 值) {
        const el = brief字段[键];
        const 码 = o => 键 === "默认任务" ? 任务码(o.value) : o.value;
        const 命中 = [...el.options].find(o => 码(o) === 值);
        if (!el.options.length || (!命中 && 枚举中 > 0)) { 待恢复下拉.set(键, 值); return; }
        el.value = (命中 || [...el.options].find(o => 码(o) === 下拉默认[键]) || el.options[0]).value;
        待恢复下拉.delete(键);
    }
    // 移除控件后，仅透传旧计划已有的执行配置，不为新计划制造默认字段。
    let 旧执行配置 = {};
    const 默认表单 = 采集brief();
    function 取编辑状态() {
        const brief = 采集brief();
        return { 有内容: Object.entries(brief).some(([键, 值]) => 值 !== 默认表单[键]), 签名: JSON.stringify(brief) };
    }
    function 采集brief() {
        return {
            ...旧执行配置,
            ...采集需求正文(提及.取文(), 原始需求, 需求已编辑),
            平台: 读下拉("平台"), 语言: 读下拉("语言"),
            总时长: Number(((brief字段.总时长.value === "" ? 0 : Number(brief字段.总时长.value)) * 60).toFixed(9)),
            段数上限: 0,
            钩子: 读下拉("钩子"),
            默认任务: 读下拉("默认任务"),
            ...参考图控件.取值(读下拉("默认任务")),
            风格: brief字段.风格.value.trim(), 受众: brief字段.受众.value.trim(),
            ...当前分类, ...(当前卡片 ? { 需求类型: 当前卡片 } : {}),
        };
    }
    function 保存当前表单() {
        const node = 取节点();
        if (!node || 暂存节点 !== node) return;
        const brief = 采集brief();
        暂存.set(node, brief);
        if (JSON.stringify(node.properties?.规划表单) !== JSON.stringify(brief)) 写节点属性(node, "规划表单", brief);
    }
    function 清除节点暂存(node) {
        if (!node) return;
        暂存.delete(node);
        if (Object.hasOwn(node.properties || {}, "规划表单")) 写节点属性(node, "规划表单", undefined);
    }
    for (const el of new Set([详细el, ...Object.values(brief字段)])) {
        el.addEventListener("input", 保存当前表单);
        el.addEventListener("change", 保存当前表单);
    }
    function 设表单(brief) {
        const b = (brief && typeof brief === "object") ? brief : {};
        旧执行配置 = Object.fromEntries(["执行后端", "段时长下限", "段时长上限"].filter(k => Object.hasOwn(b, k)).map(k => [k, b[k]]));
        // 文本/数字：缺失回落构造默认（见上方 brief入/网格格 初值），保证换节点不残留
        原始需求 = Object.fromEntries(["主题", "详细内容"].filter(k => Object.hasOwn(b, k)).map(k => [k, b[k]])); 需求已编辑 = false;
        提及.设文(合并旧需求(b));   // 合并旧主题和正文，再将纯文本引用重建为 chip。
        当前分类 = 取需求分类(b); 当前卡片 = 需求卡片.some(c => c.id === b.需求类型) ? b.需求类型 : 匹配需求卡片(b)?.id || ""; 刷新卡片();
        brief字段.风格.value = b.风格 ?? "";
        brief字段.受众.value = b.受众 ?? "";
        brief字段.总时长.value = (b.总时长 == null ? 0 : Number(b.总时长)) / 60;
        for (const [键, 默认] of Object.entries(下拉默认)) 设下拉(键, b[键] ?? 默认);
        参考图控件.恢复(b);
        参考图控件.设任务(b.默认任务 || "t2v");
    }
    function 恢复brief(节点, 清除暂存 = false) {
        if (当前任务 && 任务节点 === 节点 && !清除暂存) return;
        if (当前任务) { if (当前任务.断开) 当前任务.断开(); else 停任务(); 使节点快照失效(节点); }
        if (暂存节点 && 暂存节点 !== 节点) 暂存.set(暂存节点, 采集brief());
        if (清除暂存) 清除节点暂存(节点);
        const 草稿 = 节点 ? 真源.读剪辑草稿(节点) : null;
        const 成果 = 节点?.properties?.规划成果任务 || 节点?.properties?.规划任务缓存 || 草稿?.规划资料?.任务引用;
        阶段成果.绑定(节点, 成果, 成果?.stages || 草稿?.规划资料?.阶段成果);
        设表单((节点 && 暂存.get(节点)) || 节点?.properties?.规划表单 || 草稿?.brief);   // 优先未提交暂存，其次草稿 brief
        素材区.刷新();   // 换绑/加载计划/清除暂存同路径：素材区随草稿重绘（全局素材/素材 由时间轴页写回，本页只读展示）
        提及.关();       // 换绑即收层：弹层里挂着上一节点的素材名会误导引用
        显示来源回执(null); 来源回执.style.color = "";   // 换绑即清上一节点的 A5 来源/A3 诊断回显，不留驻陈旧灰字
        暂存节点 = 节点;
        const 结果提醒 = 规划结果提示(草稿?.规划资料);
        报brief错(结果提醒.待完善 ? 结果提醒.说明 : "", 结果提醒.待完善);
        const pending = 节点?.properties?.规划任务缓存;
        if (pending && !清除暂存) {
            const { 模型id: _model, 素材: _materials, 素材理解: _understanding, ...form } = pending.请求体;
            const 当前表单 = 节点.properties.规划表单;
            const 需求未变 = !当前表单 || JSON.stringify(当前表单) === pending.表单签名;
            if (需求未变 && JSON.stringify(草稿 || {}) === pending.原稿签名) {
                设表单(form);
                本轮结束.then(() => { if (取节点() === 节点 && !生成中 && 节点.properties.规划任务缓存 === pending) 执行规划(pending); });
            }
        }
    }

    生成钮.onclick = () => 执行规划();
    导入钮.onclick = async () => {
        if (生成中 || 导入中 || 取操作忙(状态)) { 报brief错("当前操作尚未结束，请等待完成后载入规划"); return; }
        const node = 取节点(); if (!node) { 报brief错("请先绑定规划师节点"); return; }
        const snapshot = 捕获节点快照(node), form = 取编辑状态().签名;
        const 令牌 = 开始操作(状态, "载入规划");
        if (!令牌) return;
        导入中 = true; 导入钮.disabled = true;
        try {
            const { 打开规划导入 } = await import("./数据管理.js");
            const imported = await 打开规划导入(); if (!imported) return;
            const data = imported.结果;
            if (!Array.isArray(data?.segments) || !data.segments.length || !data.segments.every(s => s && typeof s === "object" && !Array.isArray(s))) throw new Error("规划没有有效分镜，当前草稿未改变");
            if (取编辑状态().签名 !== form) throw new Error("当前需求或操作已变化，未载入规划，请重试");
            if (!提交节点快照(snapshot, 取节点(), target => {
                const old = 真源.读剪辑草稿(target);
                if (old?.规划资料?.项目 && old.规划资料.项目 === data.规划资料?.项目) {
                    const meta = old.规划资料;
                    const edits = target.properties.规划分集编辑?.项目 === meta.项目 ? target.properties.规划分集编辑 : { 项目: meta.项目, 分集: {} };
                    const next = { ...edits.分集, [meta.集号 || 1]: 保存分集编辑(old) };
                    if (JSON.stringify(next).length > 2000000) throw new Error("分集编辑缓存已达上限，当前手工改动已保留，未切换分集");
                    const selected = { ...data, segments: 分配段ID(data.segments.map(s => ({ ...s }))) };
                    真源.写剪辑草稿(target, { ...切换分集草稿(old, selected), 规划资料: { ...data.规划资料, ...selected.规划资料,
                        任务引用: data.规划资料.任务引用, 阶段成果: data.规划资料.阶段成果 } });
                    target.properties.规划分集编辑 = { 项目: meta.项目, 分集: next };
                    target.properties.规划成果任务 = imported.引用;
                    delete target.properties.规划任务缓存;
                    target.graph?.change?.();
                    return;
                }
                let write = { ...old, brief: imported.brief || {}, segments: 分配段ID(data.segments.map(s => ({ ...s }))), 规划资料: data.规划资料 };
                // 使用载入规划的素材分配，节点的字幕开关和制作工程保留。
                write.素材 = imported.素材 || [];
                write.素材理解 = imported.素材理解 || {};
                if (data.全局素材) write.全局素材 = data.全局素材; else delete write.全局素材;
                if (data.生成参考图资料) write = 合并生成参考图(write, data.生成参考图资料);
                真源.写剪辑草稿(target, write);
                target.properties.规划成果任务 = imported.引用;
                delete target.properties.规划任务缓存; delete target.properties.规划分集编辑;
                target.graph?.change?.();
            })) throw new Error("节点或草稿已变化，未载入规划，请重试");
            恢复brief(node, true); 状态.设("剪辑选中段", 0); 重渲染时间轴页?.();
        } catch (e) { if (取节点() === node) 报brief错(e.message || "规划载入失败"); }
        finally { 结束操作(状态, 令牌); 导入中 = false; 导入钮.disabled = false; }
    };
    async function 执行规划(恢复 = null) {
        if (生成中) { 停任务(); return; }
        if (导入中) return;
        if (取操作忙(状态)) { 报brief错("当前操作进行中，请等待完成后再发起规划"); return; }   // B3：跨入口互斥
        // ⚠️ 必须在两条早退校验**之前**清空：否则上一轮成功的来源回执会留在框里，与本轮「未绑定/主题为空」
        // 的错误行同时占位——矮框档底部余量只够一行信息，两行会把末两格挤出圆角框（且已无滚动兜底）。
        报brief错(""); 显示来源回执(null); 来源回执.style.color = "";
        const 节点 = 取节点();
        if (!节点) { 报brief错("请先绑定长视频规划师节点"); return; }
        const brief = 采集brief();
        brief.总时长 = brief.总时长 > 0 ? Math.max(1, Math.round(brief.总时长)) : brief.总时长;   // 微小正值不能四舍五入后误入自动模式。
        const 请求体 = 恢复?.请求体 || { ...brief };
        if (!恢复 && !请求体.详细内容) delete 请求体.详细内容;
        const 素材清单 = (真源.读剪辑草稿(节点).素材 || []).filter(m => !请求体.生成参考图 || !m.生成参考图);
        if (!恢复 && 素材清单.length) 请求体.素材 = 素材清单;
        const 素材理解 = 真源.读剪辑草稿(节点).素材理解;
        if (!恢复 && 素材理解 && typeof 素材理解 === "object") 请求体.素材理解 = Object.fromEntries(
            Object.entries(素材理解).filter(([名]) => 素材清单.some(m => m.名 === 名)));
        if (!brief.主题 && !brief.详细内容 && !素材清单.some(m => m.类型 === "文本")) { 报brief错("请提供想法、正文或文本素材"); return; }
        const 表单签名 = 取编辑状态().签名;
        // 需求在成功规划前尚未写入草稿，先暂存，避免失败后的同节点重绑定读回旧正文。
        暂存.set(节点, 采集brief());
        let 原稿签名 = JSON.stringify(真源.读剪辑草稿(节点));
        // 新一轮请求立即使旧响应失效，即使最终生成的 JSON 恰好相同。
        使节点快照失效(节点);
        let 快照 = 捕获节点快照(节点);
        生成中 = true; 停止中 = false;
        任务节点 = 节点;
        阶段成果.绑定(节点, 恢复, 恢复?.stages);
        if (!恢复) 写节点属性(节点, "规划成果任务", undefined);
        let 结束本轮;
        本轮结束 = new Promise(resolve => { 结束本轮 = resolve; });
        状态.设("LLM请求在途", true);   // B3：反向互斥——规划在途时「AI生成提示词」同样被挡
        生成钮.disabled = false; 生成钮.textContent = "停止规划";
        进度区.hidden = false;
        更新进度({ progress: { 阶段: "准备输入" } });
        let 本轮参考图已接收 = false;
        const 编辑批次 = {};
        function 接收参考图(data) {
            const refs = data.progress?.生成参考图资料;
            if (!refs?.素材?.length || 停止中 || 取编辑状态().签名 !== 表单签名 || 取节点() !== 节点) return;
            const 草 = 真源.读剪辑草稿(节点), 写 = 合并生成参考图(草, refs);
            if (JSON.stringify(写) === JSON.stringify(草)) return;
            if (!提交节点快照(快照, 取节点(), 目标 => 真源.写剪辑草稿(目标, 写, { 编辑批次 }))) return;
            本轮参考图已接收 = true;
            快照 = 捕获节点快照(节点);
            原稿签名 = JSON.stringify(写);
            if (节点.properties.规划任务缓存) 节点.properties.规划任务缓存.原稿签名 = 原稿签名;
            节点.graph?.change?.();
            素材区.刷新();
        }
        const 任务 = 创建规划任务客户端({ 更新: data => { if (当前任务 === 任务) {
                接收参考图(data);
                if (取节点() === 节点) {
                    更新进度(data);
                    if ((!停止中 || ["completed", "failed", "cancelled"].includes(data.status)) && Array.isArray(data.stages)) {
                        const ref = 节点.properties.规划成果任务 || 节点.properties.规划任务缓存;
                        if (ref?.id && ref?.token) {
                            修改节点(节点, () => {
                                节点.properties.规划成果任务 = { id: ref.id, token: ref.token, stages: data.stages, status: data.status };
                                if (节点.properties.规划任务缓存) 节点.properties.规划任务缓存.stages = data.stages;
                            });
                            阶段成果.更新(data, ref);
                        }
                    }
                }
            } },
            恢复任务: 恢复,
            保存任务: data => {
                修改节点(节点, () => {
                    节点.properties.规划任务缓存 = { ...data, 原稿签名, 表单签名 };
                    节点.properties.规划成果任务 = { id: data.id, token: data.token, stages: data.stages || 恢复?.stages || [] };
                });
                if (取节点() === 节点) 阶段成果.绑定(节点, data, data.stages || 恢复?.stages);
            } });
        当前任务 = 任务;
        进度区.scrollIntoView?.({ block: "nearest" });
        let 规划完成 = false;
        try {
            const 数据 = await 任务.运行(请求体);
            if (停止中) throw Object.assign(new Error("已停止，原草稿未改变"), { name: "AbortError" });
            if (!Array.isArray(数据?.segments) || !数据.segments.length ||
                !数据.segments.every(s => s && typeof s === "object" && !Array.isArray(s))) {
                throw new Error("规划响应无有效段，未修改草稿，请重试");
            }
            if (!可交付规划(数据)) {
                throw Object.assign(new Error("规划尚未完整验收，阶段成果已保存，原草稿未改变"), { 终态: true });
            }
            // 两阶段流程：生成规划**先写草稿**（剪辑时间轴预演），不再直接写节点时间轴。
            // brief 快照随草稿存（剔除 模型id：它只作用于本次请求，不属草稿内容）。
            const 草brief = { ...brief }; delete 草brief.模型id;
            if (!草brief.详细内容) delete 草brief.详细内容;   // 缺省＝无键（不做迁移写入）
            if (取编辑状态().签名 !== 表单签名) { 写节点属性(节点, "规划任务缓存", undefined); 报brief错("需求已变化，已丢弃规划结果，原草稿未改变"); return; }
            const 已提交 = 提交节点快照(快照, 取节点(), (目标) => {
                // 新规划段均为全新实体：写入前就地补齐稳定 segment_id（A3），拖动/分割/保存往返据此保持身份。
                // 冲突1 裁定A：规划只换 brief/segments，「禁用字幕」是节点级开关态，跟节点走、不被静默重置；未勾过则保持无键。
                const 旧 = 真源.读剪辑草稿(目标);
                let 写 = { ...旧, brief: 草brief, segments: 分配段ID(数据.segments), 规划资料: 数据.规划资料 };
                if (数据.规划任务引用) 写.规划资料 = { ...写.规划资料, 任务引用: 数据.规划任务引用, 阶段成果: 阶段成果.取阶段() };
                if (数据.分集?.length) 写.规划资料 = { ...写.规划资料, 分集索引: 数据.分集 };
                // 新分镜保留实体卡、音轨、字幕、工作流及画布。旧镜头关联在制作页提示清理。
                if (旧.制作) 写.制作 = 旧.制作;
                if (旧.素材理解) 写.素材理解 = Object.fromEntries(Object.entries(旧.素材理解).filter(([名]) => (旧.素材 || []).some(m => m.名 === 名)));
                if (Array.isArray(旧.素材) && 旧.素材.length) 写.素材 = 旧.素材;                 // 段素材清单保留（编辑归提示词时间轴页）
                if (Array.isArray(数据.全局素材) && 数据.全局素材.length) 写.全局素材 = 数据.全局素材;   // 全局素材＝本轮新分配（无则不写键）
                else delete 写.全局素材;
                if (数据.生成参考图资料) 写 = 合并生成参考图(写, 数据.生成参考图资料);
                真源.写剪辑草稿(目标, 写, { 编辑批次 });
            });
            if (!已提交) { 写节点属性(节点, "规划任务缓存", undefined); 报brief错("节点、草稿或请求已变化，已丢弃规划结果，请重试"); return; }
            规划完成 = true;
            写节点属性(节点, "规划任务缓存", undefined);
            delete 节点.properties.规划分集编辑;
            if (brief.总时长 === 0) {
                const 秒 = Math.max(...数据.segments.map(s => Number(s.end) || 0));
                阶段文.textContent = `规划完成 · ${数据.segments.length} 段 · 自动时长 ${Number(秒.toFixed(2))} 秒`;
                阶段文.title = 阶段文.textContent;
            }
            if (数据.分集?.length) {
                阶段文.textContent = `${规划结果提示(数据.规划资料).待完善 ? "已有规划已输出，待完善" : "全剧生成完成"} · ${数据.分集.length}集 · ${Number(数据.规划资料.全剧时长.toFixed(2))}秒 · 已调用${数据.规划资料.累计调用}次`;
                阶段文.title = 阶段文.textContent;
            }
            const 提醒 = 规划结果提示(数据.规划资料);
            if (提醒.待完善) {
                阶段文.textContent = `规划已输出（待完善） · ${数据.segments.length}段`;
                阶段文.title = 提醒.说明;
                报brief错(提醒.说明 || "规划已输出，请查看待完善项。", true);
            }
            清除节点暂存(节点);   // 3.3(120)：已提交 → 草稿.brief 即真源，清除该节点未提交暂存
            素材区.刷新();
            重渲染时间轴页?.();   // 拆页回归修复：剪辑已迁至提示词时间轴页，写草稿后须跨页整树重绘（原同页 剪辑.渲染 的替代）
            状态.设("剪辑选中段", 0);
            显示来源回执(数据.knowledge);   // A5：回显本次实际来源/截断/缺失
            // A3：不足段数已作一次定向修复仍不足 → 后端不再复制末段凑数，而是返回有效段+诊断，界面显式告知。
            if (数据.diagnostics && 数据.diagnostics.insufficient_segments) {
                来源回执.style.color = "var(--p-warning-color,#e0a458)";
                来源回执.textContent = (来源回执.textContent ? 来源回执.textContent + " · " : "")
                    + (数据.diagnostics.message || "故事未规划完整");
                // 回执恒一行、超出走省略号 ⇒ title 是唯一全文载体：在来源清单之后**追加**诊断，
                // 不能整体覆盖（原写法会把「实际进入请求…」的悬浮挤掉，两部分都读不全）。
                来源回执.title = (来源回执.title ? 来源回执.title + "\n" : "") + (数据.diagnostics.message || "");
            } else {
                来源回执.style.color = "var(--p-text-muted-color,#9aa0a8)";
            }
        } catch (e) {
            if (停止中 || e.终态) 写节点属性(节点, "规划任务缓存", undefined);
            报brief错(本轮参考图已接收 ? (停止中 || e.name === "AbortError" ? "已停止，原分镜未改变，已生成参考图保留"
                : (e.message || "规划失败") + "；已生成参考图保留，原分镜未改变") : e.message || "规划失败");
            阶段文.textContent = e.name === "AbortError" ? "已停止" : "规划失败";
        } finally {
            // 保留等待期间的最新编辑；显式加载计划或换节点时不把旧请求表单写到新页面。
            if (!规划完成 && 取节点() === 节点 && 暂存节点 === 节点) 暂存.set(节点, 采集brief());
            if (!规划完成) 隐藏进度();
            if (取节点() === 节点 && !规划完成) 阶段成果.刷新();
            当前任务 = null;
            任务节点 = null; 结束本轮();
            生成中 = false; 停止中 = false;
            状态.设("LLM请求在途", false);
            生成钮.disabled = false; 生成钮.textContent = "生成规划";
        }
    }

    async function 拉规划枚举() {
        枚举中++;
        let 已刷新 = false;
        try {
            const m = await (await fetch("/lvp/plan_meta")).json();
            if (!静态枚举已填) {
                // 平台/钩子/任务 均为代码常量（静态），仅首次装配填充一次；重复展开重填会
                // 把用户已选值异步重置回默认（填下拉 保留=false），故守住只填一遍。
                静态枚举已填 = true;
                // 同时填充 AI 规划页 brief 表单下拉
                填下拉(平台el, ["通用", ...(m.平台 || []).filter(v => v !== "通用")], "通用");
                填下拉(钩el, m.钩子, "悬念钩");
                // 选项沿用节点中文标签，AI 规划始终默认 t2v，不跟随或修改执行节点已保存的任务。
                const 节点 = 取节点();
                const wOpts = 节点 ? 取widget(节点, "任务类型")?.options?.values : null;
                填下拉(任务el, wOpts?.length ? wOpts : 默认任务标签, "文生视频 t2v");
            }
            已刷新 = true;
        } catch {} finally {
            枚举中--;
            if (已刷新) for (const [键, 值] of 待恢复下拉) 设下拉(键, 值);
            参考图控件.设任务(读下拉("默认任务"));
        }
    }
    // 绑定节点/换节点/加载计划时由框架层调用：恢复brief（含素材区刷新）；
    // 总时长 供状态栏面板跨页读写（UI 分钟 ↔ 契约秒）；重渲染 刷素材区（草稿素材键变化时）。
    return {
        恢复brief, 取编辑状态, 拉规划枚举,
        清除节点暂存,
        重置: node => {
            清除节点暂存(node);
            if (取节点() !== node) return;
            待恢复下拉.clear();
            恢复brief(node, true);
            报brief错(""); 隐藏进度();
            来源回执.textContent = ""; 来源回执.title = "";
            生成钮.disabled = false; 生成钮.textContent = "生成规划";
        },
        重渲染: () => { 素材区.刷新(); 提及.关(); },   // 草稿素材键变了：清单重绘，弹层同步收掉（旧行会引用已删素材）
        取总时长秒: () => Number(brief字段.总时长.value) * 60,
        设总时长秒: 秒 => {
            brief字段.总时长.value = 秒 / 60;
            const 节点 = 取节点();
            if (节点 && 暂存.has(节点)) 保存当前表单();
        },
    };
}
