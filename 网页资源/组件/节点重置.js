// 节点级重置：默认值来自宿主节点定义（缺定义时取创建阶段的原始 widget 值）。
// 不替换节点、不删文件；确认、任务预检和快照通过后，按一次图变更恢复参数与创作数据。
import { 真源, 写值, 捕获节点快照, 提交节点快照, 使节点快照失效 } from "./桥接/节点桥.js";

const 定义表 = new WeakMap(), 控制表 = new WeakMap(), 任务表 = new WeakMap(), 监听表 = new WeakMap();
const 终态 = new Set(["completed", "failed", "cancelled", "stopped", "interrupted", "完成", "失败", "已停止"]);
const 创作属性 = ["规划任务缓存", "规划成果任务", "规划分集编辑", "草稿编辑历史", "草稿前进历史"];
const 拷贝 = v => v == null ? v : JSON.parse(JSON.stringify(v));

export function 登记重置节点定义(类型, 定义) { 定义表.set(类型, 定义); }

function 通知(node) {
    监听表.get(node)?.forEach(fn => { try { fn(); } catch (e) { console.error("[节点重置] 状态刷新失败", e); } });
}
export function 订阅节点重置(node, fn) {
    let 组 = 监听表.get(node); if (!组) { 组 = new Set(); 监听表.set(node, 组); }
    组.add(fn); return () => 组.delete(fn);
}
export function 设置节点忙碌(node, key, 原因 = "") {
    if (!node) return;
    let 表 = 任务表.get(node); if (!表) { 表 = new Map(); 任务表.set(node, 表); }
    if (原因) 表.set(key, 原因); else 表.delete(key);
    通知(node);
}
export function 登记节点重置(node, 接口) {
    if (控制表.has(node)) return; // 重挂载不得把已编辑的值误记为默认值。
    const 定义 = 定义表.get(node.constructor) || node.constructor?.nodeData;
    const 输入 = { ...定义?.input?.required, ...定义?.input?.optional };
    const 默认 = new Map();
    for (const w of node.widgets || []) {
        if (!w.name || w.options?.serialize === false || w.serialize === false) continue;
        const spec = 输入[w.name], opts = spec?.[1];
        const 值 = opts && Object.hasOwn(opts, "default") ? opts.default
            : Array.isArray(spec?.[0]) ? spec[0][0] : w.value;
        默认.set(w.name, 拷贝(值));
    }
    控制表.set(node, { 默认, 接口, 确认中: false });
    通知(node);
}
export function 重置阻止原因(node) {
    const 控制 = 控制表.get(node);
    if (!控制) return "重置功能尚未准备就绪";
    if (控制.确认中) return "正在确认重置";
    return [...(任务表.get(node)?.values() || [])][0] || 控制.接口.忙碌原因?.() || "";
}
export function 刷新节点重置状态(node) { 通知(node); }
export function 节点曾重置(node) { return !!控制表.get(node)?.已重置; }

