import { 真源, 取widget, 捕获节点快照, 提交节点快照, 使节点快照失效, 分配段ID } from "./桥接/节点桥.js";
// 标签→任务码 镜像（同 编辑页/时间轴 用法）：brief 下拉显示中文标签，但发给后端的必须是码
import { 任务码, 默认任务标签 } from "./生成类型选择.js";
import { 创建规划素材区, 图标 as 素材图标 } from "./规划素材区.js";
import { 挂素材提及 } from "./素材提及.js";

// AI规划页（Tab「AI规划」）专属样式：左=素材区（全局/段素材，见 规划素材区.js），
// 右=brief 表单区（两列网格 + 末行模型下拉/生成钮）。
// ⚠️ 生成钮复用框架层的 `.lvp-胶囊` 基元（状态栏面板.js 注入），本文件只补 `.lvp-生成` 尺寸覆写；
// 框架样式必然先注入（创建状态栏面板 首行），故 `.lvp-生成` 的 padding/font-size 照常胜出，与拆分前一致。
// 🔒 `.lvp-brief网格` 列模板必须是 minmax(0,1fr)：1fr＝minmax(auto,1fr)，auto 最小值＝列内 min-content，
// 模型下拉的长选项（如「Kimi-K3（未配置Key）」）会把左列撑宽 → 与上方两列错位（详 11 §I12）。
// 矮框只收留白；下限和密度阈值须同时容纳单行消息、原生控件缩放舍入及窄页滚动占高。
const 样式已注入 = { v: false };
// 面板重建（模块热重载 / 状态栏入口 DOM 级防重复重建）时用来摘掉上一轮 window 监听。
let 上轮监听 = null;
function 注入样式() {
    if (样式已注入.v) return;
    const s = document.createElement("style");
    s.textContent = `
      .lvp-brief区{display:flex;flex-direction:row;gap:8px;flex:3 1 0;min-width:0;box-sizing:border-box;background:var(--comfy-menu-bg,#2b2b2b);padding:6px;border-radius:8px;min-height:0;container-type:size}
      /* brief 区一分为二：左列＝主题/字段网格/错误/回执（原纵向表单），右列＝详细内容整块满高（用户 2026-09-30 排布）。两列等宽 flex:1 1 0。 */
      .lvp-brief表单列{display:flex;flex-direction:column;gap:3px;flex:1 1 0;min-width:0}
      .lvp-brief内容列{display:flex;flex-direction:column;gap:3px;flex:1 1 0;min-width:0}
      .lvp-brief行{display:flex;align-items:center;gap:4px}
      .lvp-brief网格{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:3px 10px}
      .lvp-brief网格>.跨{grid-column:1/-1}
      .lvp-brief标{color:var(--p-text-muted-color,#9aa0a8);font-size:10px;white-space:nowrap;flex:0 0 36px;width:36px;text-align:right}
      .lvp-brief单位{color:var(--p-text-muted-color,#9aa0a8);font-size:10px;flex:0 0 auto;white-space:nowrap}
      .lvp-brief入,.lvp-brief选{padding:2px 4px;background:var(--comfy-input-bg,#1c1c1c);color:var(--fg-color,#ddd);border:1px solid var(--border-color,#444);border-radius:4px;font:11px system-ui;flex:1;min-width:0}
      .lvp-brief入.短,.lvp-brief选.短{flex:0 0 44px;width:44px}
      .lvp-brief入.中,.lvp-brief选.中{flex:0 0 78px;width:78px}
      /* 长消息不得换行挤占固定表单高度，完整内容由 title 承载。 */
      .lvp-brief错{color:var(--p-error-color,#ff6b6b);font-size:10px;min-height:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .lvp-规划分栏{display:flex;gap:8px;flex:1 1 auto;min-width:0}
      .lvp-素材栏{flex:2 1 0;min-width:0;display:flex}
      /* 内容框＝contenteditable（用户 2026-09-30：引用要带背景色，textarea 做不到），行为见 素材提及.js。
         resize:vertical 需 overflow 非 visible 才出把手，故显式 overflow-y:auto；折行规则贴近原 textarea。 */
      .lvp-brief详细{flex:1;min-height:44px;overflow-y:auto;resize:vertical;background:var(--comfy-input-bg,#1c1c1c);color:var(--fg-color,#ddd);border:1px solid var(--border-color,#444);border-radius:4px;font:11px system-ui;line-height:1.3;padding:3px 5px;box-sizing:border-box;white-space:pre-wrap;overflow-wrap:break-word}
      /* contenteditable 没有 placeholder 属性，占位文案走 :empty::before（框清空时由 素材提及.js 摘掉残余节点以保住 :empty）。 */
      .lvp-brief详细:empty::before{content:attr(data-ph);color:var(--p-text-muted-color,#9aa0a8)}
      .lvp-模型选{flex:1;min-width:0;padding:2px 5px;background:var(--comfy-input-bg,#1c1c1c);color:var(--fg-color,#ddd);border:1px solid var(--border-color,#444);border-radius:6px;font:11px system-ui}
      .lvp-生成{flex:0 0 auto;white-space:nowrap;padding:2px 10px;font-size:11px;font-weight:600;border-radius:6px;line-height:1.35}
      /* A5 知识库来源回执行（常驻灰字；原内联样式移进类里，好让下面的 :empty 能收起占位。
         恒一行＋省略号，同上方 .lvp-brief错 的行高封顶口径；完整来源清单本来就在 title 上） */
      .lvp-brief回执{color:var(--p-text-muted-color,#9aa0a8);font-size:10px;min-height:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      /* 阈值按内容盒计算，退出时须容纳恢复的内距、行距和两条信息行占位。 */
      @container (max-height:225px){
        .lvp-brief网格{gap:2px 10px}
        .lvp-brief入,.lvp-brief选,.lvp-模型选{padding:1px 4px}
        .lvp-brief错:empty,.lvp-brief回执:empty{display:none}
      }
      /* 3.3(122)：窄面板分区折叠。规划页（lvp-页面 lvp-规划页，display:flex）作为容器查询根；
         宽度 ≤480px 时左右分栏改纵向堆叠（素材区在上、brief 区在下各占整行），
         避免两列 50% 布局在窄宿主下溢出或被裁。*/
      .lvp-规划页{container-type:inline-size;container-name:lvp-规划页}
      @container lvp-规划页 (max-width:480px){
        .lvp-规划分栏{flex-direction:column}
        .lvp-素材栏{flex:1 1 50%}
        .lvp-brief区{flex:1 1 100%;flex-direction:column;width:100%}
      }`;
    document.head.appendChild(s);
    样式已注入.v = true;
}

