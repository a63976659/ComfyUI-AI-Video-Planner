import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { 创建状态栏面板 } from "./组件/状态栏面板.js";

const 扩展名 = "ComfyUI-AI-Edit-Video.长视频规划师";
const 节点类 = "长视频规划师";
let 面板 = null;

// 节点上隐藏 输出分辨率/百万像素/全局提示词/参考共用/尾帧锚定（真源仍在 node.widgets，经状态栏 @ 行或时间轴工具条编辑）：
// 后端 extra_dict hidden 只设 options.hidden（Vue 渲染路径读它），此处补 widget.hidden
// （canvas 布局路径 getLayoutWidgets/isWidgetVisible 读它），双路径都不显示、不占高。
// 全局提示词 不再提供自由文本框，改由 @ 行「百万像素」右边的 画风/预设 两个下拉拼接写回。
const 隐藏widget名 = ["输出分辨率", "百万像素", "全局提示词", "参考共用", "尾帧锚定"];
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
        console.warn("[长视频规划师] 未找到 .comfyui-body-bottom，状态栏跳过注入");
        return null;
    }
    面板 = 创建状态栏面板(底栏);
    return 面板;
}

app.registerExtension({
    name: 扩展名,

    async setup() {
        确保面板();
        // 段级进度走**自有**通道（后端 节点/长视频规划师.py 的 _广播进度 发 _进度事件名），事件名是前后端
        // 字面量镜像，同步锁见 测试/测试_常量同步.py。
        // ⚠️ 这里**刻意不再监听**宿主的 legacy "progress"：那条事件由 KSampler 的内部去噪步进触发
        // （宿主 main.py 的 hijack_progress 全局 hook），其 node_id 取自执行上下文＝本长视频规划师节点，
        // 与我方段级进度同 node_id ⇒ 按 node 过滤也分不开，只会让状态条在「生成中 3/7」（段）与
        // 「5/20」（去噪步）之间来回跳。而 api.execution.set_progress 根本不发 "progress"，
        // 所以旧写法下面板从来没显示过段级进度，显示的全是去噪步。缘由详 _广播进度 docstring。
        api.addEventListener("长视频规划师_进度", (e) => {
            const d = e.detail || {};
            const 绑定 = 面板?.取节点();
            // 按绑定节点过滤：多节点工作流下只显示当前正在编辑的那个长视频规划师的进度。
            if (!绑定 || String(d.node) !== String(绑定.id)) return;
            面板?.设进度(d.value, d.max);
        });
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
