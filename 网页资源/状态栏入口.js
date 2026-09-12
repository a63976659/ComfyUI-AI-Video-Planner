import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { 创建状态栏面板 } from "./组件/状态栏面板.js";

const 扩展名 = "ComfyUI-AI-Edit-Video.H3导演台";
const 节点类 = "H3DYT_Director";
let 面板 = null;

// 节点上隐藏 输出分辨率/百万像素/全局提示词（真源仍在 node.widgets，经状态栏 @ 行编辑）：
// 后端 extra_dict hidden 只设 options.hidden（Vue 渲染路径读它），此处补 widget.hidden
// （canvas 布局路径 getLayoutWidgets/isWidgetVisible 读它），双路径都不显示、不占高。
// 全局提示词 不再提供自由文本框，改由 @ 行「百万像素」右边的 画风/预设 两个下拉拼接写回。
const 隐藏widget名 = ["输出分辨率", "百万像素", "全局提示词", "参考共用"];
function 隐藏状态栏widget(node) {
    for (const 名 of 隐藏widget名) {
        const w = (node.widgets || []).find((x) => x.name === 名);
        if (!w) continue;
        w.hidden = true;
        (w.options ||= {}).hidden = true;
    }
    node.setDirtyCanvas?.(true, true);
}

function 确保面板() {
    if (面板) return 面板;
    const 底栏 = document.querySelector(".comfyui-body-bottom");
    if (!底栏) {
        console.warn("[H3导演台] 未找到 .comfyui-body-bottom，状态栏跳过注入");
        return null;
    }
    面板 = 创建状态栏面板(底栏);
    return 面板;
}

app.registerExtension({
    name: 扩展名,

    async setup() {
        确保面板();
        // 原生进度/成功/失败事件 → 面板状态条
        api.addEventListener("progress", (e) => 面板?.设进度(e.detail?.value, e.detail?.max));
        api.addEventListener("execution_success", () => 面板?.设状态("完成"));
        api.addEventListener("execution_error", (e) => 面板?.设状态("失败：" + (e.detail?.message || "")));
    },

    async nodeCreated(node) {
        if (node.comfyClass !== 节点类) return;
        隐藏状态栏widget(node);
        // 「编辑」按钮：toggle——已绑定本节点且展开则折叠，否则绑定并展开
        node.addWidget("button", "编辑", null, () => {
            const p = 确保面板();
            if (!p) return;
            if (p.取节点() === node && p.状态.取("展开")) { p.收起(); return; }
            p.绑定节点(node);
            p.展开();
        });
        // 挂载节点内多段时间轴（DOM 富 widget）
        const { 挂载时间轴 } = await import("./组件/时间轴面板.js");
        挂载时间轴(node, 面板);
    },

    async loadedGraphNode(node) {
        if (node.comfyClass !== 节点类) return;
        隐藏状态栏widget(node);
        面板?.绑定节点(node);   // 载入既有工作流时回填
    },
});
