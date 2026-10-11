import { 真源, 捕获节点快照, 提交节点快照 } from "./桥接/节点桥.js";
import { 接收生成结果 } from "./制作数据.js";
import { 设置节点忙碌 } from "./节点重置.js";

const 已安装 = new WeakMap();
const 生命周期 = new WeakMap();
function 取生命周期(node) {
    if (生命周期.has(node)) return 生命周期.get(node);
    const state = { 代数: 0 }; 生命周期.set(node, state);
    // 编辑页换绑会作废普通编辑快照，但不会作废后台生成；只有恢复和删除作废结果归属。
    for (const 名 of ["onConfigure", "onRemoved"]) {
        const 原 = node[名]; node[名] = function (...args) { state.代数++; return 原?.apply(this, args); };
    }
    return state;
}
// 创作重置与普通编辑换绑不同：此前提交的生成结果不能再自动加入新工程。
export function 使生成结果失效(node) { if (node) 取生命周期(node).代数++; }
// 与界面是否展开无关：只接收本次提交、当前图内仍存活的原规划节点。
export function 安装自动接收结果(app, api, 刷新 = () => {}, 告知 = () => {}) {
    if (已安装.has(api)) return 已安装.get(api);
    const 提交表 = new Map(), 在途 = new Set(), 已完成 = new Set();
    function 捕获(图 = app.graph, prompt = null) {
        const nodes = 图?._nodes || [];
        return nodes.filter(n => n.comfyClass === "长视频规划师" && (!prompt || prompt[String(n.id)]?.class_type === "长视频规划师"))
            .map(node => ({ node, id: node.id, 代数: 取生命周期(node).代数, graph: 图 }));
    }
    if (typeof api.queuePrompt === "function") {
        const 原提交 = api.queuePrompt;
        api.queuePrompt = function (...args) {
            const 记录 = 捕获(app.graph, args[1]?.output || null), 标记 = {};
            记录.forEach(r => 设置节点忙碌(r.node, 标记, "当前节点正在提交生成任务，请等待提交完成"));
            let 返回;
            try { 返回 = 原提交.apply(this, args); }
            catch (e) { 记录.forEach(r => 设置节点忙碌(r.node, 标记)); throw e; }
            (typeof 返回?.then === "function" ? 返回 : Promise.resolve(返回)).then(v => {
                if (v?.prompt_id && 记录.length) {
                    const id = String(v.prompt_id); if (!提交表.has(id)) 提交表.set(id, 记录);
                    while (提交表.size > 100) 提交表.delete(提交表.keys().next().value);
                    if (已完成.has(id)) 完成({ prompt_id: id }).catch(() => {});
                }
            }).catch(() => {}).finally(() => 记录.forEach(r => 设置节点忙碌(r.node, 标记)));
            return 返回;
        };
    }
    api.addEventListener("execution_start", e => {
        const id = e.detail?.prompt_id;
        // 已排队图优先；刷新浏览器后执行中的任务没有提交快照，保守不自动写入。
        if (!id) return;
    });
    async function 完成(detail = {}) {
        if (!detail.prompt_id) return;
        const id = String(detail.prompt_id); 已完成.add(id); while (已完成.size > 100) 已完成.delete(已完成.values().next().value);
        const 记录 = 提交表.get(id);
        if (!记录 || 在途.has(id)) return;
        在途.add(id);
        try {
            for (const r of 记录) {
                if (app.graph !== r.graph || r.node.graph !== r.graph || r.node.id !== r.id || r.graph.getNodeById?.(r.id) !== r.node || 取生命周期(r.node).代数 !== r.代数) continue;
                try {
                    let resp, data;
                    for (let 重试 = 0; 重试 < 4; 重试++) {
                        resp = await fetch("/lvp/production/receive", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt_id: id, 来源节点: String(r.node.id) }) });
                        data = await resp.json();
                        if (resp.status !== 404 || 重试 === 3) break;
                        await new Promise(resolve => setTimeout(resolve, [200, 500, 1000][重试]));
                        if (app.graph !== r.graph || 取生命周期(r.node).代数 !== r.代数) break;
                    }
                    if (!resp.ok) throw new Error(data.error || data.错误 || "生成结果自动导入失败");
                    if (app.graph !== r.graph || 取生命周期(r.node).代数 !== r.代数) continue;
                    if (data.待完成 && typeof data.prompt_id === "string" && data.prompt_id && data.prompt_id !== id) {
                        const next = data.prompt_id, 原记录 = 提交表.get(next) || [];
                        提交表.set(next, [...原记录.filter(x => x.node !== r.node), r]);
                        if (已完成.has(next)) 完成({ prompt_id: next }).catch(e => console.warn("[视频制作] 最终结果接收失败", e));
                        continue;
                    }
                    const bundles = data.结果 || [];
                    if (!Array.isArray(bundles) || bundles.some(b => String(b.来源节点) !== String(r.node.id))) throw new Error("生成结果归属不匹配，未导入");
                    let 新增 = 0;
                    const ok = 提交节点快照(捕获节点快照(r.node, []), r.graph.getNodeById?.(r.id), node => {
                        let 草 = 真源.读剪辑草稿(node);
                        for (const bundle of bundles) { const j = 接收生成结果(草, bundle); 草 = j.草稿; 新增 += j.新增; }
                        if (新增) 真源.写剪辑草稿(node, 草);
                    });
                    if (ok && 新增) { 刷新(r.node); 告知(r.node, `已自动加入 ${新增} 个视频片段${data.warnings?.length ? "；" + data.warnings.join("；") : ""}`); }
                    else if (ok && data.warnings?.length) 告知(r.node, "生成结果未导入；" + data.warnings.join("；"), true);
                    else if (!ok && bundles.length) 告知(r.node, "草稿或工作流已变化，生成结果未自动覆盖当前工程。", true);
                } catch (e) {
                    if (app.graph === r.graph && r.node.graph === r.graph && r.graph.getNodeById?.(r.id) === r.node
                        && 取生命周期(r.node).代数 === r.代数) 告知(r.node, e.message || String(e), true);
                }
            }
        } finally { 在途.delete(id); 提交表.delete(id); }
    }
    api.addEventListener("execution_success", e => { 完成(e.detail || {}).catch(e => console.warn("[视频制作] 自动接收失败", e)); });
    const control = { 完成, 提交表,
        任务属于当前创作: (node, id) => !!提交表.get(String(id))?.some(r => r.node === node && r.graph === node.graph
            && r.graph.getNodeById?.(r.id) === node && 取生命周期(node).代数 === r.代数),
    }; 已安装.set(api, control); return control;
}
