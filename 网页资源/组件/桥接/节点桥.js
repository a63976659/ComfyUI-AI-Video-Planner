// 状态栏/时间轴 ↔ node.widgets + node.properties（节点为唯一真源）。不依赖 app，便于复用与测试。
// 🔒 剪辑草稿 真源＝node.properties.剪辑草稿（非 widget）：properties 随工作流序列化保存，
//   但**不进入 prompt / 执行缓存签名**——编辑草稿不会作废 ComfyUI 节点缓存、不触发重执行。
//   schema 中仍保留同名 widget（恒为默认值、幽灵化），仅作旧工作流迁移载体与向后兼容占位。
import { 清理草稿台词模板 } from "../台词提示词清理.js";
import { 取编辑历史, 安排编辑历史保存 } from "../编辑历史缓存.js";

export function 取widget(node, 名) {
    return (node?.widgets || []).find((w) => w.name === 名);
}

const 正在修改 = new WeakSet();
export function 修改节点(node, 修改) {
    const graph = node?.graph;
    if (graph && 正在修改.has(graph)) return 修改();
    graph?.beforeChange?.();
    if (graph) 正在修改.add(graph);
    try {
        return 修改();
    } finally {
        node?.setDirtyCanvas?.(true, true);
        graph?.setDirtyCanvas?.(true, true);
        if (graph) 正在修改.delete(graph);
        graph?.afterChange?.();
        if (node) 安排编辑历史保存(node);
    }
}

export function 写节点属性(node, 名, 值) {
    if (!node) return false;
    return 修改节点(node, () => {
        const props = node.properties ||= {};
        if (值 === undefined) delete props[名];
        else props[名] = 值;
        return true;
    });
}

export function 读JSON(node, 名, 回退) {
    const w = 取widget(node, 名);
    try {
        const v = JSON.parse(w?.value ?? "null");
        return v ?? 回退;
    } catch {
        return 回退;
    }
}

// 只存内存：相同 JSON 的重写也递增版本，不改变持久化数据契约。
const 写入版本 = new WeakMap();
const 节点代数 = new WeakMap();
// 剪辑草稿 迁至 node.properties 后的写入版本追踪（ABA 守卫，与 widget 写入版本同理）。
const 属性版本 = new WeakMap();   // node → Map<名, version>
const 编辑分组 = new WeakMap();

function 取编辑记录(node, 字段) {
    const history = 取编辑历史(node, 字段);
    const entry = Array.isArray(history) ? history.at(-1) : null;
    return entry?.草稿 && Array.isArray(entry.草稿.segments) ? entry : null;
}
export function 取上次编辑(node) { return 取编辑记录(node, "草稿编辑历史"); }
export function 取下次编辑(node) { return 取编辑记录(node, "草稿前进历史"); }

export function 保存编辑记录(node, 字段 = "草稿编辑历史") {
    取编辑历史(node, 字段);
    const props = node.properties ||= {};
    const history = Array.isArray(props[字段]) ? [...props[字段]] : [];
    const entry = { 草稿: 真源.读剪辑草稿(node) };
    if (props.规划分集编辑) entry.分集编辑 = JSON.parse(JSON.stringify(props.规划分集编辑));
    history.push(entry);
    props[字段] = history.slice(-20);
    安排编辑历史保存(node);
}

function 属性版本号(node, 名) {
    return 属性版本.get(node)?.get(名) || 0;
}
function 递增属性版本(node, 名) {
    let m = 属性版本.get(node);
    if (!m) { m = new Map(); 属性版本.set(node, m); }
    m.set(名, (m.get(名) || 0) + 1);
}

export function 使节点快照失效(node) {
    if (node) 节点代数.set(node, (节点代数.get(node) || 0) + 1);
}

export function 捕获节点快照(node, 字段 = ["剪辑草稿"]) {
    if (!node?.graph) return null;
    return {
        node, graph: node.graph, id: node.id, 代数: 节点代数.get(node) || 0,
        字段: 字段.map(名 => {
            // 剪辑草稿 真源在 properties（隔离执行缓存）；其余字段仍走 widget。
            if (名 === "剪辑草稿") {
                return { 名, widget: null, props: node.properties, 值: node.properties?.[名], 版本: 属性版本号(node, 名) };
            }
            const widget = 取widget(node, 名);
            return { 名, widget, 值: widget?.value, 版本: 写入版本.get(widget) || 0 };
        }),
    };
}

