// 长期专项配置，不给规划页面增加逐阶段确认项。
let 设置序号 = 0;
export function 创建专项能力设置({ el, 文本框 }) {
    let 已加载 = false, 错误 = "", 草稿 = null, 编辑版本 = 0, 保存中 = null;
    const 根ID = `lvp-skill-settings-${++设置序号}`;
    const 根 = el("div", { id: 根ID, class: "lvp-card" });
    根.style.containerType = "inline-size";
    根.append(el("style", { text: `
        #${根ID}.lvp-card { gap:10px; }
        #${根ID} .lvp-skill-group { min-width:0; margin:0; padding:10px 0 0; border:0; border-top:1px solid var(--p-content-border-color,#2e2e2e); }
        #${根ID} .lvp-skill-group:first-of-type { padding-top:0; border-top:0; }
        #${根ID} .lvp-skill-group-title { margin:0 0 8px; font-size:12px; font-weight:600; color:var(--p-text-color,#e8e8e8); }
        #${根ID} .lvp-skill-line { display:flex; align-items:center; flex-wrap:wrap; gap:10px 22px; min-width:0; }
        #${根ID} .lvp-skill-line + .lvp-skill-line { margin-top:10px; }
        #${根ID} .lvp-skill-field { display:flex; align-items:center; gap:8px; min-width:0; max-width:100%; }
        #${根ID} .lvp-skill-field > label { flex:0 0 auto; font-size:12px; color:var(--p-text-muted-color,#9aa0a8); }
        #${根ID} .lvp-skill-field > .lvp-cell { display:flex; min-width:0; flex-wrap:nowrap; }
        #${根ID} input:not([type=checkbox]), #${根ID} select, #${根ID} textarea { flex:0 1 auto; min-width:0; max-width:100%; box-sizing:border-box; }
        #${根ID} input[type=number] { width:80px; }
        #${根ID} select { width:112px; }
        #${根ID} .lvp-skill-model { width:190px; }
        #${根ID} input[type=checkbox] { margin:0; flex:0 0 auto; accent-color:var(--p-primary-color,#3b82f6); }
        #${根ID} .lvp-skill-directory { width:min(100%,760px); align-items:flex-start; }
        #${根ID} .lvp-skill-directory > label { padding-top:7px; }
        #${根ID} .lvp-skill-directory > .lvp-cell { flex:1 1 auto; }
        #${根ID} textarea { width:100%; min-height:58px; resize:vertical; }
        #${根ID} .lvp-skill-tasks { width:100%; align-items:flex-start; }
        #${根ID} .lvp-skill-tasks > label { padding-top:2px; }
        #${根ID} .lvp-skill-tasks > .lvp-cell { flex:1 1 auto; }
        #${根ID} .lvp-skill-task-list { display:flex; flex-wrap:wrap; gap:8px 16px; min-width:0; }
        #${根ID} .lvp-msg { overflow-wrap:anywhere; }
        #${根ID} .lvp-msg:empty { display:none; }
        #${根ID} .lvp-task-label { display:inline-flex; align-items:center; gap:5px; white-space:nowrap; font-size:12px; }
        @container (max-width:480px) {
            #${根ID} .lvp-skill-line { gap:10px 16px; }
            #${根ID} .lvp-skill-directory { flex-direction:column; align-items:stretch; gap:6px; }
            #${根ID} .lvp-skill-directory > label { padding-top:0; }
            #${根ID} .lvp-skill-tasks { flex-direction:column; gap:8px; }
            #${根ID} .lvp-skill-tasks > .lvp-cell { width:100%; }
        }
    ` }));
    根.append(el("div", { class: "lvp-card-h" }, el("b", { text: "专项自动流程" })));
    const 控件 = {}, 已编辑 = new Set(), 所有输入 = [];
    function 监听(node) {
        所有输入.push(node); node.disabled = true;
        for (const event of ["input", "change"]) node.addEventListener(event, () => {
            已编辑.add(node); 编辑版本++;
        });
    }
    let 当前行;
    function 分组(标题) {
        const group = el("section", { class: "lvp-skill-group" }); group.setAttribute("aria-label", 标题);
        group.append(el("h3", { class: "lvp-skill-group-title", text: 标题 })); 根.append(group);
        return group;
    }
    function 新行(group) { 当前行 = el("div", { class: "lvp-skill-line" }); group.append(当前行); }
    function 行(名称, 控件项, 类 = "") {
        const id = `${根ID}-${Object.keys(控件).length}`;
        控件项.id = id; 控件[名称] = 控件项;
        if (控件项.tagName.toLowerCase() !== "div") 监听(控件项);
        当前行.append(el("div", { class: `lvp-skill-field ${类}`.trim() }, el("label", { text: 名称, htmlFor: id }), el("div", { class: "lvp-cell" }, 控件项)));
    }
    const 参考组 = 分组("参考与辅助"); 新行(参考组);
    const 目录 = el("textarea", { class: "p-inputtext p-component", rows: 2 });
    行("本地参考目录", 目录, "lvp-skill-directory"); 新行(参考组);
    function 勾选(名称) { const node = el("input", { type: "checkbox" }); 行(名称, node); return node; }
    function 选项(名称, values) {
        const node = el("select", { class: "p-inputtext p-component" });
        for (const v of values) node.append(el("option", { value: v, text: v }));
        行(名称, node); return node;
    }
    function 数值(名称, max, 秒数 = false) {
        const node = el("input", { type: "number", min: 秒数 ? 0.001 : 0, max, step: 秒数 ? "any" : 1, class: "p-inputtext p-component" });
        行(名称, node); return node;
    }
    const 检索 = 勾选("检索参考"), 辅助 = 选项("辅助图", ["按需", "全部", "关闭"]);
    const 图限 = 数值("辅助图上限", 24);
    const 审查组 = 分组("成片检查"); 新行(审查组);
    const 审查 = 勾选("成片自动审查"), 片修 = 数值("成片修复次数", 2);
    const 模型组 = 分组("视频模型能力"); 新行(模型组);
    const 名称 = 文本框("目标视频模型"); 名称.className = "p-inputtext p-component lvp-skill-model"; 行("目标模型", 名称);
    const 格式 = 选项("提示词格式", ["H3", "自然语言", "原样"]);
    新行(模型组);
    const 最短 = 数值("模型最短秒数", 120, true), 最长 = 数值("模型最长秒数", 120, true), 引用 = 数值("模型最大参考图", 40);
    新行(模型组);
    const 任务 = el("div", { class: "lvp-skill-task-list" }), 任务框 = {};
    for (const [v, label] of [["t2v", "文生视频"], ["i2v", "图生视频"], ["fl2v", "首尾帧"], ["r2v", "参考图视频"], ["v2v", "视频改编"], ["rv2v", "参考加视频"]]) {
        const node = el("input", { type: "checkbox", id: `${根ID}-task-${v}` }); 任务框[v] = node; 监听(node);
        任务.append(el("label", { class: "lvp-task-label", htmlFor: node.id }, node, el("span", { text: label })));
    }
    行("模型支持任务", 任务, "lvp-skill-tasks");
    const 消息 = el("span", { class: "lvp-msg", role: "status", text: "读取配置中…" });
    消息.setAttribute("aria-live", "polite"); 根.append(消息);
    const 重读 = el("button", { type: "button", text: "重新读取", hidden: true,
        class: "p-button p-component", style: { alignSelf: "flex-start" } }); 根.append(重读);
    function 显示错误(前缀, error) {
        消息.textContent = `${前缀}：${error.message || error}`; 消息.className = "lvp-msg err";
    }
    function 校验响应(data) {
        const capability = data?.模型能力;
        if (!data || !Array.isArray(data.本地参考目录) || data.本地参考目录.some(x => typeof x !== "string") ||
            typeof data.检索参考 !== "boolean" || typeof data.成片自动审查 !== "boolean" ||
            !["按需", "全部", "关闭"].includes(data.辅助图) || typeof data.目标模型 !== "string" || !data.目标模型.trim() ||
            !capability || !["H3", "自然语言", "原样"].includes(capability.提示词格式) ||
            !Array.isArray(capability.任务) || !capability.任务.length || capability.任务.some(x => !Object.hasOwn(任务框, x)) ||
            !Number.isFinite(capability.最短秒) || !Number.isFinite(capability.最长秒) ||
            !(capability.最短秒 > 0 && capability.最短秒 <= capability.最长秒 && capability.最长秒 <= 120) ||
            [[data.辅助图上限, 24], [data.成片修复次数, 2], [capability.最大参考图, 40]]
                .some(([value, max]) => !Number.isInteger(value) || value < 0 || value > max))
            throw new Error("专项配置响应格式无效");
    }
    function 填写(data, 保留编辑 = false) {
        校验响应(data);
        草稿 = data;
        const 写值 = (node, key, value) => { if (!保留编辑 || !已编辑.has(node)) node[key] = value; };
        for (const [node, value] of [[目录, data.本地参考目录.join("\n")], [辅助, data.辅助图], [图限, data.辅助图上限],
            [片修, data.成片修复次数], [名称, data.目标模型], [格式, data.模型能力.提示词格式],
            [最短, data.模型能力.最短秒], [最长, data.模型能力.最长秒], [引用, data.模型能力.最大参考图]]) 写值(node, "value", value);
        写值(检索, "checked", data.检索参考); 写值(审查, "checked", data.成片自动审查);
        for (const [key, node] of Object.entries(任务框)) 写值(node, "checked", data.模型能力.任务.includes(key));
    }
    let 加载;
    function 读取() {
        重读.hidden = true; 消息.textContent = "读取配置中…"; 消息.className = "lvp-msg";
        加载 = Promise.resolve().then(() => fetch("/lvp/skill_config")).then(async response => {
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
            填写(data, true); 已加载 = true; 错误 = "";
            for (const node of 所有输入) node.disabled = false;
            消息.textContent = "";
        }).catch(error => { 错误 = error.message; 重读.hidden = false; 显示错误("读取专项配置失败", error); });
    }
    重读.addEventListener("click", 读取); 读取();
    function 读数字(node, label) {
        const value = Number(node.value);
        if (String(node.value).trim() === "" || !Number.isFinite(value) || value < Number(node.min) || value > Number(node.max) ||
            (node.step !== "any" && !Number.isInteger(value))) throw new Error(`${label}须为${node.min}到${node.max}${node.step === "any" ? "的数值" : "的整数"}`);
        return value;
    }
    async function 提交() {
        await 加载;
        if (!已加载) throw new Error(错误 || "专项配置尚未加载");
        if (!名称.value.trim() || 名称.value.trim().length > 100) throw new Error("目标模型名称须为1到100个字符");
        const patch = { ...草稿, 本地参考目录: 目录.value.split(/\r?\n/).map(x => x.trim()).filter(Boolean),
            检索参考: 检索.checked, 辅助图: 辅助.value, 辅助图上限: 读数字(图限, "辅助图上限"), 参考图修复次数: 0,
            成片自动审查: 审查.checked, 成片修复次数: 读数字(片修, "成片修复次数"), 目标模型: 名称.value.trim(),
            模型能力: { 名称: 名称.value.trim(), 提示词格式: 格式.value, 最短秒: 读数字(最短, "模型最短秒数"), 最长秒: 读数字(最长, "模型最长秒数"),
                最大参考图: 读数字(引用, "模型最大参考图"), 任务: Object.keys(任务框).filter(key => 任务框[key].checked) } };
        if (patch.模型能力.最短秒 > patch.模型能力.最长秒) throw new Error("模型最短秒数不能大于最长秒数");
        if (!patch.模型能力.任务.length) throw new Error("至少选择一种模型支持任务");
        const 提交版本 = 编辑版本;
        消息.textContent = "保存中…"; 消息.className = "lvp-msg";
        const response = await fetch("/lvp/skill_config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        校验响应(data);
        if (编辑版本 === 提交版本) { 填写(data); 已编辑.clear(); 消息.textContent = "已保存"; }
        else { 草稿 = data; 消息.textContent = "已保存提交内容，后续修改尚未保存"; }
        消息.className = "lvp-msg ok";
        return data;
    }
    return { 根, 保存() {
        if (!保存中) 保存中 = 提交().catch(error => { 显示错误("保存专项配置失败", error); throw error; }).finally(() => { 保存中 = null; });
        return 保存中;
    } };
}
