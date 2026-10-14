import { app } from "../../scripts/app.js";
import * as 宿主接口 from "../../scripts/api.js";
import { 交接类型, 创建交接控制器 } from "./组件/交接提交.js";

const 节点定义 = new Map();

const 控制器 = 创建交接控制器({
    app,
    api: 宿主接口.api,
    取定义(名称) {
        const 已收集 = 节点定义.get(名称);
        const 类型 = globalThis.LiteGraph?.registered_node_types?.[名称] ?? 已收集?.类型;
        return 类型?.nodeData ?? 已收集?.数据;
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
    beforeConfigureGraph() {
        控制器.失效全部();
    },
    setup() {
        控制器.安装();
    },
});
