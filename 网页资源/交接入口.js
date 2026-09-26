import { app } from "../../scripts/app.js";
import * as 宿主接口 from "../../scripts/api.js";
import { 交接类型, 创建交接控制器 } from "./组件/交接提交.js";

const 节点定义 = new Map();
const 节点控件 = new WeakMap();

function 挂载节点(节点) {
    if (节点.comfyClass !== 交接类型 || 节点控件.has(节点)) return;
    if (节点.widgets?.some(控件 => 控件.name === "交接状态")) return;
    const 状态 = 节点.addWidget("text", "交接状态", "未运行", () => {}, { serialize: false, readOnly: true });
    const 取消 = 节点.addWidget("button", "取消交接", null, () => 控制器.取消(节点), { serialize: false });
    const 重试 = 节点.addWidget("button", "仅重跑二采", null, () => 控制器.重试(节点), { serialize: false });
    for (const 控件 of [状态, 取消, 重试]) {
        控件.serialize = false;
        控件.serializeValue = () => undefined;
    }
    节点控件.set(节点, 状态);
    const 原删除 = 节点.onRemoved;
    节点.onRemoved = function (...参数) {
        控制器.失效节点(this);
        return 原删除?.apply(this, 参数);
    };
}

const 控制器 = 创建交接控制器({
    app,
    api: 宿主接口.api,
    取定义(名称) {
        const 已收集 = 节点定义.get(名称);
        const 类型 = globalThis.LiteGraph?.registered_node_types?.[名称] ?? 已收集?.类型;
        return 类型?.nodeData ?? 已收集?.数据;
    },
    挂载节点,
    显示(节点, 文本) {
        const 控件 = 节点控件.get(节点);
        if (!控件) return;
        控件.value = 文本;
        节点.setDirtyCanvas?.(true, false);
    },
    创建错误(消息, 状态, 节点ID) {
        const 详情 = { type: "lvp_handoff_error", message: 消息, details: "", extra_info: {} };
        const 响应 = { error: 详情, node_errors: {} };
        if (节点ID != null) 响应.node_errors[节点ID] = { errors: [详情], class_type: 交接类型, dependent_outputs: [] };
        if (typeof 宿主接口.PromptExecutionError === "function") {
            return new 宿主接口.PromptExecutionError(响应, 状态);
        }
        const 错误 = new Error(消息);
        错误.name = "PromptExecutionError";
        错误.response = 响应;
        错误.status = 状态;
        return 错误;
    },
});

app.registerExtension({
    name: "ComfyUI-AI-Video-Planner.初采交接",
    beforeRegisterNodeDef(类型, 数据) {
        节点定义.set(数据.name, { 类型, 数据 });
    },
    nodeCreated: 挂载节点,
    loadedGraphNode: 挂载节点,
    beforeConfigureGraph() {
        控制器.失效全部();
    },
    setup() {
        控制器.安装();
    },
});
