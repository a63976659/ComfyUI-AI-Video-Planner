// API 模型配置面板：以「单设置项 + 函数型自定义面板」内嵌进 ComfyUI 设置页（参照 ComfyUI-Artificial-Intelligence
// web/API智能体.js 的 registerManagerSetting/renderManagerPanel 模式）。
// 原因：宿主前端 1.41.20 的 buildTree 把 category 路径当叶子节点、同路径后注册覆盖先注册（a.data=i），
// 多项 addSetting 共用 category 时设置页只剩最后一项；单设置项内嵌面板规避。
// 视觉（2026-09-17 重设计）：widenFormRow 把 FormItem 行改「标签在上、面板满宽」（否则面板被挤进右半栏）；
// 布局同参考插件：上方「模型」卡片＝统一模型清单（预设行 builtin + 自定义行，单选钮选当前模型；每行可「编辑」，
// 编辑/新增行内填写 名称/地址/模型名/API Key，保存后持久化回列表），下方「连接与安全」卡片＝长期全局内容
// （超时/SSL）+「模型清单」添加按钮；API Key 按模型各自保存（同参考插件 api_models 模式），无全局 Key；
// 控件走原生视觉——输入框 p-inputtext、按钮/开关逐字取自参考插件实测在打包产物里的 Tailwind 类组合；
// 自绘样式块只留原生覆盖不到的规则，配色一律 var(--comfy-*/--p-*, 兜底)。
// 面板打开 GET /lvp/llm_config 拉取用户目录中的配置草稿（models 逐条 has_key），
// 点「保存」POST 全量清单；api_key 掩码：逐条徽章「已配置/未配置」，留空不回传（后端按 id 沿用旧 Key）。
// 全局请求超时钳制 120~3600（2026-09-17 下限由 30 提为 120：思考模型规划常超 2 分钟，低下限会误伤）；温度/Max Tokens 不入 UI，走后端默认。
import { app } from "../../../scripts/app.js";
import { 创建图像模型设置 } from "./图像模型设置.js";
import { 创建专项能力设置 } from "./专项能力设置.js";
import { 创建数据管理 } from "./数据管理.js";

const 超时下限 = 120;
const 超时上限 = 3600;
const 面板ID = "lvp-api-model-panel";
const 行类 = "lvp-formrow";   // 挂在 FormItem 根上：标签在上、面板满宽（对齐参照 FORM_ROW_CLASS）
// 包裹层类（挂在 CustomFormValue 生成的 <div id="settingId"> 上）：
// DevTools 实测（2026-09-17）发现宿主 Vue 组件在 .form-input 内包了一层 id=settingId 的包裹层，
// 父 .form-input 是 flex 行容器（flex:1 1 auto），包裹层默认按内容宽收缩（DevTools 实测 709px vs 父 988px），
// 宿主对此包裹层无任何 CSS 规则——NodeCraft AI 知识库「设置持久化/联动UI方案」只用标准控件，
// 函数型 type 自定义面板的包裹层满宽无官方约定，必须自己处理。
const 包裹层类 = "lvp-hostwrap";
const 样式ID = "lvp-api-model-panel-style";
// 后端未重启/旧响应无 models 时的回落副本（与 规划/配置.py 内置预设 同构，单一真实源在后端）
const 回落模型 = [
    { id: "Kimi-K3", name: "Kimi-K3", base_url: "https://api.moonshot.cn/v1", model: "kimi-k3", builtin: true, has_key: false },
    { id: "Qwen3.8", name: "Qwen3.8", base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "qwen3.8-flash", builtin: true, has_key: false },
    { id: "GLM-5.3-Flash", name: "GLM-5.3-Flash", base_url: "https://open.bigmodel.cn/api/paas/v4", model: "glm-5.3-flash", builtin: true, has_key: false },
];

let 已注册 = false;
let 用途面板序 = 0;
let 草稿 = null;      // 模块级草稿：设置对话框关闭重开才会重建面板（切分类复用同一节点，实测宿主 1.41），无条件重载会丢用户未保存的输入
let 已改 = false;
let 镜像 = [];   // 模块级模型清单副本：后端未重启（旧响应无 models）时不丢用户已加条目；只存已持久化部分（不含 _new 行）

/** 镜像同步：副本只留已持久化条目且剥瞬时 UI 态（_new/_edit/_newKey），防幽灵行污染回落路径 */
function 同步镜像() {
    镜像 = (草稿?.models || []).filter((m) => !m._new).map(({ _edit, _newKey, ...r }) => r);
}

