import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { 创建状态栏面板 } from "./组件/状态栏面板.js";
import { 挂载时间轴 } from "./组件/时间轴面板.js";
import { 使节点快照失效, 取widget } from "./组件/桥接/节点桥.js";

// 扩展名动态派生自插件文件夹名（ComfyUI 前端约定：/extensions/<文件夹名>/...），
// 文件夹再改名不用动这里；URL 结构异常时兜底为固定串。
const 扩展名 = (() => {
    try {
        const 段 = new URL(import.meta.url).pathname.split("/").filter(Boolean);
        const i = 段.indexOf("extensions");
        if (i >= 0 && 段[i + 1]) return `${decodeURIComponent(段[i + 1])}.长视频规划师`;
    } catch {}
    return "ComfyUI-AI-Video-Planner.长视频规划师";
})();
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
    // DOM 级防重复：若 .lvp-状态栏 已存在（模块重载/热更新等场景），先移除再重建
    底栏.querySelectorAll(".lvp-状态栏").forEach(el => el.remove());
    面板 = 创建状态栏面板(底栏);
    return 面板;
}

app.registerExtension({
    name: 扩展名,

    async setup() {
        确保面板();
        // 注册 API 模型配置面板（§8.6）：动态 import，失败 try/catch 告警不阻断入口。
        try {
            const { 注册规划设置 } = await import("./组件/规划器设置.js");
            await 注册规划设置(app);
        } catch (e) {
            console.warn("[长视频规划师] 规划设置注册跳过:", e);
        }
        // 段级进度走**自有**通道（后端 节点/长视频规划师.py 的 _广播进度 发 _进度事件名），事件名是前后端
        // 字面量镜像，同步锁见 测试/测试_常量同步.py。
        // ⚠️ 这里**刻意不再监听**宿主的 legacy "progress"：那条事件由 KSampler 的内部去噪步进触发
        // （宿主 main.py 的 hijack_progress 全局 hook），其 node_id 取自执行上下文＝本长视频规划师节点，
        // 与我方段级进度同 node_id ⇒ 按 node 过滤也分不开，只会让状态条在「生成中 3/7」（段）与
        // 「5/20」（去噪步）之间来回跳。而 api.execution.set_progress 根本不发 "progress"，
        // 所以旧写法下面板从来没显示过段级进度，显示的全是去噪步。缘由详 _广播进度 docstring。
        // 3.1(98)：后端 payload 新增 run/stage/segment/stage_done/stage_total；本处：
        //   • 丢弃 stale run（旧轮迟到的事件）：按 node 维记录最新 run，execution_start 时重置（一个 prompt 一个 run）
        //   • 把完整 detail 交下来给 设进度，面板展示“采样/解码 阶段 x/y・段 z”
        const 最新run按节点 = new Map();
        api.addEventListener("execution_start", () => 最新run按节点.clear());
        api.addEventListener("长视频规划师_进度", (e) => {
            const d = e.detail || {};
            const 绑定 = 面板?.取节点();
            // 按绑定节点过滤：多节点工作流下只显示当前正在编辑的那个长视频规划师的进度。
            if (!绑定 || String(d.node) !== String(绑定.id)) return;
            const 键 = String(d.node);
            if (d.run) {
                const 已知 = 最新run按节点.get(键);
                if (已知 && 已知 !== d.run) return;   // stale run 丢弃
                最新run按节点.set(键, d.run);
            }
            面板?.设进度(d.value, d.max, d);
        });
        api.addEventListener("execution_success", () => 面板?.设状态("完成"));
        api.addEventListener("execution_error", (e) => 面板?.设状态("失败：" + (e.detail?.message || "")));
    },

    nodeCreated(node) {
        if (node.comfyClass !== 节点类) return;
        隐藏状态栏widget(node);
        // 「编辑」按钮：toggle——已绑定本节点且展开则折叠，否则绑定并展开
        // 防重复：若节点已有编辑 widget（重载/热更新场景），跳过
        if (!(node.widgets || []).some(w => w.name === "编辑")) {
            const 编辑钮 = node.addWidget("button", "编辑", null, () => {
                const p = 确保面板();
                if (!p) return;
                if (p.取节点() === node && p.状态.取("展开")) { p.收起(); return; }
                p.绑定节点(node);
                p.展开();
            }, { serialize: false });
            // 纯前端控件：graphToPrompt 按 widget 名把值写进 prompt inputs，未声明的键会让交接图判定整图拒绝；存档也不占 widgets_values 槽（08 §1 自建控件口径）。
            编辑钮.serialize = false;
        }
        // 挂载节点内多段时间轴（DOM 富 widget）
        // 宿主不等待 nodeCreated：同步挂载，默认尺寸必须在 configure 恢复保存尺寸之前设置。
        const 时间轴 = 挂载时间轴(node, 面板);
        const 原移除 = node.onRemoved;
        node.onRemoved = function () {
            // 撤销删除可能复用节点实例，移除时即废弃旧响应，不能等提交时才看归属。
            使节点快照失效(this);
            时间轴?.destroy?.();   // 3.3(121)：统一销毁——摘掉本节点时间轴对状态桥的订阅，避免僵尸监听器
            return 原移除?.apply(this, arguments);
        };
        const 原配置 = node.onConfigure;
        node.onConfigure = function () {
            // 同实例恢复即使 JSON 相同，也不能接受恢复前发起的异步回写。
            使节点快照失效(this);
            // 🔒 剪辑草稿 迁移（fix18a3）：旧工作流把草稿存在 widget 里；新真源在 node.properties。
            //   若 properties 尚无草稿且 widget 持有非默认值，则迁移并重置 widget（隔离执行缓存）。
            const 草w = 取widget(this, "剪辑草稿");
            const 默认草 = '{"brief":{},"segments":[]}';
            if (草w) {
                if (this.properties?.剪辑草稿 === undefined && 草w.value && 草w.value !== 默认草) {
                    (this.properties ||= {}).剪辑草稿 = 草w.value;
                }
                草w.value = 默认草;   // widget 恒为默认值，不再承载数据
            }
            const 结果 = 原配置?.apply(this, arguments);
            // widget 值已由宿主恢复；这里只刷新 DOM，不写回参数或重新计算节点尺寸。
            时间轴.渲染();
            return 结果;
        };
    },

    async loadedGraphNode(node) {
        if (node.comfyClass !== 节点类) return;
        隐藏状态栏widget(node);
        面板?.绑定节点(node);   // 载入既有工作流时回填
    },
});
