"""可选交接分图标记；常规工作流执行不能绕过协调器提交。"""
from comfy_api.latest import io


class 初采交接与清理(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="初采交接与清理",
            display_name="初采交接与清理",
            category="长视频规划师",
            description=("可选的初采交接边界，请从节点交接提交入口运行，由协调器提交初采、清理、二采阶段。"
                         "阶段清理影响宿主全局缓存及已加载模型，也会影响其他工作流的缓存复用；"
                         "本节点不直接清理或写盘。不使用本节点时保持内存直连。"),
            inputs=[io.Custom("LVP_FIRST_PASS").Input("初采产物")],
            outputs=[io.Custom("LVP_FIRST_PASS").Output("初采产物")],
        )

    @classmethod
    def execute(cls, 初采产物):
        raise RuntimeError("初采交接与清理不能通过常规执行透传；请从节点交接提交入口运行，由协调器提交。")
