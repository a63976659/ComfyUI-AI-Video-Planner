import { 取操作忙, 开始操作, 结束操作 } from "./操作锁.js";
// 状态栏面板 —— 框架层（通用内容 + 骨架 + 对外入口）。
//
// 三文件分工（2026-09-17 拆分，便于管理）：
//   状态栏面板.js（本文件）：样式注入单例（框架类 + 跨页共用基元 `.lvp-胶囊`）、标题「正在编辑」标记、
//       把手 + Tab 状态机、主体/三页容器、状态桥、当前节点、**应用规划**（时间轴页与编辑页共用的公共动作）、
//       绑定节点/展开/折叠/回填/全刷/设进度/设状态，以及 `创建状态栏面板` 这个对外入口。
//   编辑页面板.js：Tab「提示词编辑」页——参考区 + 提示词编辑器 + 右列（任务胶囊 + 首尾帧）、
//       刷新显隐、段级素材/共用/提示词/任务/帧 的读写。
//   规划页面板.js：Tab「AI规划」页——brief 表单（12 字段两列网格，行序见 09 §1.3）+ 生成按钮 +
//       段级规划字段（标题/结构/字幕，「结构」UI 标签对应数据键 职能）、拉规划枚举。
//   提示词时间轴页面板.js：Tab「提示词时间轴」页——剪辑时间轴＋单段精修（标题/结构/字幕/提示词），真源＝剪辑草稿。
//   规划素材区.js：AI规划页左列——规划期素材清单（草稿顶层 素材 键），不入节点全局参考素材池。
//
// 三页通过本文件注入的「上下文」访问共享态（取节点/状态/刷卡/渲染时间轴/全刷/应用规划/弹确认），
// 彼此不 import、不互调 —— 跨页动作一律走框架层，避免子面板之间形成耦合或循环依赖。
import { 真源, 捕获节点快照, 提交节点快照, 使节点快照失效 } from "./桥接/节点桥.js";
import { app } from "../../../scripts/app.js";
import { 创建状态桥 } from "./桥接/状态桥.js";
import { 创建编辑页面板 } from "./编辑页面板.js";
import { 创建规划页面板 } from "./规划页面板.js";
import { 创建提示词时间轴页面板 } from "./提示词时间轴页面板.js";
import { 创建视频制作页面板 } from "./视频制作页面板.js";
import { 准备H3填充 } from "./制作数据.js";
import { 任务码 } from "./生成类型选择.js";
import { 上限 as 槽位上限 } from "./参考文件区.js";   // 复用编辑页槽位真源，映射段素材 截断与之同源

