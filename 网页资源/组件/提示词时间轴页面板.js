import { 真源 } from "./桥接/节点桥.js";
import { 创建剪辑时间轴 } from "./剪辑时间轴.js";

// 提示词时间轴页（Tab「提示词时间轴」）：左=剪辑时间轴（草稿预演编辑器，宽度与拆分前一致），
// 右=单段精修区（标题/结构/字幕/提示词，写剪辑草稿 active 段；「结构」为 UI 标签、数据键仍 职能）。
// 自 规划页面板.js 迁出；与 brief 的唯一跨页耦合（总时长）经框架层上下文 取/设规划总时长 转发。
const 样式已注入 = { v: false };
let 上轮监听 = null;   // 面板重建时摘上一轮 window 监听（同 规划页面板 模式）
function 注入样式() {
    if (样式已注入.v) return;
    const s = document.createElement("style");
    s.textContent = `
      .lvp-时间轴页{container-type:inline-size;container-name:lvp-时间轴页}
      .lvp-时间轴剪辑{flex:0 0 calc(100% - 452px);min-width:0;display:flex}
      .lvp-精修区{display:flex;flex-direction:column;gap:4px;flex:1 1 444px;min-width:268px;align-self:stretch;box-sizing:border-box;background:var(--comfy-menu-bg,#2b2b2b);padding:6px;border-radius:8px}
      .lvp-右行{display:flex;gap:4px;align-items:center}
      .lvp-右行.高{flex:1;align-items:stretch}
      .lvp-右行.高 .lvp-brief标{align-self:flex-start}
      .lvp-字幕入{flex:1;resize:none;background:var(--comfy-input-bg,#1c1c1c);color:var(--fg-color,#ddd);border:1px solid var(--border-color,#444);border-radius:4px;font:11px system-ui;line-height:1.3;padding:3px 5px;box-sizing:border-box;height:38px}
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
        同步台词总时长: 总时长 => 设规划总时长(总时长),
    });

    // 单段精修区（原 brief右，DOM/逻辑原样迁入）：字幕固定两行高、提示词吃剩余高度
    const 精修区 = document.createElement("div");
    精修区.className = "lvp-精修区";
    function 右行(标签, 高) {
        const 盒 = document.createElement("div"); 盒.className = "lvp-右行" + (高 ? " 高" : "");
        const 标 = document.createElement("span"); 标.className = "lvp-brief标"; 标.textContent = 标签 + ":";
        盒.appendChild(标); 精修区.appendChild(盒); return 盒;
    }
    const 标题el = document.createElement("input"); 标题el.className = "lvp-brief入"; 标题el.type = "text";
    右行("标题").appendChild(标题el); 标题el.onchange = () => 写选中段规划({ 标题: 标题el.value });
    const 角色sel = document.createElement("select"); 角色sel.className = "lvp-brief选";
    // UI 标签「结构」（2026-09-21 改名，仅前端文案）；数据键仍「职能」（含 职能色），后端契约不变
    右行("结构").appendChild(角色sel); 角色sel.onchange = () => 写选中段规划({ 职能: 角色sel.value, 职能色: 角色到色(角色sel.value) });
    const 字幕el = document.createElement("textarea"); 字幕el.className = "lvp-字幕入";
    右行("字幕").appendChild(字幕el); 字幕el.onchange = () => 写选中段规划({ 字幕: 字幕el.value });
    const 提示词el = document.createElement("textarea"); 提示词el.className = "lvp-提示词入";
    右行("提示词", true).appendChild(提示词el); 提示词el.onchange = () => 写选中段规划({ prompt: 提示词el.value });
    时间轴页.appendChild(精修区);
    const 角色到色 = (名) => (角色表.find((r) => r.名 === 名) || {}).色 || "";

    // 编辑**草稿** active 段（边界铁律 C3：草稿的结构/内容编辑集中在剪辑链路页面）
    function 写选中段规划(patch) {
        const 节点 = 取节点();
        if (!节点) return;
        const 草 = 真源.读剪辑草稿(节点);
        const 段组 = 草.segments || [];
        const i = 状态.取("剪辑选中段");
        if (!段组[i]) return;
        Object.assign(段组[i], patch);
        const 写 = { ...开关补丁(草), brief: 草.brief || {}, segments: 段组 };
        if (Array.isArray(草.素材) && 草.素材.length) 写.素材 = 草.素材;         // 保态携带（冲突1 同口径）
        if (Array.isArray(草.全局素材) && 草.全局素材.length) 写.全局素材 = 草.全局素材;
        真源.写剪辑草稿(节点, 写);
        剪辑.渲染();
    }

    function 回填(seg) {
        标题el.value = seg.标题 || ""; 字幕el.value = seg.字幕 || ""; 角色sel.value = seg.职能 || ""; 提示词el.value = seg.prompt || "";
        剪辑.刷active();
    }

    // 本页自拉枚举（谁拥有谁监听）：职能→结构下拉（首建防竞态）、技能/辅助→生成行、模型→生成行
    async function 拉生成行模型() {
        try {
            const cfg = await (await fetch("/lvp/llm_config")).json();
            剪辑.填模型((cfg && cfg.models) || [], cfg);
        } catch {}
    }
    let 角色已建 = false;
    async function 拉枚举() {
        try {
            const m = await (await fetch("/lvp/plan_meta")).json();
            if (!角色已建) {
                角色表 = m.职能 || [];
                角色sel.textContent = "";
                角色表.forEach(({ 名 }) => { const o = document.createElement("option"); o.value = 名; o.textContent = 名; 角色sel.appendChild(o); });
                剪辑.填枚举(m);
                角色已建 = true;
            }
        } catch {}
        拉生成行模型();
    }
    // 设置页保存模型配置后广播 → 只刷生成行模型标注（事件名与 规划器设置.js 镜像，测试_常量同步 扫描目标加本文件）
    上轮监听?.abort();
    上轮监听 = new AbortController();
    window.addEventListener("长视频规划师_配置已存", 拉生成行模型, { signal: 上轮监听.signal });

    return { 回填, 重渲染: () => 剪辑.渲染(), 拉枚举 };
}
