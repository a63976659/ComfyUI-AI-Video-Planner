// 图像API与文本模型分别保存；运行时严格使用本清单唯一选中项。
let 草稿 = null, 已改 = false, 加载序号 = 0;

export function 创建图像模型设置({ el, 按钮, 文本框, 小按钮类 }) {
    const 根 = el("div", { class: "lvp-card" });
    const 列表 = el("div", { class: "lvp-models" });
    const 状态 = el("span", { class: "lvp-hint" });
    根.append(el("div", { class: "lvp-card-h" }, el("b", { text: "图像模型" })), 列表, 状态);
    const 空行 = m => m._new && ![m.name, m.base_url, m.model, m._newKey].some(v => String(v || "").trim());
    function 渲染() {
        列表.replaceChildren();
        for (const m of 草稿?.models || []) {
            const 行 = el("div", { class: "lvp-model-item" });
            const 选 = el("input", { type: "radio", name: "lvp-image-model-pick", checked: 草稿.selected_id === m.id });
            选.setAttribute("aria-label", `使用图像模型 ${m.name || "新模型"}`);
            选.onchange = () => { 草稿.selected_id = m.id; 已改 = true; };
            行.append(选);
            if (m._edit || m._new) {
                const 表 = el("div", { class: "lvp-cell", style: { flex: "1", minWidth: "0" } });
                for (const [key, placeholder] of [["name", "名称"], ["base_url", "https://api.openai.com/v1"], ["model", "模型名，如 gpt-image-2.5-flare"]]) {
                    const input = 文本框(placeholder); input.value = m[key] || ""; input.setAttribute("aria-label", "图像模型" + placeholder);
                    input.oninput = () => { m[key] = input.value; 已改 = true; };
                    表.append(input);
                }
                const key = 文本框(m.has_key ? "API Key留空不修改" : "API Key", "password"); key.value = m._newKey || "";
                key.setAttribute("aria-label", "图像模型API Key");
                key.oninput = () => { m._newKey = key.value; 已改 = true; };
                表.append(key);
                const 完成 = 按钮("完成", 小按钮类); 完成.onclick = () => { m._edit = false; m._new = false; 渲染(); };
                表.append(完成); 行.append(表);
            } else {
                行.append(el("div", { class: "lvp-model-meta" }, el("strong", { text: m.name }), el("span", { text: `${m.model} @ ${m.base_url}` })),
                    el("span", { class: m.has_key ? "lvp-badge" : "lvp-badge none", text: m.has_key ? "已配置" : "未配置" }));
                const 编辑 = 按钮("编辑", 小按钮类); 编辑.onclick = () => { m._edit = true; 渲染(); }; 行.append(编辑);
            }
            if (!m.builtin) {
                const 删除 = 按钮("删除", 小按钮类); 删除.onclick = () => {
                    草稿.models = 草稿.models.filter(x => x !== m);
                    if (草稿.selected_id === m.id) 草稿.selected_id = 草稿.models[0]?.id || "";
                    已改 = true; 渲染();
                }; 行.append(删除);
            }
            列表.append(行);
        }
    }
    const 添加按钮 = 按钮("添加图像模型");
    添加按钮.onclick = () => {
        if (!草稿) { 状态.textContent = "请先等待图像配置加载，失败时重开设置或重启服务"; return; }
        const id = globalThis.crypto?.randomUUID?.() || `image-${Date.now()}-${Math.random()}`;
        草稿.models.push({ id, name: "", base_url: "", model: "", _new: true }); 已改 = true; 渲染();
        根.scrollIntoView?.({ block: "nearest" });
    };
    const 序号 = ++加载序号;
    渲染();
    if (!草稿 || !已改) fetch("/lvp/image_config").then(async response => {
        const data = await response.json();
        if (!response.ok || !Array.isArray(data.models)) throw new Error(data.error || "请重启服务以加载图像API配置");
        if (序号 !== 加载序号 || 已改) return;
        草稿 = data; 渲染(); 状态.textContent = "";
    }).catch(e => { if (序号 === 加载序号) 状态.textContent = e.message; });
    function 取保存数据() {
        if (!已改) return null;
        if (!草稿) throw new Error("图像配置未加载");
        const 原数 = 草稿.models.length;
        草稿.models = 草稿.models.filter(m => !空行(m));
        if (原数 !== 草稿.models.length) 渲染();
        if (!草稿.models.length || 草稿.models.some(m => !m.name?.trim() || !m.model?.trim() || !/^https?:\/\//i.test(m.base_url?.trim() || ""))) {
            throw new Error("请填完图像模型的名称、地址和模型名，或删除未完成行");
        }
        if (!草稿.models.some(m => m.id === 草稿.selected_id)) throw new Error("请勾选一个图像模型");
        return { selected_id: 草稿.selected_id, models: 草稿.models.map(m => ({
            id: m.id, name: m.name.trim(), base_url: m.base_url.trim(), model: m.model.trim(), builtin: !!m.builtin, api_key: (m._newKey || "").trim(),
        })) };
    }
    async function 保存(patch) {
        if (!patch) return;
        const response = await fetch("/lvp/image_config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        草稿 = data; 已改 = false; 渲染();
    }
    return { 根, 添加按钮, 取保存数据, 保存 };
}
