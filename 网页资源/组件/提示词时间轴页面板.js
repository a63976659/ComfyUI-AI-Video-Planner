import { 取操作忙 } from "./操作锁.js";
import { 真源 } from "./桥接/节点桥.js";
import { 创建剪辑时间轴 } from "./剪辑时间轴.js";
import { 保护台词提示词 } from "./台词时长.js";

// 提示词时间轴页（Tab「提示词时间轴」）：左=剪辑时间轴（草稿预演编辑器，宽度与拆分前一致），
// 右=单段精修区（标题/结构/台词/提示词，写剪辑草稿 active 段；「结构」为 UI 标签、数据键仍 职能）。
// 自 规划页面板.js 迁出；与 brief 的唯一跨页耦合（总时长）经框架层上下文 取/设规划总时长 转发。
const 样式已注入 = { v: false };
function 注入样式() {
    if (样式已注入.v) return;
    const s = document.createElement("style");
    s.textContent = `
      .lvp-时间轴页{container-type:inline-size;container-name:lvp-时间轴页}
      .lvp-时间轴剪辑{flex:0 0 calc(100% - 452px);min-width:0;display:flex}
      .lvp-精修区{display:flex;flex-direction:column;gap:4px;flex:1 1 444px;min-width:268px;min-height:0;overflow-y:auto;align-self:stretch;box-sizing:border-box;background:var(--comfy-menu-bg,#2b2b2b);padding:6px;border-radius:8px}
      .lvp-精修区>.lvp-右行,.lvp-精修首行{flex-shrink:0}
      .lvp-精修首行{display:flex;gap:8px;min-width:0}
      .lvp-精修首行>.lvp-右行{flex:1 1 0;min-width:0;max-width:270px}
      .lvp-精修首行 .lvp-brief标{flex:0 0 auto}
      .lvp-精修首行 input,.lvp-精修首行 select{flex:1 1 0;width:0;min-width:0;max-width:220px}
      .lvp-精修首行 input{max-width:200px}
      .lvp-右行{display:flex;gap:4px;align-items:center}
      .lvp-右行.高{flex:1;align-items:stretch}
      .lvp-右行.高 .lvp-brief标{align-self:flex-start}
      .lvp-台词入{flex:1;min-width:0;background:var(--comfy-input-bg,#1c1c1c);color:inherit;border:1px solid var(--border-color,#444);border-radius:4px;font:11px system-ui;padding:3px 5px}
      .lvp-提示词入{flex:1;resize:vertical;background:var(--comfy-input-bg,#1c1c1c);color:var(--fg-color,#ddd);border:1px solid var(--border-color,#444);border-radius:4px;font:11px system-ui;padding:3px 5px;min-height:64px}
      @container lvp-时间轴页 (max-width:480px){.lvp-精修区{display:none}.lvp-时间轴剪辑{flex:1 1 auto}}`;
    document.head.appendChild(s);
    样式已注入.v = true;
}

// 与 规划页面板 同名小函数保持两份各文件自持：禁用字幕保态契约由 测试_提示词生成/台词时长 锁，跨页面板禁止互 import（架构铁律）
function 开关补丁(草) { return 草?.禁用字幕 === true ? { 禁用字幕: true } : {}; }

