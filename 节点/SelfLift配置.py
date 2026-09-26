# -*- coding: utf-8 -*-
"""SelfLift 渐进分辨率采样的可选配置节点：四个 widget 归一成 Custom 产物，交给 长视频规划师。"""
from comfy_api.latest import io


class SelfLift配置(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        if "." in __package__:                                  # ComfyUI 运行时（包形式加载）
            from ..执行.H3潜空间放大 import 列H3放大权重
        else:                                                   # pytest（插件根在 sys.path）
            from 执行.H3潜空间放大 import 列H3放大权重
        return io.Schema(
            node_id="SelfLift配置", display_name="SelfLift配置",
            category="长视频规划师",
            description=("渐进分辨率采样的参数，连到 长视频规划师 的「SelfLift配置」输入即启用；"
                         "不连接时段照常单阶段采样、段缓存不受影响。启用后每段的前若干去噪步跑在低清画布"
                         "（视频 token 数按缩放平方减少），抬升到目标分辨率后再跑完剩余步；总去噪步数不变。"
                         "节点「采样器」必须为 euler（过渡公式只对确定性一阶步成立），参数不合法会在采样前"
                         "报错并点名是哪个参数，不会静默回退普通采样。抬升质量取决于 H3 潜空间放大权重；未选权重时"
                         "只有显式勾选「允许插值降级」才用双线性插值抬升（画质明显更差）。"),
            inputs=[
                io.Float.Input("低清缩放", default=0.5, min=0.25, max=0.95, step=0.05,
                               tooltip="低清画布 = 目标画布 × 本值（再对齐到 32 倍数）。0.5 时低清单步视频 token 约为 1/4；"
                                       "取整后若等于目标画布会直接报错"),
                io.Int.Input("高清步数", default=6, min=1, max=10000, step=1,
                             tooltip="以目标分辨率跑的步数；低清步数 = 节点「步数」− 本值。两阶段各至少 1 步"),
                io.Combo.Input("放大权重", options=列H3放大权重(), default="未选择",
                               tooltip="models/latent_upscale_models/ 下的 24 通道 3D safetensors；只抬升视频支，音频不参与"),
                io.Boolean.Input("允许插值降级", default=False,
                                 tooltip="未选放大权重时是否改用双线性插值抬升（不加载任何网络，但细节明显更糊）"),
            ],
            outputs=[io.Custom("LVP_SELFLIFT_CONFIG").Output("配置")],
        )

    @classmethod
    def execute(cls, 低清缩放, 高清步数, 放大权重, 允许插值降级):
        """只做类型归一；语义门控在 执行核心 采样前统一做（那里才知道 步数/采样器/宽高）。

        不在此报错：本节点常处于「连了但参数还没调好」的状态，报错会让每次执行都红一次，
        而真正的启用判定属于消费方。"""
        if "." in __package__:
            from ..执行.渐进采样 import 构造配置
        else:
            from 执行.渐进采样 import 构造配置
        return io.NodeOutput(构造配置(低清缩放, 高清步数, 放大权重, 允许插值降级))