// 包含排队/执行中的 ComfyUI prompt 和当前工程持有凭据的规划、制作任务。
// 只在用户请求重置时查询；404 表示任务已不存在，其余查询失败保留原数据。
export async function 检查节点后台任务(node, 请求 = fetch) {
    const 控制 = new AbortController(), timer = setTimeout(() => 控制.abort(), 10000);
    try {
        const res = await 请求("/queue", { cache: "no-store", signal: 控制.signal });
        if (!res.ok) throw new Error("无法确认工作流任务状态，请稍后重试");
        const queue = await res.json();
        if (!Array.isArray(queue.queue_running) || !Array.isArray(queue.queue_pending)) throw new Error("工作流任务状态无效，请稍后重试");
        const id = String(node.id);
        if ([...queue.queue_running, ...queue.queue_pending].some(row => row?.[2]?.[id]?.class_type === "长视频规划师")) {
            return "当前节点有排队或运行中的生成任务，请先停止或等待完成";
        }
        const 草 = 真源.读剪辑草稿(node), 作 = 草.制作 || {}, 表 = new Map();
        for (const ref of [node.properties?.规划任务缓存, node.properties?.规划成果任务, 草.规划资料?.任务引用]) {
            if (ref?.id && ref?.token) 表.set(`plan:${ref.id}`, { ...ref, 类型: "plan" });
        }
        for (const ref of [作.最近任务, ...(Array.isArray(作.任务历史) ? 作.任务历史 : [])]) {
            if (ref?.id && ref?.token) 表.set(`production:${ref.id}`, { ...ref, 类型: "production" });
        }
        const 结果 = await Promise.allSettled([...表.values()].map(async ref => {
            const r = await 请求(`/lvp/${ref.类型}/jobs/${encodeURIComponent(ref.id)}`, {
                cache: "no-store", signal: 控制.signal,
                headers: { [ref.类型 === "plan" ? "X-LVP-Plan-Token" : "X-LVP-Production-Token"]: ref.token },
            });
            if (r.status === 404) return "";
            if (!r.ok) throw new Error("无法确认当前工程的任务状态，请稍后重试");
            const j = await r.json();
            return 终态.has(j.status) ? "" : `当前工程有${ref.类型 === "plan" ? "规划" : "制作"}任务未结束，请先停止或等待完成`;
        }));
        for (const r of 结果) { if (r.status === "rejected") throw r.reason; }
        return 结果.find(r => r.value)?.value || "";
    } finally { clearTimeout(timer); }
}

export async function 请求节点重置(node) {
    const c = 控制表.get(node); if (!c || c.确认中) return false;
    const { 接口, 默认 } = c;
    const 提示 = (文, 类 = "warn") => 接口.提示?.(文, 类);
    const 原因 = 重置阻止原因(node); if (原因) { 提示(原因); return false; }
    if (!接口.存活?.()) { 提示("节点或工作流已变化，重置已取消"); return false; }
    const 快照 = 捕获节点快照(node, [...new Set([...默认.keys(), "剪辑草稿"])]);
    const 原属性 = JSON.stringify(node.properties || {}), 原界面 = 接口.界面签名?.();
    const 仍有效 = () => 接口.存活() && JSON.stringify(node.properties || {}) === 原属性 && 接口.界面签名?.() === 原界面;
    c.确认中 = true; 通知(node);
    try {
        const 检查 = async () => {
            const 忙 = [...(任务表.get(node)?.values() || [])][0] || 接口.忙碌原因?.();
            if (忙) return 忙;
            return await 接口.检查后台?.();
        };
        const 忙 = await 检查(); if (忙) { 提示(忙); return false; }
        if (!仍有效()) { 提示("节点或内容已变化，重置已取消，请重试"); return false; }
        const ok = await 接口.确认("重置创作", "将恢复当前节点的默认参数，并清空全部分段、AI规划、提示词和视频制作工程。\n保留模型连线、公共 API 配置、预设以及磁盘素材、成片和缓存文件。\n确认重置并重新开始创作？");
        if (!ok) return false;
        const 后忙 = await 检查(); if (后忙) { 提示(后忙); return false; }
        if (!仍有效()) { 提示("确认期间节点或内容已变化，重置已取消，请重试"); return false; }
        const 已提交 = 提交节点快照(快照, node, () => {
            const 图 = node.graph;
            图.beforeChange?.();
            try {
                使节点快照失效(node);
                接口.失效生成结果?.();
                for (const [名, 值] of 默认) 写值(node, 名, 拷贝(值));
                真源.写剪辑草稿(node, JSON.parse(默认.get("剪辑草稿") || '{"brief":{},"segments":[]}'), { 记录历史: false });
                for (const 名 of 创作属性) delete node.properties[名];
                c.已重置 = true;
                接口.重置界面?.();
                图.setDirtyCanvas?.(true, true);
            } finally { 图.afterChange?.(); }
        });
        if (!已提交) { 提示("确认期间节点或内容已变化，重置已取消，请重试"); return false; }
        提示("已重置，可以重新开始创作", "success");
        return true;
    } catch (e) { 提示(e.name === "AbortError" ? "任务状态检查超时，未重置，请稍后重试" : e.message || "重置失败", "error"); return false; }
    finally { c.确认中 = false; 通知(node); }
}
