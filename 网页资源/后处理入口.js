import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const widgets = new WeakMap();
let promptId = null;
const targets = new Map();
let registered = false;

function attach(node) {
    if (node.comfyClass !== "精修与放大" || widgets.has(node)) return;
    const existing = node.widgets?.find(widget => widget.name === "整体进度")
        ?? node.addWidget("text", "整体进度", "未运行（宿主进度条为单段进度）", () => {},
            { serialize: false, readOnly: true });
    existing.serialize = false;
    existing.serializeValue = () => undefined;
    widgets.set(node, existing);
}

function show(node, text) {
    const widget = widgets.get(node);
    if (!widget) return;
    widget.value = text;
    node.setDirtyCanvas?.(true, false);
}

app.registerExtension({
    name: "ComfyUI-AI-Video-Planner.后处理进度",
    nodeCreated: attach,
    loadedGraphNode: attach,
    beforeConfigureGraph() {
        promptId = null;
        targets.clear();
    },
    setup() {
        if (registered) return;
        registered = true;
        api.addEventListener("execution_start", ({ detail }) => {
            promptId = detail?.prompt_id;
            targets.clear();
            for (const node of app.graph?._nodes || []) {
                if (!widgets.has(node)) continue;
                targets.set(String(node.id), { node, run: null, seq: 0, completed: false });
                show(node, "本轮尚未执行（缓存命中可能无进度）");
            }
        });
        api.addEventListener("长视频规划师_后处理进度", ({ detail: d }) => {
            if (!d || !promptId || d.prompt_id !== promptId) return;
            const target = targets.get(String(d.node));
            if (!target || app.graph?.getNodeById(d.node) !== target.node) return;
            if (!d.run || (target.run && target.run !== d.run) || !Number.isInteger(d.seq) || d.seq <= target.seq) return;
            if (!Number.isInteger(d.value) || !Number.isInteger(d.max) || d.max <= 0 || d.value < 0 || d.value > d.max) return;
            target.run = d.run;
            target.seq = d.seq;
            target.completed = d.value === d.max;
            show(target.node, `${target.completed ? "完成" : "整体"} ${d.value}/${d.max}（宿主进度条为单段进度）`);
        });
        for (const [event, label] of [["execution_error", "失败"], ["execution_interrupted", "已取消"]]) {
            api.addEventListener(event, ({ detail: d }) => {
                if (!d || d.prompt_id !== promptId) return;
                for (const [id, target] of targets) {
                    if (app.graph?.getNodeById(id) !== target.node) continue;
                    if (id === String(d.node_id)) show(target.node, label);
                    else if (target.run && !target.completed) show(target.node, `已停止（任务${label}）`);
                }
                targets.clear();
                promptId = null;
            });
        }
        api.addEventListener("execution_success", ({ detail }) => {
            if (detail?.prompt_id === promptId) {
                promptId = null;
                targets.clear();
            }
        });
    },
});