// 冲突1 裁定A：本面板生成规划处是**重建式**写草稿（整份替换），必须带上节点级「禁用字幕」开关态，否则一回规划/编辑就静默重置。
// ⚠️ 只在真为 true 时携带该键：草稿缺键＝未勾过，写回后仍应保持缺键（规格 §10「不做迁移写入」），别往里落 `禁用字幕: false`。
function 开关补丁(草) { return 草?.禁用字幕 === true ? { 禁用字幕: true } : {}; }

// 上下文（由 状态栏面板.js 注入，均为延迟求值的 getter/回调）：
//   取节点()  → 当前绑定节点（未绑定为 null；⚠️ 每次用都要重新取，不得缓存）
//   状态      → 状态桥（读/写「剪辑选中段」；与节点时间轴的「选中段」解耦，item3）
//   应用规划(segments) → 框架层公共动作（覆盖确认 → 写时间轴 → 全刷）；本面板不再调用（透传剪辑时间轴的职责已随 剪辑 迁入 提示词时间轴页面板.js）
//   弹确认(标题,消息) → 二次确认框；同上，本面板不再使用
//   重渲染时间轴页() → 框架层跨页转发到 提示词时间轴页面板.重渲染（生成规划写草稿后整树重绘剪辑，避免子面板互 import）
export function 创建规划页面板(规划页, 上下文) {
    注入样式();
    const { 取节点, 状态, 重渲染时间轴页 } = 上下文;

    let 静态枚举已填 = false;   // 平台/钩子/任务 为代码常量（静态），仅首次装配填充一次

    // 左右分栏：左=素材区（规划素材区.js，设计 §3.3），右=brief 表单区
    const 分栏 = document.createElement("div");
    分栏.className = "lvp-规划分栏";
    规划页.appendChild(分栏);
    const 素材容器 = document.createElement("div");
    素材容器.className = "lvp-素材栏";
    分栏.appendChild(素材容器);
    const 素材区 = 创建规划素材区(素材容器, { 取节点 });
    const brief区 = document.createElement("div");
    brief区.className = "lvp-brief区";
    分栏.appendChild(brief区);
    // 一分为二（用户 2026-09-30）：左列＝表单（主题/字段网格/错误/回执），右列＝详细内容整块满高
    const 左列 = document.createElement("div"); 左列.className = "lvp-brief表单列"; brief区.appendChild(左列);
    const 右列 = document.createElement("div"); 右列.className = "lvp-brief内容列"; brief区.appendChild(右列);

    function brief行(父) { const d = document.createElement("div"); d.className = "lvp-brief行"; (父 || 左列).appendChild(d); return d; }
    function brief标(父, 文) { const l = document.createElement("label"); l.className = "lvp-brief标"; l.textContent = 文; 父.appendChild(l); return l; }
    function brief入(键, 标签, 占位, 值 = "") {
        const d = brief行(); brief标(d, 标签);
        const el = document.createElement("input"); el.className = "lvp-brief入"; el.type = "text"; el.placeholder = 占位; el.value = 值;
        d.appendChild(el); brief字段[键] = el; return el;
    }
    function 填下拉(el, 选项, 默认, 保留) {
        const 旧 = 保留 ? el.value : null;   // 保留=true 时记住重填前的选中值（用于动态枚举刷新不重置用户选择）
        el.innerHTML = "";
        (选项 || []).forEach((o) => { const op = document.createElement("option"); op.value = typeof o === "object" ? o.名 || o : o; op.textContent = typeof o === "object" ? o.名 || o : o; el.appendChild(op); });
        if (旧 != null && [...el.options].some((op) => op.value === 旧)) el.value = 旧;   // 旧值仍在新选项中 → 保留
        else if (默认 != null) el.value = 默认;
    }

    const brief字段 = {};
    // 主题（限宽，不再满宽铺满面板）
    brief入("主题", "主题*:", "例如：3 分钟看懂手冲咖啡");
    // 详细内容（大量详细要求，入草稿 brief 持久化；规划与提示词生成共用，设计 §3.3/§5.3）
    //   独占右列整块：右列＝标签行 + 满高内容框（contenteditable，@ 引用带背景色），其余表单全留在左列。
    const 内容头 = document.createElement("div"); 内容头.className = "lvp-brief行"; 右列.appendChild(内容头);
    brief标(内容头, "内容:");
    const 详细el = document.createElement("div"); 详细el.className = "lvp-brief详细"; 详细el.contentEditable = "true";
    详细el.dataset.ph = "详细要求：内容要点、必须出现的画面/台词、限制与禁忌…（输入 @ 可引用左侧规划素材）";
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
    // 排布（两列网格，自上而下）：②总时长|每段 ③段数（通栏 .跨） ④任务|钩子 ⑤语言|风格 ⑥平台|受众 ⑦技能|辅助 ⑧模型|生成规划
    const 时长格 = 网格格("总时长:");
    const 时长el = 入控("lvp-brief入", "number"); 时长el.value = 3; 时长el.min = 1; 时长el.max = 60; 时长格.appendChild(时长el);
    const 时长单位 = document.createElement("span"); 时长单位.className = "lvp-brief单位"; 时长单位.textContent = "分钟"; 时长格.appendChild(时长单位);
    brief字段.总时长 = 时长el;   // UI 按分钟输入，提交时 ×60 换算为秒（后端契约不变，仍 1..3600 秒）
    // 每段建议时长：范围字符串如 "5-8"，交给 LLM 控制分镜节奏，不做硬校验
    const 每段格 = 网格格("每段:"); 每段格.title = "每段建议时长(秒)，可填范围如 5-8，便于控制分镜节奏；仍受段时长 5~15 秒硬边界约束";
    const 每段el = 入控("lvp-brief入", "text"); 每段el.value = "5-8"; 每段格.appendChild(每段el);
    const 每段单位 = document.createElement("span"); 每段单位.className = "lvp-brief单位"; 每段单位.textContent = "秒"; 每段格.appendChild(每段单位);
    brief字段.每段建议时长 = 每段el;
    const 段数格 = 网格格("段数:"); 段数格.classList.add("跨");   // 通栏＝第三排只有段数（用户 2026-09-24 排布），输入框吃满整行不被提示挤窄
    const 限el = 入控("lvp-brief入", "number"); 限el.value = 0; 限el.min = 0; 限el.max = 120; 限el.style.maxWidth = "33.33%"; 段数格.appendChild(限el);   // UI 输入天花板 120；后端无固定上限（校验归一按 总时长//MIN_SEG 动态束段）
    const 段数提示 = document.createElement("span"); 段数提示.className = "lvp-brief单位"; 段数提示.textContent = "0=自动分配"; 段数提示.title = "0 表示按总时长自动分配段数"; 段数格.appendChild(段数提示);
    brief字段.段数上限 = 限el;
    const 任务el = 入控("lvp-brief选", "选"); 网格格("任务:").appendChild(任务el); brief字段.默认任务 = 任务el;
    const 钩el = 入控("lvp-brief选", "选"); 网格格("钩子:").appendChild(钩el); brief字段.钩子 = 钩el;
    // 语言枚举＝MiniMax H3 官方稳定支持的 11 种对白语言（GitHub MiniMax-AI/MiniMax-H3 README），各用母语自称
    const 言el = 入控("lvp-brief选", "选"); 填下拉(言el, ["中文", "English", "日本語", "한국어", "العربية", "Français", "Deutsch", "Italiano", "Português", "Русский", "Español"], "中文"); 网格格("语言:").appendChild(言el); brief字段.语言 = 言el;
    const 风格el = 入控("lvp-brief入", "text"); 风格el.placeholder = "电影感"; 网格格("风格:").appendChild(风格el); brief字段.风格 = 风格el;
    const 平台el = 入控("lvp-brief选", "选"); 网格格("平台:").appendChild(平台el); brief字段.平台 = 平台el;
    const 受众el = 入控("lvp-brief入", "text"); 受众el.placeholder = "新手"; 网格格("受众:").appendChild(受众el); brief字段.受众 = 受众el;
    // brief「技能」源＝根目录 Skills/（m.brief技能，与剪辑时间轴生成行技能 m.风格技能＝MiniMax-H3知识库 分家）；
    // brief「辅助」与技能同源 Skills/；生成行的技能/辅助仍用 MiniMax-H3知识库。选 不指定/无 = 不注入技能文档，走通用分镜
    const 技能el = 入控("lvp-brief选", "选"); 网格格("技能:").appendChild(技能el); brief字段.风格技能 = 技能el;
    const 辅助el = 入控("lvp-brief选", "选"); 网格格("辅助:").appendChild(辅助el); brief字段.辅助风格 = 辅助el;
    const brief错 = document.createElement("div"); brief错.className = "lvp-brief错"; 左列.appendChild(brief错);
    // 矮框档错误行只显示一行（CSS 省略号），完整文案挂 title，免得长文案换行把末两格挤出圆角框。
    const 报brief错 = (文本) => { brief错.textContent = 文本; brief错.title = 文本; };
    // A5：知识库来源回执（仅列实际进入请求的资料 + 截断/缺失回显）；来自 /lvp/plan 的 response.knowledge，
    // 非错误行故用常驻灰字，无回执则留空。样式走 `.lvp-brief回执`（原内联 cssText 无法被 :empty 收起）。
    const 来源回执 = document.createElement("div"); 来源回执.className = "lvp-brief回执"; 左列.appendChild(来源回执);
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
    // 模型下拉 + 生成按钮直接作为字段网格的最后一行（共用同一套列轨道 → 与上方左/右两列输入框
    // 逐像素对齐）。网格列用 minmax(0,1fr) 抵消 select 长选项的 min-content（1fr= minmax(auto,1fr)
    // 会被长选项撑宽左列）。模型清单来自 /lvp/llm_config
    const 模型sel = document.createElement("select"); 模型sel.className = "lvp-模型选"; 模型sel.title = "选择本次生成使用的 API 模型";
    网格格("").appendChild(模型sel);
    const 生成钮 = document.createElement("button"); 生成钮.className = "lvp-胶囊 lvp-生成"; 生成钮.type = "button"; 生成钮.textContent = "生成规划";
    生成钮.style.cssText = "background:var(--p-primary-color,#4a9eff);color:var(--p-primary-contrast-color,#fff);border-color:var(--p-primary-color,#4a9eff);flex:1";
    网格格("").appendChild(生成钮);

    // 暂存保留小数秒，换绑优先暂存；加载计划则只丢弃当前节点旧暂存。
    const 暂存 = new Map();
    let 暂存节点 = null;
    const 下拉默认 = { 平台: "抖音", 钩子: "悬念钩", 语言: "中文", 风格技能: "不指定", 辅助风格: "无", 默认任务: "t2v" };
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
    const 默认表单 = 采集brief();
    function 取编辑状态() {
        const brief = 采集brief();
        return { 有内容: Object.entries(brief).some(([键, 值]) => 值 !== 默认表单[键]), 签名: JSON.stringify(brief) };
    }
    function 采集brief() {
        return {
            主题: brief字段.主题.value.trim(), 详细内容: 提及.取文().trim(),
            平台: 读下拉("平台"), 语言: 读下拉("语言"),
            总时长: Number(((Number(brief字段.总时长.value) || 3) * 60).toFixed(9)),
            段数上限: Number(brief字段.段数上限.value) || 0,
            每段建议时长: brief字段.每段建议时长.value.trim(),   // 范围字符串（如 "5-8"），供 LLM 控制分镜节奏；空=不提
            钩子: 读下拉("钩子"),
            默认任务: 读下拉("默认任务"),
            风格: brief字段.风格.value.trim(), 受众: brief字段.受众.value.trim(),
            风格技能: 读下拉("风格技能"), 辅助风格: 读下拉("辅助风格"),
        };
    }
    function 设表单(brief) {
        const b = (brief && typeof brief === "object") ? brief : {};
        // 文本/数字：缺失回落构造默认（见上方 brief入/网格格 初值），保证换节点不残留
        brief字段.主题.value = b.主题 ?? "";
        提及.设文(b.详细内容 ?? "");   // 纯文本 → 框内 DOM（命中当前素材名的 `@名` 才 chip 化）
        brief字段.风格.value = b.风格 ?? "";
        brief字段.受众.value = b.受众 ?? "";
        brief字段.段数上限.value = b.段数上限 ?? 0;
        brief字段.每段建议时长.value = b.每段建议时长 ?? "5-8";
        brief字段.总时长.value = (Number(b.总时长) || 180) / 60;   // 秒→分钟（缺省 180s=3min）
        for (const [键, 默认] of Object.entries(下拉默认)) 设下拉(键, b[键] ?? 默认);
    }
    function 恢复brief(节点, 清除暂存 = false) {
        const 新id = 节点 ? String(节点.id) : null;
        if (暂存节点 && 暂存节点 !== 新id) 暂存.set(暂存节点, 采集brief());
        if (清除暂存) 暂存.delete(新id);
        const 草稿 = 节点 ? 真源.读剪辑草稿(节点) : null;
        设表单((新id && 暂存.get(新id)) || 草稿?.brief);   // 优先未提交暂存，其次草稿 brief
        素材区.刷新();   // 换绑/加载计划/清除暂存同路径：素材区随草稿重绘（全局素材/素材 由时间轴页写回，本页只读展示）
        提及.关();       // 换绑即收层：弹层里挂着上一节点的素材名会误导引用
        显示来源回执(null); 来源回执.style.color = "";   // 换绑即清上一节点的 A5 来源/A3 诊断回显，不留驻陈旧灰字
        暂存节点 = 新id;
    }

    let 生成中 = false;
    生成钮.onclick = async () => {
        if (生成中) return;
        if (状态.取("LLM请求在途")) { 报brief错("AI 生成提示词进行中，请等待完成后再发起规划"); return; }   // B3：跨入口互斥
        // ⚠️ 必须在两条早退校验**之前**清空：否则上一轮成功的来源回执会留在框里，与本轮「未绑定/主题为空」
        // 的错误行同时占位——矮框档底部余量只够一行信息，两行会把末两格挤出圆角框（且已无滚动兜底）。
        报brief错(""); 显示来源回执(null); 来源回执.style.color = "";
        const 节点 = 取节点();
        if (!节点) { 报brief错("请先绑定长视频规划师节点"); return; }
        const brief = 采集brief();
        brief.总时长 = Math.round(brief.总时长);   // 生成接口沿用整秒，表单暂存保留草稿的小数秒。
        if (模型sel.value) brief.模型id = 模型sel.value;   // 指定本次生成用哪个 API 模型（后端按 id 命中 api_models 临时切 opener，不写盘）
        const 请求体 = { ...brief };
        if (!请求体.详细内容) delete 请求体.详细内容;          // 缺省＝无键（不做迁移写入）
        const 素材清单 = 真源.读剪辑草稿(节点).素材 || [];
        if (素材清单.length) 请求体.素材 = 素材清单;
        if (!brief.主题) { 报brief错("主题不能为空"); return; }
        // 新一轮请求立即使旧响应失效，即使最终生成的 JSON 恰好相同。
        使节点快照失效(节点);
        const 快照 = 捕获节点快照(节点);
        生成中 = true;
        状态.设("LLM请求在途", true);   // B3：反向互斥——规划在途时「AI生成提示词」同样被挡
        生成钮.disabled = true; 生成钮.textContent = "规划中…";   // 错误行/来源回执已在入口清空
        try {
            const resp = await fetch("/lvp/plan", {
                method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(请求体),
            });
            const 数据 = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(数据?.error || `请求失败（${resp.status}）`);
            if (!Array.isArray(数据?.segments) || !数据.segments.length ||
                !数据.segments.every(s => s && typeof s === "object" && !Array.isArray(s))) {
                throw new Error("规划响应无有效段，未修改草稿，请重试");
            }
            // 两阶段流程：生成规划**先写草稿**（剪辑时间轴预演），不再直接写节点时间轴。
            // brief 快照随草稿存（剔除 模型id：它只作用于本次请求，不属草稿内容）。
            const 草brief = { ...brief }; delete 草brief.模型id;
            if (!草brief.详细内容) delete 草brief.详细内容;   // 缺省＝无键（不做迁移写入）
            const 已提交 = 提交节点快照(快照, 取节点(), (目标) => {
                // 新规划段均为全新实体：写入前就地补齐稳定 segment_id（A3），拖动/分割/保存往返据此保持身份。
                // 冲突1 裁定A：规划只换 brief/segments，「禁用字幕」是节点级开关态，跟节点走、不被静默重置；未勾过则保持无键。
                const 旧 = 真源.读剪辑草稿(目标);
                const 写 = { ...开关补丁(旧), brief: 草brief, segments: 分配段ID(数据.segments) };
                if (Array.isArray(旧.素材) && 旧.素材.length) 写.素材 = 旧.素材;                 // 段素材清单保留（编辑归提示词时间轴页）
                if (Array.isArray(数据.全局素材) && 数据.全局素材.length) 写.全局素材 = 数据.全局素材;   // 全局素材＝本轮新分配（无则不写键）
                真源.写剪辑草稿(目标, 写);
            });
            if (!已提交) { 报brief错("节点、草稿或请求已变化，已丢弃规划结果，请重试"); return; }
            暂存.delete(String(节点.id));   // 3.3(120)：已提交 → 草稿.brief 即真源，清除该节点未提交暂存
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
            报brief错(e.message || "规划失败");
        } finally {
            生成中 = false;
            状态.设("LLM请求在途", false);
            生成钮.disabled = false; 生成钮.textContent = "生成规划";
        }
    };

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
                填下拉(平台el, m.平台, "抖音");
                填下拉(钩el, m.钩子, "悬念钩");
                // 选项沿用节点中文标签，AI 规划始终默认 t2v，不跟随或修改执行节点已保存的任务。
                const 节点 = 取节点();
                const wOpts = 节点 ? 取widget(节点, "任务类型")?.options?.values : null;
                填下拉(任务el, wOpts?.length ? wOpts : 默认任务标签, "文生视频 t2v");
            }
            // brief「技能/辅助」均为动态枚举（源＝根目录 Skills/，后端 os.listdir 实时扫描），每次展开都刷新
            // 以反映用户新增/删除的技能文件夹；保留=true 保住用户已选值（仍在选项中）不被重置回默认。
            填下拉(技能el, m.brief技能, "不指定", true);
            填下拉(辅助el, ["无", ...(m.brief技能 || []).filter(名 => 名 !== "不指定" && 名 !== "无")], "无", true);
            已刷新 = true;
        } catch {} finally {
            枚举中--;
            if (已刷新) for (const [键, 值] of 待恢复下拉) 设下拉(键, 值);
        }
    }
    // 拉 API 模型清单填入下拉：值＝模型 id（生成时回传后端），文本＝名称（未配 Key 加标注）。
    // 默认选中：优先保留上次选择；否则生效模型（base_url+model 命中）；再否则首个。每次展开重拉以反映设置页新增/改 Key。
    async function 拉模型清单() {
        try {
            const cfg = await (await fetch("/lvp/llm_config")).json();
            const models = (cfg && cfg.models) || [];
            const 旧选 = 模型sel.value;
            模型sel.innerHTML = "";
            models.forEach((m) => {
                const o = document.createElement("option");
                o.value = m.id;
                o.textContent = m.has_key ? m.name : `${m.name}（未配置Key）`;
                模型sel.appendChild(o);
            });
            const 命中 = models.find((m) => m.base_url === cfg.base_url && m.model === cfg.model);
            if (models.some((m) => m.id === 旧选)) 模型sel.value = 旧选;
            else 模型sel.value = 命中 ? 命中.id : (models[0]?.id || "");
        } catch {}
    }

    // 设置页保存 API 模型配置成功后广播「长视频规划师_配置已存」→ 重拉下拉标注：配完 Key 无需
    // 手动折叠再展开状态栏即可刷新「未配置Key」标记（事件名字面量与 规划器设置.js 保存成功处镜像）。
    // 先 abort 上一轮再挂：否则重建后 window 上会累积僵尸监听器，其闭包持有已脱离 DOM 的旧
    // 模型sel，每次广播都白跑一遍（AbortController 是标准做法，不需要自己存/比对函数引用）。
    上轮监听?.abort();
    上轮监听 = new AbortController();
    window.addEventListener("长视频规划师_配置已存", 拉模型清单, { signal: 上轮监听.signal });

    // 绑定节点/换节点/加载计划时由框架层调用：恢复brief（含素材区刷新）；
    // 总时长 供状态栏面板跨页读写（UI 分钟 ↔ 契约秒）；重渲染 刷素材区（草稿素材键变化时）。
    return {
        恢复brief, 取编辑状态, 拉规划枚举, 拉模型清单,
        重渲染: () => { 素材区.刷新(); 提及.关(); },   // 草稿素材键变了：清单重绘，弹层同步收掉（旧行会引用已删素材）
        取总时长秒: () => Number(brief字段.总时长.value) * 60,
        设总时长秒: 秒 => {
            brief字段.总时长.value = 秒 / 60;
            const 节点 = 取节点();
            if (节点) { const id = String(节点.id); if (暂存.has(id)) 暂存.set(id, { ...暂存.get(id), 总时长: 秒 }); }
        },
    };
}