// 调用方在提交时重新取得存活的当前节点；通过后同步重读真源并写入，不跨 await。
export function 提交节点快照(快照, 当前节点, 提交) {
    if (!快照 || 快照.已提交) return false;
    const { node, graph, id, 代数, 字段 } = 快照;
    if (当前节点 !== node || node.graph !== graph || node.id !== id ||
        graph.getNodeById?.(id) !== node || (节点代数.get(node) || 0) !== 代数) return false;
    if (!字段.every(({ 名, widget, props, 值, 版本 }) => {
        if (widget) {
            return 取widget(node, 名) === widget && widget.value === 值 &&
                (写入版本.get(widget) || 0) === 版本;
        }
        // properties 路径（剪辑草稿）：对象身份 + 值 + 版本三重校验（ABA 守卫）。
        //   身份校验对应旧 widget 方案的对象替换检测：properties 被整体替换（即便 JSON 相同）也判失效。
        return node.properties === props && (node.properties?.[名]) === 值 && 属性版本号(node, 名) === 版本;
    })) return false;
    快照.已提交 = true;
    提交(node);
    return true;
}

export function 写值(node, 名, 值) {
    const w = 取widget(node, 名);
    if (!w) return false;
    return 修改节点(node, () => {
        w.value = 值;
        写入版本.set(w, (写入版本.get(w) || 0) + 1);
        return true;
    });
}

export function 写JSON(node, 名, 对象) {
    return 写值(node, 名, JSON.stringify(对象));
}

// 便捷真源读写（字段名与节点 widget 一致）
export const 真源 = {
    读任务类型: (n) => 取widget(n, "任务类型")?.value,
    写任务类型: (n, v) => 写值(n, "任务类型", v),
    读全局提示词: (n) => 取widget(n, "全局提示词")?.value ?? "",
    写全局提示词: (n, v) => 写值(n, "全局提示词", v),
    读参考素材: (n) => 读JSON(n, "参考素材", { 图片: [], 音频: [], 视频: [] }),
    写参考素材: (n, v) => 写JSON(n, "参考素材", v),
    读参考共用: (n) => !!取widget(n, "参考共用")?.value,
    写参考共用: (n, v) => 写值(n, "参考共用", !!v),
    读尾帧锚定: (n) => !!取widget(n, "尾帧锚定")?.value,
    写尾帧锚定: (n, v) => 写值(n, "尾帧锚定", !!v),
    读时间轴: (n) => 读JSON(n, "时间轴数据", { segments: [] }),
    写时间轴: (n, v) => 写JSON(n, "时间轴数据", v),
    读运行选择: (n) => 读JSON(n, "运行选择", {}),
    写运行选择: (n, v) => 写JSON(n, "运行选择", v),
    读输出分辨率: (n) => 取widget(n, "输出分辨率")?.value,
    写输出分辨率: (n, v) => 写值(n, "输出分辨率", v),
    读百万像素: (n) => 取widget(n, "百万像素")?.value,
    写百万像素: (n, v) => 写值(n, "百万像素", v),
    // 缓存失效版本：隐藏数值 widget，经时间轴缓存工具条编辑，换模型/换权重后手动 +1 整体作废段缓存（§B-2）。
    //   读归一为非负整数（widget 值可能是字符串/undefined → 0），与后端 execute 的 int 归一同口径。
    读缓存失效版本: (n) => { const v = Number(取widget(n, "缓存失效版本")?.value); return Number.isFinite(v) && v > 0 ? Math.trunc(v) : 0; },
    写缓存失效版本: (n, v) => { const i = Math.trunc(Number(v)); return 写值(n, "缓存失效版本", Number.isFinite(i) && i > 0 ? i : 0); },
    // 🔒 剪辑草稿 真源＝node.properties.剪辑草稿（隔离执行缓存，详文件头注释）。
    //   schema widget 恒为默认值、不承载数据；读写一律走 properties。
    读剪辑草稿: (n) => {
        const raw = n?.properties?.剪辑草稿;
        try {
            const v = JSON.parse(raw ?? "null");
            return 清理草稿台词模板(v ?? { brief: {}, segments: [] });
        } catch {
            return { brief: {}, segments: [] };
        }
    },
    写剪辑草稿: (n, v, { 记录历史 = true, 编辑批次 = null } = {}) => {
        if (!n) return false;
        return 修改节点(n, () => {
            const props = n.properties ||= {};
            const next = JSON.stringify(清理草稿台词模板(v));
            const old = props.剪辑草稿;
            const group = 编辑分组.get(n);
            if (记录历史 && next !== old && !(编辑批次 && group?.批次 === 编辑批次 && group.当前 === old)) {
                保存编辑记录(n);
            }
            if (记录历史 && next !== old) delete props.草稿前进历史;
            props.剪辑草稿 = next;
            if (记录历史 && 编辑批次) 编辑分组.set(n, { 批次: 编辑批次, 当前: next });
            else 编辑分组.delete(n);
            递增属性版本(n, "剪辑草稿");
            return true;
        });
    },
};