const 样式已注入 = { v: false };
const 节点显示名 = "长视频规划师";
const 编辑后缀 = "（正在编辑）";
const 剥离编辑 = (t) => ((t || "").endsWith(编辑后缀) ? (t || "").slice(0, -编辑后缀.length) : (t || ""));
// 「正在编辑」标题标的加/去（均幂等）：加=剥离后重拼、去=剥离还原；保留用户自定义标题。
const 加编辑标 = (n) => { if (n) n.title = (剥离编辑(n.title) || 节点显示名) + 编辑后缀; };
const 去编辑标 = (n) => { if (n) n.title = 剥离编辑(n.title) || 节点显示名; };
// 框架类（状态栏/把手/主体/Tab/页面/标题/状态条）+ **跨页共用基元** `.lvp-胶囊`。
// `.lvp-胶囊` 留在此处而非某个子面板：参考区、生成类型选择、提示词工具行、计划数据（编辑页）
// 与规划页生成钮五处都在用它；本样式块必然最先注入（创建状态栏面板 首行），子面板的覆写类
// （如 `.lvp-生成`）后注入 → 层叠胜负关系与拆分前逐字一致。
function 注入样式() {
    if (样式已注入.v) return;
    const s = document.createElement("style");
    s.textContent = `
      .lvp-状态栏{display:flex;flex-direction:column;font:11px system-ui;color:var(--fg-color,#ddd)}
      .lvp-把手{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:2px 10px;cursor:pointer;user-select:none;background:var(--comfy-menu-bg,#2b2b2b);border-radius:8px}
      /* 宿主 grid 的 auto 行没有确定高度；显式夹取限制画布占用，260px 是布局上限而非内容最小高度。 */
      .lvp-主体{display:none;padding:0;background:var(--comfy-menu-secondary-bg,#232323);border-top:1px solid var(--border-color,#3a3a3a);height:clamp(225px,26vh,260px);overflow:hidden}
      .lvp-主体.展开{display:flex;flex-direction:column}
      .lvp-把手标签{display:flex;align-items:center;gap:2px;flex:1}
      .lvp-把手标签 .lvp-tab{flex:1;text-align:center;padding:2px 14px;cursor:pointer;border:none;background:transparent;color:var(--p-text-muted-color,#8c8c8c);font:11px system-ui;border-radius:6px;position:relative;overflow:hidden;transition:background .15s,color .15s}
      .lvp-把手标签 .lvp-tab:hover{color:var(--fg-color,#ddd)}
      .lvp-把手标签 .lvp-tab.激活{background:var(--comfy-input-bg,#2f2f2f);color:var(--fg-color,#ddd)}
      .lvp-页面{display:none;flex:1;gap:6px;padding:6px;align-items:stretch;overflow:auto}
      .lvp-页面,.lvp-页面 :is(textarea,.lvp-规划分栏,.lvp-brief表单列,.lvp-brief详细,
        .lvp-参考,.lvp-素材框,.lvp-右列,.lvp-编辑区,.lvp-精修区,.lvp-ct-卷,
        .lvp-制作列,.lvp-制作列表,.lvp-制作报告){overscroll-behavior-y:contain}
      .lvp-页面.激活{display:flex;flex-wrap:nowrap}
      .lvp-胶囊{padding:2px 8px;border:1px solid var(--border-color,#444);border-radius:10px;background:var(--comfy-input-bg,#2f2f2f);color:var(--fg-color,#ccc);cursor:pointer}
      .lvp-胶囊.激活{background:var(--p-primary-color,#4a9eff);color:var(--p-primary-contrast-color,#fff);border-color:var(--p-primary-color,#4a9eff)}
      .lvp-标题{flex:0 0 160px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .lvp-状态{color:var(--p-text-muted-color,#8c8c8c);flex:0 0 160px;text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}`;
    document.head.appendChild(s);
    样式已注入.v = true;
}