export function 创建提示词时间轴页面板(时间轴页, 上下文) {
    注入样式();
    const { 取节点, 状态, 应用规划, 弹确认, 取规划总时长, 设规划总时长 } = 上下文;

    let 角色表 = [];
    const 剪辑容器 = document.createElement("div");
    剪辑容器.className = "lvp-时间轴剪辑";
    时间轴页.appendChild(剪辑容器);
    const 剪辑 = 创建剪辑时间轴(剪辑容器, {
        取节点, 状态, 应用规划, 弹确认,
        取规划总时长,
        恢复规划界面: 上下文.恢复规划界面,
        取填充段: 上下文.取填充段,
        同步台词总时长: 总时长 => 设规划总时长(总时长),
        回填当前段: () => 回填((真源.读剪辑草稿(取节点()).segments || [])[状态.取("剪辑选中段")] || {}),
    });

    // 单段精修区：台词与提示词独立编辑，提示词占用剩余高度
    const 精修区 = document.createElement("div");
    精修区.className = "lvp-精修区";
    function 右行(标签, 高, 父 = 精修区) {
        const 盒 = document.createElement("div"); 盒.className = "lvp-右行" + (高 ? " 高" : "");
        const 标 = document.createElement("span"); 标.className = "lvp-brief标"; 标.textContent = 标签 + ":";
        盒.appendChild(标); 父.appendChild(盒); return 盒;
    }
    const 首行 = document.createElement("div"); 首行.className = "lvp-精修首行"; 精修区.appendChild(首行);
    const 标题el = document.createElement("input"); 标题el.className = "lvp-brief入"; 标题el.type = "text";
    右行("标题", false, 首行).appendChild(标题el); 标题el.onchange = () => 写选中段规划({ 标题: 标题el.value });
    const 角色sel = document.createElement("select"); 角色sel.className = "lvp-brief选";
    // UI 标签「结构」（2026-09-21 改名，仅前端文案）；数据键仍「职能」（含 职能色），后端契约不变
    右行("结构", false, 首行).appendChild(角色sel); 角色sel.onchange = () => 写选中段规划({ 职能: 角色sel.value, 职能色: 角色到色(角色sel.value) });
    const 台词el = document.createElement("input"); 台词el.type = "text"; 台词el.className = "lvp-台词入";
    台词el.placeholder = "填写本段需要朗读的台词或旁白";
    右行("台词／旁白").appendChild(台词el);
    let 回填段 = {};
    台词el.onchange = () => 写选中段规划({ 台词: 台词el.value, 台词参与估时: !!台词el.value.trim() });
    const 提示词el = document.createElement("textarea"); 提示词el.className = "lvp-提示词入";
    右行("提示词", true).appendChild(提示词el); 提示词el.onchange = () => 写选中段规划({ prompt: 提示词el.value });
    时间轴页.appendChild(精修区);
    function 角色到色(名) {
        if (!名) return "";
        return 角色表.find(r => r.名 === 名)?.色
            || (回填段.职能 === 名 ? 回填段.职能色 : "")
            || (真源.读剪辑草稿(取节点()).segments || []).find(s => s.职能 === 名 && s.职能色)?.职能色
            || "#8c8c8c";
    }

    function 刷结构选项() {
        const 当前名 = typeof 回填段.职能 === "string" ? 回填段.职能 : "";
        const 名称 = new Set(角色表.map(r => r.名));
        // 自定义结构来自当前草稿，切换节点时不会把其他计划的名称带过来。
        for (const 段 of 真源.读剪辑草稿(取节点()).segments || []) {
            if (typeof 段.职能 === "string" && 段.职能.trim()) 名称.add(段.职能);
        }
        if (当前名) 名称.add(当前名);
        角色sel.textContent = "";
        for (const 名 of ["", ...名称]) {
            const o = document.createElement("option");
            o.value = 名; o.textContent = 名 || "未设置";
            角色sel.appendChild(o);
        }
        角色sel.value = 当前名;
    }

    // 编辑**草稿** active 段（边界铁律 C3：草稿的结构/内容编辑集中在剪辑链路页面）
    function 写选中段规划(patch) {
        const 节点 = 取节点();
        if (!节点) return;
        if (取操作忙(状态)) { 回填((真源.读剪辑草稿(节点).segments || [])[状态.取("剪辑选中段")] || {}); return; }
        const 草 = 真源.读剪辑草稿(节点);
        const 段组 = 草.segments || [];
        const i = 状态.取("剪辑选中段");
        if (!段组[i]) return;
        Object.assign(段组[i], patch);
        if (Object.hasOwn(patch, "台词")) {
            delete 段组[i].配音计时;
            if (段组[i].refs) delete 段组[i].refs.台词配音;
            Object.assign(段组[i], 保护台词提示词(段组[i]));
        }
        const 写 = { ...草, ...开关补丁(草), brief: 草.brief || {}, segments: 段组 };
        if (Array.isArray(草.素材) && 草.素材.length) 写.素材 = 草.素材;         // 保态携带（冲突1 同口径）
        if (Array.isArray(草.全局素材) && 草.全局素材.length) 写.全局素材 = 草.全局素材;
        // 新规划扩展随手工精修保留；不改变 H3 提示词的请求或改写逻辑。
        if (草.规划资料) 写.规划资料 = 草.规划资料;
        if (草.规划历史) 写.规划历史 = 草.规划历史;
        真源.写剪辑草稿(节点, 写);
        剪辑.渲染();
        回填(段组[i]);
    }

    function 刷编辑锁() {
        const 锁定 = 取操作忙(状态);
        for (const 控件 of [标题el, 角色sel, 台词el, 提示词el]) {
            控件.disabled = 锁定;
            控件.title = 锁定 ? "当前操作使用点击时的数据；完成或停止后可编辑" : "";
        }
    }
    状态.订阅(键 => { if (键 === "统一操作锁" || 键 === "LLM请求在途") {
        回填((真源.读剪辑草稿(取节点()).segments || [])[状态.取("剪辑选中段")] || {});
    } });
    刷编辑锁();

    function 回填(seg) {
        刷编辑锁();
        回填段 = seg;
        标题el.value = seg.标题 || ""; 提示词el.value = seg.prompt || "";
        刷结构选项();
        台词el.value = typeof seg.台词 === "string" ? seg.台词 : "";
        剪辑.刷active();
    }

    // 本页加载结构枚举，模型选择由配置页管理。
    let 角色已建 = false;
    async function 拉枚举() {
        try {
            const 响应 = await fetch("/lvp/plan_meta");
            if (!响应.ok) return;
            const m = await 响应.json();
            if (!角色已建) {
                if (!Array.isArray(m.职能) || !m.职能.length) return;
                角色表 = m.职能.filter(r => typeof r?.名 === "string" && r.名.trim());
                if (!角色表.length) return;
                角色已建 = true;
                // 请求期间可能已切换镜头；恢复最新回填值，而不是请求发起时的值。
                刷结构选项();
            }
        } catch {}
    }
    return { 回填, 重渲染: () => 剪辑.渲染(), 拉枚举,
        取忙: () => 剪辑.取忙(), 重置: () => { 剪辑.重置视图(); 回填({}); } };
}