// 素材列表的只读显示转换：合法字符串/数组按后端 _规范列表 去空、去两端空白。
// 非法类型显示为空，校验报错仍由后端负责；不写回、不截槽位上限，不替代后端校验。
function 素材名列表(值) {
    const 列表 = typeof 值 === "string" ? [值] : 值;
    if (!Array.isArray(列表) || 列表.some(名 => 名 != null && typeof 名 !== "string")) return [];
    return 列表.filter(名 => typeof 名 === "string").map(名 => 名.trim()).filter(Boolean);
}

// 对齐 _应用全局：无共用时逐键补缺（显式 []/null/空串均不回退）；共用只覆盖自身含有的键。
// 编辑候选不传共用素材，避免把其他段的共用池当作本段可编辑列表。
export function 解析段素材(refs, 全局素材, 共用素材 = null) {
    const 合并 = 共用素材 === null ? { ...全局素材, ...refs } : { ...refs, ...共用素材 };
    if (共用素材 !== null && 共用素材.视频音频模式 === undefined) delete 合并.视频音频模式;
    return { 图片: 素材名列表(合并.图片), 音频: 素材名列表(合并.音频), 视频: 素材名列表(合并.视频),
        ...(合并.视频音频模式 !== undefined ? { 视频音频模式: 合并.视频音频模式 } : {}) };
}

// 对齐 _查找共用素材：首个段级共用优先，缺槽为空；否则按全局开关取全局字典（缺键不补）。
export function 查找共用素材(段组, 全局素材, 全局共用) {
    const refs = 段组.find(s => s?.refs?.共用)?.refs;
    if (refs) return { 图片: refs.图片 || [], 音频: refs.音频 || [], 视频: refs.视频 || [],
        ...(refs.视频音频模式 !== undefined ? { 视频音频模式: refs.视频音频模式 } : {}) };
    return 全局共用 ? (全局素材 || {}) : null;
}

// ── segment_id（A3）：草稿段的稳定身份 ──
// 语义：拖动/重排随段实体迁移（不按下标重编）；分割生成新 id；旧数据加载/新规划写入时补齐。
//   分配只“补缺”——已有合法字符串 id 的段保持原值，故跨 保存↔加载 往返固定（幂等）。
//   真源仍在 node.properties.剪辑草稿（隔离执行缓存），segment_id 只是段内一个普通字段。
let _段id序号 = 0;
export function 新段ID() {
    const uuid = globalThis.crypto?.randomUUID?.();
    if (typeof uuid === "string" && uuid) return uuid;
    // 无 crypto（老浏览器 / vm 测试环境）退回：单调序号 + 时间 + 随机，同会话内不重复。
    _段id序号 += 1;
    return `seg-${Date.now().toString(36)}-${_段id序号.toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

// 就地为缺失 segment_id 的段补一个唯一稳定 id（幂等：已有 id 的段不动）。非数组原样返回。
export function 分配段ID(段组) {
    if (!Array.isArray(段组)) return 段组;
    const 已用 = new Set();
    for (const s of 段组) if (s && typeof s.segment_id === "string" && s.segment_id) 已用.add(s.segment_id);
    for (const s of 段组) {
        if (!s || typeof s !== "object") continue;
        if (typeof s.segment_id === "string" && s.segment_id) continue;   // 幂等：固定已有 id
        let id = 新段ID();
        while (已用.has(id)) id = 新段ID();   // 与组内已有 id 去重
        s.segment_id = id;
        已用.add(id);
    }
    return 段组;
}
