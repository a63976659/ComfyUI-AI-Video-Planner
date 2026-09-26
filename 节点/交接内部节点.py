"""协调器专用 V3 节点；真实上下文、归属和状态验证均由协调器负责。"""
from comfy_api.latest import io


class LVP_交接写入(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="LVP_交接写入", category="_长视频规划师/交接内部",
            inputs=[io.Custom("LVP_FIRST_PASS").Input("初采产物"),
                    io.String.Input("job_id"), io.Int.Input("attempt"), io.String.Input("nonce")],
            outputs=[], is_output_node=True, is_dev_only=True, not_idempotent=True,
        )

    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        return float("nan")

    @classmethod
    def execute(cls, 初采产物, job_id, attempt, nonce):
        if "." in __package__:
            from ..执行.跨任务清理 import 取得协调器
        else:
            from 执行.跨任务清理 import 取得协调器
        _, receipt = 取得协调器().保存任务初采(初采产物, job_id, attempt, nonce)
        return io.NodeOutput(ui={"lvp_handoff": [receipt]})


class LVP_阶段清理(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="LVP_阶段清理", category="_长视频规划师/交接内部",
            inputs=[io.String.Input("job_id"), io.Int.Input("attempt"), io.String.Input("nonce")],
            outputs=[], is_output_node=True, is_dev_only=True, not_idempotent=True,
        )

    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        return float("nan")

    @classmethod
    def execute(cls, job_id, attempt, nonce):
        if "." in __package__:
            from ..执行.跨任务清理 import 取得协调器
        else:
            from 执行.跨任务清理 import 取得协调器
        receipt = 取得协调器().请求阶段清理(job_id, attempt, nonce)
        return io.NodeOutput(ui={"lvp_handoff": [receipt]})


class LVP_二采入口(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="LVP_二采入口", category="_长视频规划师/交接内部",
            inputs=[io.String.Input("job_id"), io.Int.Input("attempt"), io.String.Input("nonce")],
            outputs=[io.Boolean.Output("门控通过")], is_output_node=True,
            enable_expand=True, is_dev_only=True, not_idempotent=True,
        )

    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        return float("nan")

    @classmethod
    def execute(cls, job_id, attempt, nonce):
        if "." in __package__:
            from ..执行.跨任务清理 import 取得协调器
        else:
            from 执行.跨任务清理 import 取得协调器
        expanded_graph, receipt = 取得协调器().核验二采门控(job_id, attempt, nonce)
        # 当前宿主的展开分支要求非 None result；仅返回门控标量，不保留业务数据。
        return io.NodeOutput(True, expand=expanded_graph, ui={"lvp_handoff": [receipt]})


class LVP_读取初采引用(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="LVP_读取初采引用", category="_长视频规划师/交接内部",
            inputs=[io.String.Input("job_id"), io.Int.Input("attempt"), io.String.Input("nonce")],
            outputs=[io.Custom("LVP_FIRST_PASS").Output("初采产物")],
            is_dev_only=True, not_idempotent=True,
        )

    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        return float("nan")

    @classmethod
    def execute(cls, job_id, attempt, nonce):
        if "." in __package__:
            from ..执行.跨任务清理 import 取得协调器
        else:
            from 执行.跨任务清理 import 取得协调器
        ref = 取得协调器().读取任务初采(job_id, attempt, nonce)
        return io.NodeOutput(ref)