export function 创建状态栏面板(底栏) {
    注入样式();

    function toast(消息, severity = "info") { app?.ui?.toast?.showMessage?.({ message: 消息, severity }); }
    // 二次确认（库约定，D8）：优先 ComfyUI 原生框，宿主未提供时退回 window.confirm。
    async function 弹确认(标题, 消息) {
        const 框 = app?.extensionManager?.dialog;
        if (框?.confirm) { try { return !!(await 框.confirm({ title: 标题, message: 消息 })); } catch { return false; } }
        return window.confirm(`${标题}\n\n${消息}`);
    }
    const 根 = document.createElement("div");
    根.className = "lvp-状态栏";

    const 把手 = document.createElement("div");
    把手.className = "lvp-把手";
    const 把手标题 = document.createElement("span");
    把手标题.className = "lvp-标题";
    把手标题.textContent = "🎬 长视频规划师（展开）";
    const 状态条 = document.createElement("span");
    状态条.className = "lvp-状态";
    状态条.textContent = "";
    // Tab 按钮（嵌入把手行）
    const 左区 = document.createElement("div");
    左区.className = "lvp-把手标签";
    const tab规划 = document.createElement("button");
    tab规划.className = "lvp-tab 激活"; tab规划.type = "button"; tab规划.textContent = "AI规划";
    const tab时间轴 = document.createElement("button");
    tab时间轴.className = "lvp-tab"; tab时间轴.type = "button"; tab时间轴.textContent = "提示词时间轴";
    const tab编辑 = document.createElement("button");
    tab编辑.className = "lvp-tab"; tab编辑.type = "button"; tab编辑.textContent = "提示词编辑";
    const tab制作 = document.createElement("button");
    tab制作.className = "lvp-tab"; tab制作.type = "button"; tab制作.textContent = "视频制作";
    左区.append(tab规划, tab时间轴, tab编辑, tab制作);
    把手.append(把手标题, 左区, 状态条);

    const 主体 = document.createElement("div");
    主体.className = "lvp-主体";

    // 三个页面容器
    const 编辑页 = document.createElement("div");
    编辑页.className = "lvp-页面";
    const 规划页 = document.createElement("div");
    规划页.className = "lvp-页面 lvp-规划页 激活";   // 3.3(122)：lvp-规划页 作为窄面板容器查询根（container-type 由 规划页面板.js 注入）
    const 时间轴页 = document.createElement("div");
    时间轴页.className = "lvp-页面 lvp-时间轴页";
    const 制作页 = document.createElement("div");
    制作页.className = "lvp-页面 lvp-视频制作页";

    主体.append(编辑页, 规划页, 时间轴页, 制作页);
    根.append(把手, 主体);

    // Tab 切换逻辑（表驱动：点击当前激活Tab=折叠，点击其它Tab=切换+展开）
    const 页表 = { 规划: [tab规划, 规划页], 时间轴: [tab时间轴, 时间轴页], 编辑: [tab编辑, 编辑页], 制作: [tab制作, 制作页] };
    function 切Tab(目标) {
        for (const [名, [钮, 页]] of Object.entries(页表)) {
            钮.classList.toggle("激活", 名 === 目标);
            页.classList.toggle("激活", 名 === 目标);
        }
        制作页面板.设激活(目标 === "制作");
    }
    function 折叠() { 状态.设("展开", false); 主体.classList.remove("展开"); 把手标题.textContent = "🎬 长视频规划师（展开）"; 去编辑标(当前节点); 制作页面板.设激活(false); }
    // Tab 点击统一状态机：
    //   激活+展开 → 折叠；激活+折叠 → 重新展开同页；非激活 → 切到目标页并展开。
    function 点击Tab(目标) {
        const [钮] = 页表[目标];
        if (钮.classList.contains("激活") && 状态.取("展开")) { 折叠(); return; }
        切Tab(目标);
        展开();
    }
    tab规划.onclick = () => 点击Tab("规划");
    tab时间轴.onclick = () => 点击Tab("时间轴");
    tab编辑.onclick = () => 点击Tab("编辑");
    tab制作.onclick = () => 点击Tab("制作");

    底栏.appendChild(根);

    // 🔒 item3 解耦：选中段＝节点时间轴（时间轴面板.js）的选中键；剪辑选中段＝剪辑时间轴（规划页草稿）
    // 的选中键。两键独立，避免点一侧高亮/回填另一侧（详 回填 拆分与下方订阅路由）。
    const 状态 = 创建状态桥({ 展开: false, 选中段: 0, 剪辑选中段: 0 });
    let 当前节点 = null;
    let 时间轴刷卡 = null;   // 时间轴挂载时注册；状态栏编辑段内容后回调它，局部刷新对应段卡
    let 时间轴渲染 = null;   // 时间轴挂载时注册；计划数据加载后回调它，整树重建时间轴

    // 共享上下文：全部为延迟求值的 getter/回调（不传值、不传引用），子面板每次用时重新取，
    // 因此 `当前节点` 重绑、时间轴后挂载都不会让子面板拿到过期对象。
    function 取存活节点() {
        const 图 = 当前节点?.graph;
        const 工作流 = app.rootGraph ?? app.graph;
        // 面板可能尚未重绑；旧工作流对象仍存活也不能继续写入。
        return 图 && (图.rootGraph ?? 图) === (工作流?.rootGraph ?? 工作流) &&
            图.getNodeById?.(当前节点.id) === 当前节点 ? 当前节点 : null;
    }
    const 上下文 = {
        取节点: 取存活节点,
        状态,
        刷卡: (i) => 时间轴刷卡?.(i),
        渲染时间轴: () => 时间轴渲染?.(),
        全刷: () => 全刷(),
        计划已加载: () => 计划已加载(),
        取规划编辑状态: () => 规划页面板.取编辑状态(),
        取规划总时长: () => 规划页面板.取总时长秒(),
        设规划总时长: (秒) => 规划页面板.设总时长秒(秒),
        应用规划: (segments) => 应用规划(segments),
        取填充段: (segments, 草) => 映射段素材(segments, 草),
        弹确认: (标题, 消息) => 弹确认(标题, 消息),   // 剪辑时间轴 填充节点/生成失败 复用同一确认框
        重渲染时间轴页: () => { 时间轴页面板.重渲染(); 制作页面板.重渲染(); },   // 规划页生成写草稿后整树重绘剪辑与制作
        恢复规划界面: () => { 规划页面板.恢复brief(取存活节点(), true); 制作页面板.重渲染(); },
    };
    const 编辑页面板 = 创建编辑页面板(编辑页, 上下文);
    const 规划页面板 = 创建规划页面板(规划页, 上下文);
    const 时间轴页面板 = 创建提示词时间轴页面板(时间轴页, 上下文);
    const 制作页面板 = 创建视频制作页面板(制作页, 上下文);

    // 草稿 使用素材/全局素材 → 段 refs（设计 2026-09-29 §6）：按类型表拆写 图片/视频/音频（值＝媒体文件名数组，
    // 与 编辑页面板.写段素材 refs.图片 同构）；「文本」类不进段；无素材键草稿＝原行为，待填段逐字原样写入。
    function 映射段素材(待填, 草, 截断 = true) {
        const 类型 = new Map(((草 && 草.素材) || []).map((m) => [m.名, m.类型]));
        const 全局 = (草 && 草.全局素材) || [];
        return 待填.map((s) => {
            const { 使用素材, ...副 } = s;   // 使用素材 属草稿层键，不落时间轴段
            const 名组 = [...new Set([...(使用素材 || []), ...全局])];
            const 入 = { 图片: [], 视频: [], 音频: [] };
            for (const 名 of 名组) {
                const 型 = 类型.get(名);
                if (型 === "图像") 入.图片.push(名);
                else if (型 === "视频") 入.视频.push(名);
                else if (型 === "音频") 入.音频.push(名);
            }
            if (!截断) for (const 型 of ["图片", "视频", "音频"]) {
                const 旧值 = s.refs?.[型];
                const 旧组 = typeof 旧值 === "string" ? [旧值] : Array.isArray(旧值) ? 旧值 : [];
                入[型] = [...new Set([...旧组, ...入[型]])];
            }
            // 超槽位上限按 图9/视3/音3 截断，与编辑页满额守卫及执行层 解析槽位 同源，防映射绕过上限致显示溢出/静默丢弃不一致
            if (截断) {
                入.图片 = 入.图片.slice(0, 槽位上限.图片);
                入.视频 = 入.视频.slice(0, 槽位上限.视频);
                入.音频 = 入.音频.slice(0, 槽位上限.音频);
            }
            if (入.图片.length + 入.视频.length + 入.音频.length) 副.refs = { ...(s.refs || {}), ...入 };
            return 副;
        });
    }

    // 应用规划：两页共用的公共动作（时间轴页剪辑 / 编辑页提示词编辑器回调都走这里）。
    let 应用中 = false;
    async function 应用规划(segments) {
        if (应用中) return;
        if (取操作忙(状态)) { toast("当前操作进行中，请等待完成后再应用", "warn"); return; }   // B3：写时间轴会作废流式批基线
        const 节点 = 取存活节点();
        if (!节点) { toast("请先绑定长视频规划师节点", "error"); return; }
        if (!Array.isArray(segments) || !segments.length) { toast("规划结果为空", "error"); return; }
        const 快照 = 捕获节点快照(节点, ["剪辑草稿", "时间轴数据"]);
        const 待填 = JSON.parse(JSON.stringify(segments));
        const 草稿快 = 真源.读剪辑草稿(节点);
        let 填段;
        try {
            填段 = 草稿快.brief?.执行后端 === "通用工作流"
                ? 准备H3填充(映射段素材(待填, 草稿快, false), 草稿快, 任务码(真源.读任务类型(节点)), 槽位上限)
                : 映射段素材(待填, 草稿快);
        } catch (e) { toast(e.message, "error"); return; }
        const 现有 = 真源.读时间轴(节点).segments || [];
        const 令牌 = 开始操作(状态, "填充节点");
        if (!令牌) return;
        应用中 = true;
        try {
            if (现有.length > 0) {
                const ok = await 弹确认("覆盖时间轴", `将用 ${待填.length} 段新规划覆盖当前 ${现有.length} 段，继续？`);
                if (!ok) return;   // 取消不动真源
            }
            const 已提交 = 提交节点快照(快照, 取存活节点(), (目标) => {
                真源.写时间轴(目标, { segments: 填段 });
                // 新段缺少素材字段时会回退全局池，不能继承旧时间轴的素材与共用状态。
                真源.写参考素材(目标, { 图片: [], 音频: [], 视频: [] });
                真源.写参考共用(目标, false);
                // 运行选择（旧索引覆盖表）优先于段内 run；换全新时间轴后旧表指向的是已不存在的段，
                // 必须同快照原子清空，否则实际运行段与新界面不一致（取消/快照失效时回调不执行，两值都不动）。
                真源.写运行选择(目标, {});
            });
            if (!已提交) { toast("节点、草稿或时间轴已变化，已取消填充，请重试", "warn"); return; }
            状态.设("选中段", 0);
            全刷();   // 回填 + 时间轴整树重建
        } finally {
            应用中 = false;
            结束操作(状态, 令牌);
        }
    }

    function 绑定节点(node) {
        // 换出再切回同一实例也不可恢复旧请求；同实例重绑同样保守失效。
        使节点快照失效(当前节点);
        if (当前节点 && 当前节点 !== node) 去编辑标(当前节点);
        当前节点 = node;
        制作页面板.绑定节点(node);
        // 广播换绑：各节点内嵌时间轴据此切换选中数据源（绑定读全局「选中段」/非绑定读本地）并重刷高亮，
        // 避免换节点编辑后旧绑定节点高亮残留、新绑定节点未同步全局选中。
        状态.设("绑定节点", node);
        // 「正在编辑」跟随展开态、且只标当前所选节点：展开才加标，折叠不加；
        // 多节点时其余节点一律无标（切换时已剥旧标），保证同时最多一个「正在编辑」。
        if (状态.取("展开")) 加编辑标(node); else 去编辑标(node);
        时间轴页面板.重渲染(); 规划页面板.重渲染();   // 前者整树重建剪辑，后者刷新素材区（换节点 → 剪辑草稿真源变了，否则重载后已存草稿显示为空态、工具钮全灰；对标节点内嵌 时间轴面板 onConfigure→渲染）
        规划页面板.恢复brief(node);   // 3.3(120)：换绑才恢复左列 brief（含未提交暂存），不随段选中刷新
        回填();
    }

    // 回填拆两半（item3 解耦）：编辑页吃**节点时间轴**[选中段]，规划页吃**剪辑草稿**[剪辑选中段]，
    // 两键独立 → 点剪辑卡不刷编辑页、点节点卡不刷规划页。回填() 仅用于需同刷两页的场合
    // （绑定节点/展开/全刷）；日常选中变化走下方按键路由的订阅，各刷各页。
    function 回填编辑页() {
        // 无绑定节点时也渲染默认（t2v）界面，使「未加节点展开」与「加节点并绑定后」外观一致。
        const tl = 当前节点 ? 真源.读时间轴(当前节点) : { segments: [] };
        const 段组 = tl.segments || [];
        const seg = 段组[状态.取("选中段")] || {};
        编辑页面板.回填(当前节点, seg, 段组);
    }
    function 回填时间轴页() {
        const 草稿 = 当前节点 ? 真源.读剪辑草稿(当前节点) : { brief: {}, segments: [] };
        const 草稿段 = (草稿.segments || [])[状态.取("剪辑选中段")] || {};
        时间轴页面板.回填(草稿段);
    }
    function 回填() { 回填编辑页(); 回填时间轴页(); }

    function 展开() {
        状态.设("展开", true); 主体.classList.add("展开"); 把手标题.textContent = "🎬 长视频规划师（收起）";
        加编辑标(当前节点);   // 展开 → 当前所选节点标题显示「正在编辑」（无绑定节点时 no-op）
        制作页面板.设激活(tab制作.classList.contains("激活"));
        // 重拉画风/预设清单：用户可能在上次展开后往 预设/ 里新增了 txt。
        // 异步响应回来时会按回填设好的上次文本重新反解析，不会错选。
        编辑页面板.刷新画风预设();
        编辑页面板.刷新计划列表();   // 重拉计划清单（用户可能在上次展开后手动往 计划数据/ 里放了 JSON）
        规划页面板.拉规划枚举();
        时间轴页面板.拉枚举();
        回填();
    }
    // 把手不再整体监听点击：Tab 按钮各自处理切换/折叠（避免事件冒泡双重触发）

    function 设进度(v, m, 信息 = null) {
        // 3.1(98)：与后端两阶段进度模型对齐（max=2×段列表长度）：
        //   • 阶段=完成 → “完成”（overall 收尾，面板取回成品的信号）
        //   • 阶段=采样/解码 → “采样 3/7·段 4（总 3/14）”，同时展示阶段小进度与总体进度
        //   • 无阶段（旧 payload/向后兼容） → “生成中 v/m”，同旧行为
        if (v == null || !m) return;
        const 阶段 = 信息?.stage;
        if (阶段 === "完成") { 状态条.textContent = "完成"; return; }
        if (阶段 === "采样" || 阶段 === "解码") {
            const 已 = 信息.stage_done ?? "?";
            const 段总 = 信息.stage_total ?? "?";
            const 段号 = 信息.segment ? `·段 ${信息.segment}` : "";
            状态条.textContent = `${阶段} ${已}/${段总}${段号}（总 ${v}/${m}）`;
            return;
        }
        状态条.textContent = `生成中 ${v}/${m}`;
    }
    function 设状态(文本) { 状态条.textContent = 文本; }

    function 计划已加载() {
        规划页面板.恢复brief(当前节点, true);
        const 段数 = 真源.读剪辑草稿(当前节点).segments?.length || 0;
        状态.设("剪辑选中段", Math.max(0, Math.min(状态.取("剪辑选中段"), 段数 - 1)));
        时间轴页面板.重渲染(); 规划页面板.重渲染();
        全刷();
    }

    // 普通刷新不恢复 brief，避免覆盖尚未提交的表单编辑。
    function 全刷() {
        if (当前节点) {
            const tl = 真源.读时间轴(当前节点);
            const 段数 = Array.isArray(tl?.segments) ? tl.segments.length : 0;
            if (状态.取("选中段") >= 段数) 状态.设("选中段", Math.max(0, 段数 - 1));
        }
        回填();
        时间轴渲染?.();
        制作页面板.重渲染();
    }

    // 重置只清目标节点的暂存；换绑时按既有路径保存另一节点尚未提交的需求。
    function 重置节点界面(node) {
        规划页面板.清除节点暂存(node);
        绑定节点(node);
        状态.设("选中段", 0); 状态.设("剪辑选中段", 0);
        规划页面板.重置(node);
        编辑页面板.重置(); 时间轴页面板.重置();
        切Tab("规划"); 制作页面板.重置(node);
        for (const 页 of [规划页, 时间轴页, 编辑页, 制作页]) 页.scrollTop = 0;
        设状态(""); 回填();
    }
    function 恢复节点界面(node) {
        规划页面板.清除节点暂存(node);
        if (当前节点 !== node) return;
        规划页面板.重置(node); 时间轴页面板.重渲染();
        制作页面板.绑定节点(node); 回填(); 设状态("");
    }

    // 供时间轴面板联动选中段（item3 解耦：两键各自只刷对应页，互不触发）
    状态.订阅((键) => { if (键 === "选中段") 回填编辑页(); else if (键 === "剪辑选中段") 回填时间轴页(); });
    // 事件名字面量仍与 规划器设置.js 的 dispatchEvent 镜像，由 测试_常量同步.py 锁（扫描目标已同步）。

    return {
        绑定节点, 展开, 收起: 折叠, 设进度, 设状态, 回填, 状态, 取节点: 取存活节点,
        重置节点界面, 恢复节点界面,
        取重置签名: node => 当前节点 === node ? 规划页面板.取编辑状态().签名 : null,
        取重置阻止原因: node => 取操作忙(状态) ? "当前操作正在进行，请先停止或等待完成"
            : (当前节点 === node && 时间轴页面板.取忙()) ? "当前剪辑操作尚未结束，请先关闭弹窗或等待完成"
            : 制作页面板.取重置阻止原因(node),
        刷新制作: () => 制作页面板.重渲染(),
        刷新编辑历史: () => 时间轴页面板.重渲染(),
        设时间轴刷卡: (fn) => { 时间轴刷卡 = fn; },
        设时间轴渲染: (fn) => { 时间轴渲染 = fn; },
        销毁: () => { 制作页面板.销毁(); 根.remove(); },
    };
}
