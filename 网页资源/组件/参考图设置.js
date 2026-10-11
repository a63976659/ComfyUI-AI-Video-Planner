// 与提示词编辑器共享 /lvp/preset/options 的画风清单，不维护第二份预设。
const 默认画风 = "电影写实", 自定义 = "自定义";

export function 创建参考图设置(父) {
    const 行 = document.createElement("div"); 行.className = "lvp-brief行 lvp-参考图行"; 行.hidden = true;
    const 标签 = document.createElement("label"); 标签.className = "lvp-参考图勾选";
    const 勾 = document.createElement("input"); 勾.type = "checkbox"; 勾.setAttribute("aria-label", "生成参考图");
    const 名称 = document.createElement("span"); 名称.textContent = "生成参考图"; 标签.append(勾, 名称);
    const 设置 = document.createElement("button"); 设置.type = "button"; 设置.className = "lvp-规划小钮 lvp-参考图齿轮";
    设置.textContent = "\u2699"; 设置.title = "参考图画风设置"; 设置.setAttribute("aria-label", 设置.title);
    let 画风 = 默认画风, 弹窗 = null, 画风列表 = [默认画风, 自定义];
    const 提示 = () => { 设置.title = "参考图画风设置：" + 画风; };
    function 关闭() { 弹窗?.remove(); 弹窗 = null; }
    设置.onclick = () => {
        关闭();
        弹窗 = document.createElement("dialog"); 弹窗.className = "lvp-参考图弹窗";
        const 标题 = document.createElement("h3"); 标题.textContent = "参考图画风";
        const 选择 = document.createElement("select"); 选择.className = "lvp-brief选"; 选择.setAttribute("aria-label", "选择画风");
        const 输入 = document.createElement("textarea"); 输入.className = "lvp-brief入"; 输入.rows = 3;
        输入.value = 画风列表.includes(画风) ? "" : 画风; 输入.placeholder = "填写参考图画风，例如：黑白木刻、强烈明暗";
        输入.setAttribute("aria-label", "手动输入画风");
        const 错 = document.createElement("div"); 错.className = "lvp-brief错";
        let 用户已编辑 = false;
        function 刷新选择(目标) {
            选择.replaceChildren();
            for (const 风 of 画风列表) { const op = document.createElement("option"); op.value = 风; op.textContent = 风; 选择.append(op); }
            const 是预设 = 目标 !== 自定义 && 画风列表.includes(目标);
            if (目标 !== 自定义 && !是预设) 输入.value = 目标;
            选择.value = 是预设 ? 目标 : 自定义;
            输入.hidden = 选择.value !== 自定义;
        }
        刷新选择(画风);
        选择.onchange = () => { 用户已编辑 = true; 输入.hidden = 选择.value !== 自定义; 错.textContent = ""; if (!输入.hidden) 输入.focus(); };
        输入.oninput = () => { 用户已编辑 = true; 错.textContent = ""; };
        const 脚 = document.createElement("div"); 脚.className = "lvp-brief行"; 脚.style.justifyContent = "flex-end";
        const 取消 = document.createElement("button"); 取消.type = "button"; 取消.className = "lvp-规划小钮"; 取消.textContent = "取消"; 取消.onclick = 关闭;
        const 保存 = document.createElement("button"); 保存.type = "button"; 保存.className = "lvp-规划小钮"; 保存.textContent = "保存";
        保存.onclick = () => {
            const 值 = 选择.value === 自定义 ? 输入.value.trim() : 选择.value;
            if (!值) { 错.textContent = "请填写画风"; return; }
            画风 = 值; 提示(); 关闭();
        };
        脚.append(取消, 保存); 弹窗.append(标题, 选择, 输入, 错, 脚);
        弹窗.addEventListener("cancel", 关闭); document.body.append(弹窗); 弹窗.showModal(); 选择.focus();
        const 本窗 = 弹窗;
        // 只读加载；关闭、换节点后迟到的响应不能修改新窗口或用户已编辑的选择。
        (async () => {
            try {
                const response = await fetch("/lvp/preset/options");
                const data = await response.json();
                if (!response.ok || !Array.isArray(data?.画风)) throw new Error("画风清单不可用");
                if (弹窗 !== 本窗) return;
                const 目标 = 用户已编辑 ? 选择.value : 画风;
                画风列表 = [默认画风, 自定义, ...new Set(data.画风.filter(v => typeof v === "string" && v.trim() && v !== 默认画风 && v !== 自定义))];
                刷新选择(目标);
            } catch {
                if (弹窗 === 本窗 && !用户已编辑) 错.textContent = "画风清单加载失败，可重新打开设置重试，或选择电影写实、自定义";
            }
        })();
    };
    行.append(标签, 设置); 父.append(行); 提示();
    return {
        取值: task => task !== "t2v" && 勾.checked ? { 生成参考图: true, 参考图画风: 画风 }
            : 画风 !== "电影写实" ? { 生成参考图: false, 参考图画风: 画风 } : {},
        恢复: brief => { 关闭(); 勾.checked = !!brief.生成参考图; 画风 = brief.参考图画风 || "电影写实"; 提示(); },
        设任务: task => { 行.hidden = task === "t2v"; if (行.hidden) 关闭(); },
        关闭,
    };
}

export function 合并生成参考图(草, data) {
    if (!Array.isArray(data?.素材) || !data.素材.length) return 草;
    const materials = new Map((草.素材 || []).map(m => [m.名, m]));
    for (const m of data.素材) if (m?.类型 === "图像" && typeof m.名 === "string" && m.名 && !/[\\/:]/.test(m.名)) materials.set(m.名, m);
    const observations = { ...草.素材理解 };
    for (const [name, value] of Object.entries(data.素材理解 || {})) if (materials.has(name)) observations[name] = value;
    return { ...草, 素材: [...materials.values()], 素材理解: observations, 生成参考图资料: data };
}