/** 全空的新行（名称/地址/模型名都没填）无保留价值：保存/重载/重建时静默丢弃，避免幽灵行阻断保存 */
const 是全空新行 = (m) => m._new && !(m.name || "").trim() && !(m.base_url || "").trim() && !(m.model || "").trim();

// 原生按钮视觉常量：逐字取自参考插件（其又取自 ComfyUI 原生按钮的 Tailwind 类组合，实测在打包产物里）。
// 基础串不含颜色与内边距：主/次/小按钮各自换主题色类与尺寸类。
const 按钮基 =
    "relative inline-flex items-center justify-center gap-2 cursor-pointer " +
    "touch-manipulation whitespace-nowrap appearance-none border-none font-medium " +
    "font-inter transition-colors focus-visible:outline-none focus-visible:ring-1 " +
    "focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 " +
    "h-8 rounded-lg text-sm";
const 次按钮类 = 按钮基 + " px-3 text-secondary-foreground bg-secondary-background hover:bg-secondary-background-hover";
const 主按钮类 = 按钮基 + " px-4 bg-primary-background text-primary-foreground";
const 小按钮类 = 按钮基 + " h-7 px-2.5 text-xs text-secondary-foreground bg-secondary-background hover:bg-secondary-background-hover";

function el(标签, 属性, ...子) {
    const n = document.createElement(标签);
    for (const [k, v] of Object.entries(属性 || {})) {
        if (k === "class") n.className = v;
        else if (k === "style" && typeof v === "object") Object.assign(n.style, v);
        else if (k === "text") n.textContent = v;
        else n[k] = v;
    }
    for (const kid of 子.flat(9)) {
        if (kid === null || kid === undefined || kid === false) continue;
        n.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return n;
}

function 文本框(占位, 类型) {
    return el("input", {
        class: "p-inputtext p-component lvp-grow", type: 类型 || "text",
        autocomplete: "off", placeholder: 占位 || "",
    });
}

function 按钮(文本, 类) {
    return el("button", { class: 类 || 次按钮类, type: "button", text: 文本 });
}

/** 原生开关：结构与类逐字取自参考插件的 ToggleSwitch 复刻（状态走 data-state，Tailwind 变体驱动变色平移） */
function 原生开关(checked, onchange) {
    const 钮 = el("span", {
        class: "pointer-events-none block size-4 rounded-full bg-base-background shadow-sm " +
            "transition-transform data-[state=checked]:translate-x-3.5 " +
            "data-[state=unchecked]:translate-x-0",
    });
    const btn = el("button", {
        class: "group inline-flex h-6 w-10 shrink-0 cursor-pointer touch-manipulation " +
            "items-center justify-center rounded-full border-0 bg-transparent p-0 " +
            "transition-shadow outline-none focus-visible:ring-1 " +
            "focus-visible:ring-border-default disabled:pointer-events-none " +
            "disabled:cursor-not-allowed disabled:opacity-50",
        role: "switch", type: "button",
    }, el("span", {
        class: "pointer-events-none inline-flex h-5 w-9 items-center rounded-full border " +
            "border-transparent bg-interface-stroke px-0.5 transition-colors " +
            "group-data-[state=checked]:bg-primary-background",
    }, 钮));
    const set = (v) => {
        btn.setAttribute("aria-checked", v ? "true" : "false");
        btn.dataset.state = v ? "checked" : "unchecked";
        钮.dataset.state = v ? "checked" : "unchecked";
    };
    set(!!checked);
    btn.addEventListener("click", () => {
        const v = btn.dataset.state !== "checked";
        set(v);
        onchange(v);
    });
    btn._set = set;   // 供异步拉配置后回写初始态
    return btn;
}

function 确保样式() {
    if (document.getElementById(样式ID)) return;
    const s = el("style");
    s.id = 样式ID;
    s.textContent = [
        `#${面板ID} { width:100%; box-sizing:border-box; display:flex; flex-direction:column; gap:14px; }`,
        /* 对齐参照 API智能体.js L303-307：只改 FormItem 根（inputBox.parentElement）为纵向，
           并通过直接子选择器让 .form-label / .form-input 满宽——不在外层加跨列 / 解除 max-width，
           宿主表单区并非两列 grid，参照插件只动这一处即可满宽（用户截图对照过） */
        `.${行类} { flex-direction:column !important; align-items:stretch !important; gap:6px !important; height:auto !important; }`,
        `.${行类} > .form-label { flex:0 0 auto !important; width:100% !important; }`,
        `.${行类} > .form-input { width:100% !important; flex:1 1 auto !important; justify-content:flex-start !important; box-sizing:border-box !important; }`,
        /* 包裹层（.form-input 的直接子，宿主 Vue CustomFormValue 生成的 id=settingId 包壳）强制满宽：
           DevTools 实测父 .form-input 是 flex 行容器，包裹层默认按内容宽收缩（709px vs 父 988px），
           宿主对此层无任何 CSS 规则，知识库亦无函数型 type 满宽约定→必须自己处理 */
        `.${行类} > .form-input > .${包裹层类} { width:100% !important; box-sizing:border-box !important; }`,
        `#${面板ID} .lvp-desc { font-size:12px; line-height:1.7; margin:0; color:var(--p-text-muted-color,#9aa0a8); }`,
        `#${面板ID} .lvp-purpose-card.lvp-card { gap:8px; }`,
        `#${面板ID} .lvp-purpose-fields { display:flex; align-items:center; flex-wrap:wrap; gap:10px 24px; min-width:0; }`,
        `#${面板ID} .lvp-purpose-field { display:flex; align-items:center; gap:8px; min-width:0; max-width:100%; }`,
        `#${面板ID} .lvp-purpose-field label { flex:0 0 auto; font-size:12px; color:var(--p-text-muted-color,#9aa0a8); }`,
        `#${面板ID} .lvp-purpose-field select { width:200px; min-width:0; max-width:100%; box-sizing:border-box; flex:0 1 auto; }`,
        `#${面板ID} .lvp-card { background:var(--p-content-background,#161616); border:1px solid var(--p-content-border-color,#2e2e2e); border-radius:10px; padding:14px 16px; display:flex; flex-direction:column; gap:12px; }`,
        `#${面板ID} .lvp-card-h { display:flex; align-items:baseline; gap:8px; flex-wrap:wrap; }`,
        `#${面板ID} .lvp-card-h b { font-size:13px; font-weight:600; color:var(--p-text-color,#e8e8e8); }`,
        `#${面板ID} .lvp-row { display:grid; grid-template-columns:112px 1fr; gap:10px; align-items:center; }`,
        `#${面板ID} .lvp-row > label { font-size:12px; color:var(--p-text-muted-color,#9aa0a8); white-space:nowrap; }`,
        `#${面板ID} .lvp-cell { display:flex; align-items:center; gap:8px; min-width:0; flex-wrap:wrap; }`,
        `#${面板ID} .lvp-grow { flex:1 1 240px; min-width:0; width:auto; }`,
        `#${面板ID} .lvp-hint { font-size:11px; color:var(--p-text-muted-color,#9aa0a8); }`,
        `#${面板ID} .lvp-test-ok { color:var(--p-green-400,#7ee0a3); }`,
        `#${面板ID} .lvp-test-err { color:var(--p-red-400,#ff8b7a); }`,
        `#${面板ID} .lvp-models { display:flex; flex-direction:column; gap:6px; }`,
        `#${面板ID} .lvp-model-item { display:flex; align-items:center; gap:10px; padding:7px 10px; border:1px solid var(--p-content-border-color,#2e2e2e); border-radius:8px; background:var(--comfy-input-bg,#1c1c1c); }`,
        `#${面板ID} .lvp-model-meta { display:flex; flex-direction:column; gap:1px; min-width:0; flex:1 1 auto; }`,
        `#${面板ID} .lvp-model-meta strong { font-size:12.5px; font-weight:600; color:var(--p-text-color,#e8e8e8); }`,
        `#${面板ID} .lvp-model-meta span { font-size:11px; color:var(--p-text-muted-color,#9aa0a8); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }`,
        `#${面板ID} .lvp-tag { font-size:10px; padding:0 6px; border-radius:8px; border:1px solid var(--p-content-border-color,#2e2e2e); color:var(--p-text-muted-color,#9aa0a8); white-space:nowrap; }`,
        `#${面板ID} .lvp-model-item input[type=radio] { accent-color:var(--p-primary-color,#3b82f6); width:14px; height:14px; margin:0; flex:0 0 auto; cursor:pointer; }`,
        /* 编辑/新增行：竖排虚线卡片（与已持久化行区分），内三列输入网格 + 密钥行 */
        `#${面板ID} .lvp-new { flex-direction:column; align-items:stretch; gap:6px; border-style:dashed; }`,
        `#${面板ID} .lvp-new-grid { display:grid; grid-template-columns:1fr 1.6fr 1fr; gap:8px; }`,
        /* Key 徽标非原生控件，自绘配色走主题变量兜底 */
        `#${面板ID} .lvp-badge { font-size:11px; color:var(--p-green-400,#7ee0a3); background:var(--p-green-900,#14351f); border:1px solid var(--p-green-700,#2a5c3c); border-radius:10px; padding:1px 8px; white-space:nowrap; }`,
        `#${面板ID} .lvp-badge.none { color:var(--p-orange-300,#e0b47e); background:var(--p-orange-900,#35291a); border-color:var(--p-orange-700,#5c452a); }`,
        `#${面板ID} .lvp-foot { display:flex; align-items:center; gap:12px; }`,
        `#${面板ID} .lvp-msg { flex:1 1 auto; font-size:12px; min-height:16px; color:var(--p-text-muted-color,#9aa0a8); }`,
        `#${面板ID} .lvp-msg.ok { color:var(--p-green-400,#7ee0a3); }`,
        `#${面板ID} .lvp-msg.err { color:var(--p-red-400,#ff8b7a); }`,
    ].join("\n");
    document.head.append(s);
}

/**
 * 把面板所在的 FormItem 行改成「标签在上、面板占满整行」。
 * 对齐参照 API智能体.js widenFormRow (L807-821)：只改 inputBox.parentElement 一处挂 行类。
 * 额外挂 包裹层类（DevTools 2026-09-17 实测发现）：宿主 Vue CustomFormValue 在 .form-input 内
 * 包了一层 <div id="settingId">（我们的面板返回 DOM 的宿主包裹），父 .form-input 是 flex 行容器，
 * 包裹层默认按内容宽收缩——必须挂 包裹层类 让 CSS 强制 width:100%。
 * CustomFormValue 先调 type 函数、后 appendChild，此刻 parentElement 还是 null——必须延迟一轮任务。
 */
function 撑满设置行(面板) {
    setTimeout(() => {
        // 先给面板的父（即 CustomFormValue 包裹层，id=settingId）挂 包裹层类
        if (面板.parentElement) 面板.parentElement.classList.add(包裹层类);
        let 输入盒 = null;
        let p = 面板.parentElement;
        for (let i = 0; i < 8 && p; i++) {
            if (p.classList && p.classList.contains("form-input")) { 输入盒 = p; break; }
            p = p.parentElement;
        }
        if (输入盒 && 输入盒.parentElement) {
            输入盒.parentElement.classList.add(行类);
        }
    }, 0);
}

function 提示(宿主, 文本, 级) {
    try {
        const t = 宿主?.extensionManager?.toast;
        if (t?.add) { t.add({ severity: 级, summary: "长视频规划师", detail: 文本, life: 4000 }); return; }
    } catch { /* 落到 ui.toast */ }
    宿主?.ui?.toast?.showMessage?.({ message: 文本, severity: 级 });
}

async function 拉配置() {
    try {
        const r = await fetch("/lvp/llm_config");
        const 数据 = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(数据.error || `HTTP ${r.status}`);
        return 数据;
    } catch (e) {
        return { 错: e.message || String(e) };
    }
}

function 渲染配置面板(宿主) {
    确保样式();
    // 全空新行无保留价值：面板重建入口即静默丢弃（与保存/GET 路径一致），切分类再切回不留幽灵填写行；填了一部分的保留
    if ((草稿?.models || []).some(是全空新行)) {
        草稿.models = 草稿.models.filter((m) => !是全空新行(m));
        同步镜像();
    }
    const 面板 = el("div", { id: 面板ID });
    const 框 = {};

    // —— 开头说明（标题由宿主 FormItem 标签承担，不重复画）——
    面板.append(el("p", { class: "lvp-desc", text: "配置存于服务器端，重启后自动恢复；API Key 按模型各自保存，留空表示不修改，完整 Key 不下发到浏览器。" }));

    // —— 卡片一：模型（统一清单＝预设行+自定义行；单选钮选当前；每行可编辑，编辑/新增行内填 Key，保存后持久化）——
    const 列表盒 = el("div", { class: "lvp-models" });
    const 用途下拉 = {};
    function 刷新用途模型() {
        const 清单 = (草稿?.models || 镜像).filter(m => m.id && !m._new);
        for (const [key, sel] of Object.entries(用途下拉)) {
            sel.replaceChildren(el("option", { value: "", text: "沿用当前默认模型" }));
            for (const m of 清单) sel.append(el("option", { value: m.id, text: m.has_key ? m.name : `${m.name}（未配置Key）` }));
            const mid = 草稿?.ai_model_selections?.[key] || "";
            sel.value = 清单.some(m => m.id === mid) ? mid : "";
            if (草稿?.ai_model_selections) 草稿.ai_model_selections[key] = sel.value;
        }
    }
    const 是命中 = (m) => !m._new && m.base_url === 草稿?.base_url && m.model === 草稿?.model;
    const 键徽 = (m) => el("span", { class: m.has_key ? "lvp-badge" : "lvp-badge none", text: m.has_key ? "已配置" : "未配置" });
    const 刷新模型列表 = () => {
        列表盒.replaceChildren();
        const 清单 = 草稿?.models || 镜像;
        const 填写行 = (m, i, 是新增) => {
            const 名入 = 文本框("名称，如 DeepSeek"); 名入.value = m.name || "";
            名入.disabled = !!m.builtin;   // 预设名是覆盖表主键，不可改
            const 址入 = 文本框("https://api.deepseek.com/v1"); 址入.value = m.base_url || "";
            const 码入 = 文本框("模型名，如 deepseek-chat"); 码入.value = m.model || "";
            名入.oninput = () => { m.name = 名入.value; 已改 = true; };
            址入.oninput = () => { m.base_url = 址入.value; 已改 = true; };
            码入.oninput = () => { m.model = 码入.value; 已改 = true; };
            const 键入 = el("input", {
                class: "p-inputtext p-component lvp-grow", type: "password", autocomplete: "off",
                placeholder: m.has_key ? "留空表示不修改；粘贴新 Key 可更换" : "粘贴 API Key（可选）",
            });
            键入.oninput = () => { m._newKey = 键入.value; 已改 = true; };
            // 测试连通性（同参照插件 test_api_model 交互）：用行内当前地址/模型/待填 Key 发最小请求；
            // Key 留空＝后端沿用该条目已存 Key（按 id/地址+模型匹配），未保存也能测
            const 测况 = el("span", { class: "lvp-hint", text: "" });
            const 测钮 = 按钮("测试连通性", 小按钮类);
            测钮.onclick = async () => {
                测钮.disabled = true; 测钮.textContent = "测试中…";
                测况.className = "lvp-hint"; 测况.textContent = "";
                try {
                    const r = await fetch("/lvp/llm_test", {
                        method: "POST", headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            id: m.id || "", base_url: 址入.value.trim(),
                            model: 码入.value.trim(), api_key: (m._newKey || "").trim(),
                        }),
                    });
                    const 数据 = await r.json().catch(() => ({}));
                    if (!r.ok) throw new Error(数据.error || `HTTP ${r.status}`);
                    if (数据.ok) { 测况.className = "lvp-hint lvp-test-ok"; 测况.textContent = "✓ 连通正常"; }
                    else { 测况.className = "lvp-hint lvp-test-err"; 测况.textContent = `✗ ${数据.error || "未知错误"}`; }
                } catch (e) {
                    测况.className = "lvp-hint lvp-test-err"; 测况.textContent = `✗ ${e.message || e}`;
                } finally {
                    测钮.disabled = false; 测钮.textContent = "测试连通性";
                }
            };
            const 钮组 = [];
            if (是新增) {
                const 撤 = 按钮("取消", 小按钮类);
                撤.onclick = () => { 草稿.models.splice(i, 1); 同步镜像(); 已改 = true; 刷新模型列表(); };
                钮组.push(撤);
            } else {
                const 完 = 按钮("完成", 小按钮类);
                完.onclick = () => { m._edit = false; 刷新模型列表(); };
                钮组.push(完);
            }
            列表盒.append(el("div", { class: "lvp-model-item lvp-new" },
                el("div", { class: "lvp-new-grid" }, 名入, 址入, 码入),
                el("div", { class: "lvp-cell" }, 键徽(m), 键入, 测钮, 测况,
                    el("span", { class: "lvp-hint", text: 是新增 ? "新模型：填写后点下方「保存配置」持久化" : "Key 留空不修改；改完点下方「保存配置」生效" }),
                    钮组)));
        };
        const 模型行 = (m, i) => {
            if (m._new || m._edit) { 填写行(m, i, !!m._new); return; }
            const 单 = el("input", { type: "radio", name: "lvp-model-pick" });
            单.checked = 是命中(m);
            单.onchange = () => {
                草稿 = 草稿 || {};
                草稿.base_url = m.base_url; 草稿.model = m.model; 已改 = true;
            };
            const 编 = 按钮("编辑", 小按钮类);
            编.onclick = () => { m._edit = true; 刷新模型列表(); };
            const 子 = [单,
                el("div", { class: "lvp-model-meta" },
                    el("strong", { text: m.name }),
                    el("span", { text: `${m.model} @ ${m.base_url}` })),
                键徽(m),
                el("span", { class: "lvp-tag", text: m.builtin ? "预设" : "自定义" }),
                编];
            if (!m.builtin) {
                const 删 = 按钮("删除", 小按钮类);
                删.onclick = () => { 草稿.models.splice(i, 1); 同步镜像(); 已改 = true; 刷新模型列表(); };
                子.push(删);
            }
            列表盒.append(el("div", { class: "lvp-model-item" }, 子));
        };
        清单.forEach(模型行);
        if (!清单.some((m) => !m.builtin && !m._new)) 列表盒.append(el("span", { class: "lvp-hint", text: "仅预设模型——点「编辑」填入该模型的 API Key，或在下方「模型清单」添加任意 OpenAI 兼容接口。" }));
        const 命中 = 清单.find(是命中);
        if (!命中 && (草稿?.model || 草稿?.base_url)) 列表盒.append(el("span", { class: "lvp-hint", text: `当前模型未列入清单：${草稿.model || "(空)"} @ ${草稿.base_url || "(空)"}，沿用其已存地址` }));
        刷新用途模型();
    };
    刷新模型列表();   // 同步先画回落清单，避免异步拉配置前列表空白
    面板.append(el("div", { class: "lvp-card" },
        el("div", { class: "lvp-card-h" }, el("b", { text: "模型" }),
            el("span", { class: "lvp-hint", text: "单选钮选当前模型并写回 Base URL / Model；预设与自定义同样可编辑，API Key 按模型各自保存" })),
        列表盒));
    const 用途卡 = el("div", { class: "lvp-card lvp-purpose-card" },
        el("div", { class: "lvp-card-h" }, el("b", { text: "AI 功能模型" })),
        el("p", { class: "lvp-desc", text: "未单独选择时沿用默认模型；新模型先保存到清单，再选择并保存配置。" }));
    const 用途字段 = el("div", { class: "lvp-purpose-fields" }); 用途卡.append(用途字段);
    const 用途ID = `${面板ID}-purpose-${++用途面板序}`;
    for (const [key, name] of [["planning", "AI规划模型"], ["timeline", "时间轴改写模型"], ["editor", "提示词优化模型"]]) {
        const sel = el("select", { id: `${用途ID}-${key}`, class: "p-inputtext p-component" }); sel.setAttribute("aria-label", name);
        sel.onchange = () => {
            草稿 = 草稿 || {}; 草稿.ai_model_selections = { ...(草稿.ai_model_selections || {}), [key]: sel.value }; 已改 = true;
        };
        用途下拉[key] = sel;
        用途字段.append(el("div", { class: "lvp-purpose-field" }, el("label", { text: name, htmlFor: sel.id }), sel));
    }
    面板.append(用途卡); 刷新用途模型();
    const 图像设置 = 创建图像模型设置({ el, 按钮, 文本框, 小按钮类 });
    面板.append(图像设置.根);
    const 专项设置 = 创建专项能力设置({ el, 文本框 });

    // —— 卡片二：连接与安全（长期全局内容；Key 已按模型各自保存在上方清单，不在此重复）——
    const 超 = el("input", {
        class: "p-inputtext p-component", type: "number",
        min: String(超时下限), max: String(超时上限), step: "10", style: { width: "110px" },
    });
    超.oninput = () => {
        const v = parseInt(超.value, 10);
        草稿 = 草稿 || {};
        草稿.timeout = Number.isFinite(v) ? Math.max(超时下限, Math.min(v, 超时上限)) : 120;
        已改 = true;
    };
    超.onchange = () => { 超.value = String(草稿?.timeout ?? 120); };   // 失焦回写钳制值，显示与真实值不脱节
    框.timeout = 超;
    const 勾 = 原生开关(true, (v) => { 草稿 = 草稿 || {}; 草稿.verify_ssl = v; 已改 = true; });
    框.ssl设 = 勾._set;
    // 模型清单添加按钮与连接设置紧接图像模型配置：点击后上方模型列表追加填写行。
    const 加钮 = 按钮("➕ 添加自定义模型");
    加钮.onclick = () => {
        草稿 = 草稿 || {};
        草稿.models = [...(草稿.models || 镜像), { name: "", base_url: "", model: "", _new: true }];
        同步镜像(); 已改 = true;
        刷新模型列表();
        setTimeout(() => {   // 聚焦新行首个输入框并滚入视野（同参考插件添加后的处理）
            const inp = 面板.querySelector(".lvp-new input");
            inp?.focus();
            inp?.scrollIntoView({ block: "nearest", behavior: "smooth" });
        }, 0);
    };
    面板.append(el("div", { class: "lvp-card" },
        el("div", { class: "lvp-card-h" }, el("b", { text: "连接与安全" }),
            el("span", { class: "lvp-hint", text: "温度 / Max Tokens 使用后端默认值，不在此配置" })),
        el("div", { class: "lvp-row" }, el("label", { text: "全局请求超时(秒)" }),
            el("div", { class: "lvp-cell" }, 超, el("span", { class: "lvp-hint", text: `${超时下限}~${超时上限}；单次连接或连续无数据等待，不限制完整规划总时长` }))),
        el("div", { class: "lvp-row" }, el("label", { text: "校验 SSL 证书" }),
            el("div", { class: "lvp-cell" }, 勾,
                el("span", { class: "lvp-hint", text: "关闭仅对本地自签证书生效；公网 https 强制保持校验" }))),
        el("div", { class: "lvp-row" }, el("label", { text: "模型清单" }),
            el("div", { class: "lvp-cell", style: { flexDirection: "column", alignItems: "flex-start" } }, 加钮, 图像设置.添加按钮,
                el("span", { class: "lvp-hint", text: "添加后在上方对应列表填写新行（含 Key），点「保存配置」生效" })))));

    面板.append(专项设置.根);
    面板.append(创建数据管理({ el }).根);

    // —— 页脚：状态 + 保存 ——
    const 状态 = el("span", { class: "lvp-msg" });
    const 存钮 = 按钮("保存配置", 主按钮类);
    存钮.onclick = async () => {
        // 全空新行静默丢弃；填了一部分但不合法的新行才阻断保存（明确报错）
        if ((草稿?.models || []).some(是全空新行)) {
            草稿.models = 草稿.models.filter((m) => !是全空新行(m));
            同步镜像(); 刷新模型列表();
        }
        const 待补 = (草稿?.models || []).filter((m) => m._new);
        if (待补.some((m) => !(m.name || "").trim() || !(m.model || "").trim() || !/^https?:\/\//i.test((m.base_url || "").trim()))) {
            状态.className = "lvp-msg err";
            状态.textContent = "保存失败：请先填完上方新模型行的名称 / Base URL(http(s) 开头) / 模型名，或取消该行";
            提示(宿主, "请先填完新增自定义模型行再保存", "warn");
            return;
        }
        const patch = { ...(草稿 || {}) };
        delete patch.models;
        // 全量清单提交：api_key 只带 _newKey（空串＝不修改，后端按 id 沿用旧 Key）；瞬时 UI 态不入 payload
        patch.api_models = (草稿?.models || []).map((m) => ({
            id: m.id || "", name: (m.name || "").trim(), base_url: (m.base_url || "").trim(),
            model: (m.model || "").trim(), builtin: !!m.builtin, api_key: (m._newKey || "").trim(),
        }));
        delete patch.api_key;   // 生效密钥由后端从选中模型条目派生，前端不直写
        delete patch.错;
        let 图像patch;
        try { 图像patch = 图像设置.取保存数据(); }
        catch (e) { 状态.className = "lvp-msg err"; 状态.textContent = e.message; return; }
        存钮.disabled = true; 状态.className = "lvp-msg"; 状态.textContent = "保存中…";
        try {
            const resp = await fetch("/lvp/llm_config", {
                method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch),
            });
            const 数据 = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(数据.error || `HTTP ${resp.status}`);
            try { await 图像设置.保存(图像patch); }
            catch (e) { throw new Error(`文本模型已保存，图像模型保存失败：${e.message}`); }
            try { await 专项设置.保存(); }
            catch (e) { throw new Error(`模型配置已保存，专项配置保存失败：${e.message}`); }
            // POST 响应即脱敏配置：用其 models 刷新清单（has_key 最新、编辑行收起）；旧后端无 models 时本地折算
            草稿.models = Array.isArray(数据.models) && 数据.models.length ? 数据.models
                : patch.api_models.map(({ api_key, ...r }) => ({ ...r, has_key: !!api_key }));
            草稿.ai_model_selections = 数据.ai_model_selections || patch.ai_model_selections || {};
            同步镜像();
            刷新模型列表();
            已改 = false;
            状态.className = "lvp-msg ok";
            状态.textContent = "已保存（服务器端模型配置）";
            提示(宿主, "API 模型配置已保存", "success");
            // 保留配置变更事件供其他配置消费者使用；三个入口运行时均读取服务器端用途选择。
            window.dispatchEvent(new CustomEvent("长视频规划师_配置已存"));
        } catch (e) {
            状态.className = "lvp-msg err";
            状态.textContent = `保存失败：${e.message || e}`;
            提示(宿主, `保存 API 模型配置失败：${e.message || e}`, "error");
        } finally {
            存钮.disabled = false;
        }
    };
    面板.append(el("div", { class: "lvp-foot" }, 状态, 存钮));

    撑满设置行(面板);
    (async () => {
        if (!草稿 || !已改) {
            const 数据 = await 拉配置();
            if (!面板.isConnected) return;   // 面板已被重建，本次结果作废
            if (数据.错) { 状态.className = "lvp-msg err"; 状态.textContent = `读取当前配置失败：${数据.错}（服务端路由未注册时需重启 ComfyUI）`; }
            // 填了一部分的未保存新行跨重建保留；全空幽灵行丢弃；服务端清单为准
            const 未保存 = (草稿?.models || []).filter((m) => m._new && !是全空新行(m));
            let 服务清单 = null;
            if (Array.isArray(数据.models) && 数据.models.length) {
                服务清单 = 数据.models;
            } else if (数据.presets || 数据.custom_models) {   // 旧后端契约回落：presets/custom_models 折算成统一清单
                服务清单 = [
                    ...(Array.isArray(数据.presets) && 数据.presets.length ? 数据.presets : 回落模型).map((p) => ({
                        id: p.id || p.name, name: p.name, base_url: p.base_url, model: p.model, builtin: true, has_key: false,
                    })),
                    ...(Array.isArray(数据.custom_models) ? 数据.custom_models : []).map((c, i) => ({
                        id: c.id || `custom_${i}`, name: c.name, base_url: c.base_url, model: c.model, builtin: false, has_key: false,
                    })),
                ];
            }
            草稿 = Object.assign({}, 数据);
            delete 草稿.错;
            delete 草稿.has_key;   // 只读字段，不回传
            delete 草稿.presets;
            delete 草稿.custom_models;
            delete 草稿.models;
            草稿.models = [...(服务清单 || 镜像), ...未保存];
            已改 = false;
        }
        if (!草稿.model && (草稿.models || [])[0]) { 草稿.base_url = 草稿.models[0].base_url; 草稿.model = 草稿.models[0].model; 已改 = true; }  // 旧盘残留空 model → 整套默认首行（含 base_url，避免选中项与地址不一致）
        草稿.models = Array.isArray(草稿.models) && 草稿.models.length ? 草稿.models : [...镜像, ...((草稿?.models || []).filter((m) => m._new))];
        同步镜像();
        框.timeout.value = 草稿.timeout ?? 120;
        框.ssl设(草稿.verify_ssl ?? true);
        刷新模型列表();
    })();
    return 面板;
}

export async function 注册规划设置(_app) {
    const 宿主 = _app || app;
    if (已注册) return;
    已注册 = true;
    const S = 宿主?.ui?.settings;
    if (!S?.addSetting) return;   // 宿主无 settings API → 静默跳过（不阻断）
    S.addSetting({
        id: "长视频规划师.LLM.配置面板",
        category: ["🎬 长视频规划师", "API 模型配置"],
        name: "API 模型配置",
        type: () => 渲染配置面板(宿主),   // 函数型 → 宿主 CustomFormValue 把返回 DOM 挂进设置项
        defaultValue: "",
        tooltip: "文本与图像API模型独立清单，Key按模型保存；配置保存在运行ComfyUI的系统用户目录中，密钥不下发浏览器、不随插件文件分享",
    });
}
