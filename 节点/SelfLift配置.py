# -*- coding: utf-8 -*-
"""SelfLift 渐进分辨率采样的可选配置节点：四个 widget 归一成 Custom 产物，交给 长视频规划师。"""
from comfy_api.latest import io


class SelfLift配置(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        if "." in __package__:                                  # ComfyUI 运行时（包形式加载）
            from ..执行.H3潜空间放大 import 列兼容H3放大模型
        else:                                                   # pytest（插件根在 sys.path）
            from 执行.H3潜空间放大 import 列兼容H3放大模型
        return io.Schema(
            # node_id 是工作流里序列化的数据键（改名会让旧存档找不到节点类型），只动 display_name
            node_id="SelfLift配置", display_name="SelfLift加速",
            category="长视频规划师",
            description=(
                "作用：把每段的前若干去噪步放到更小的画布上跑，抬升到目标分辨率后再跑完剩下的步。"
                "总去噪步数不变，省下来的是前几步的计算量。\n"
                "\n"
                "用法：把本节点的「SelfLift配置」口连到 长视频规划师 最下方那个「SelfLift配置」输入，即启用。"
                "不连线＝单阶段采样，段缓存也不受影响。启用后主节点「采样器」必须选 euler。\n"
                "\n"
                "参数：\n"
                "· 低清缩放：低清画布 = 目标画布 × 本值，再对齐到 32 的倍数。0.5 时低清那几步的视频 token "
                "大约只有四分之一，0.65 约 42%；取整后若等于目标画布会报错。\n"
                "· 高清步数：按目标分辨率跑的步数。低清步数 = 主节点「步数」− 本值，两阶段各至少 1 步，"
                "所以步数要 ≥ 高清步数 + 1。默认 6 配默认步数 20＝低清 14 步。\n"
                "· 放大模型：抬升画质靠它，下拉框只列 models/latent_upscale_models/ 下符合 H3 24 通道 3D "
                "架构的 .safetensors（同目录里别的路径不适用于本节点，故不显示）；只抬升画面的空间尺寸，音频不参与。\n"
                "· 允许插值降级：没选模型时改走双线性抬升。只在临时看构图和运动时勾选，"
                "当成正式成片会出现可见伪影。\n"
                "\n"
                "注意事项：参数不合法一律在开跑前报错并点名是哪个参数，不会悄悄按普通采样跑。"
                "「低清缩放 / 高清步数 / 放大模型」任一项一改，全部段都要重跑（这几项写在每段的缓存指纹里）。"
                "帧数、时长、声音和成片尺寸都不受影响。⚠️ 提速倍数和抬升后的画质目前还没有显卡实测数据，"
                "可设环境变量 H3_计时=1，看日志里「段N 渐进采样细分」拆出的低清采样、抬升、高清采样各花多久。"
            ),
            inputs=[
                io.Float.Input("低清缩放", default=0.5, min=0.25, max=0.95, step=0.05,
                               tooltip="低清画布 = 目标画布 × 本值（再对齐到 32 倍数）。0.5 时低清单步视频 token 约为 1/4；"
                                       "取整后若等于目标画布会直接报错"),
                io.Int.Input("高清步数", default=6, min=1, max=10000, step=1,
                             tooltip="以目标分辨率跑的步数；低清步数 = 节点「步数」− 本值。两阶段各至少 1 步"),
                # widget 的 id 同样是工作流 JSON 里的数据键，改名只动 display_name
                io.Combo.Input("放大权重", display_name="放大模型", options=列兼容H3放大模型(), default="未选择",
                               tooltip="只列 models/latent_upscale_models/ 下符合 H3 24 通道 3D 架构的 safetensors；"
                                       "只抬升视频支，音频不参与"),
                io.Boolean.Input("允许插值降级", default=False,
                                 tooltip="未选放大模型时是否改用双线性插值抬升（不加载任何网络，但成片会出现可见伪影）"),
            ],
            outputs=[io.Custom("LVP_SELFLIFT_CONFIG").Output("SelfLift配置")],
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

    @classmethod
    def validate_inputs(cls, 放大权重):
        """把「旧存档里选过的模型后来被筛掉」这类失效值报成人话，取代宿主的通用 value_not_in_list。

        宿主那条只回显数据键 id（放大权重）和整表 options，用户看不出「刚才还能选的东西为什么现在不行」。
        这里不新增失败面：连线值不在 options 里时宿主本来就会拒收，只是换成能照着做的中文文案。
        形参只列本输入——宿主按这份名单逐项跳过自身的通用检查（execution.py:1019），
        低清缩放/高清步数的 min/max 与布尔转换仍由宿主执行；语义门控照旧留在 执行核心。"""
        if "." in __package__:
            from ..执行.H3潜空间放大 import 列兼容H3放大模型
        else:
            from 执行.H3潜空间放大 import 列兼容H3放大模型
        if 放大权重 in 列兼容H3放大模型():
            return True
        return (f"「放大模型」里的 {放大权重} 已不在可加载清单：文件被删除、改名，"
                f"或不符合 H3 24 通道 3D 架构。请在下拉里重选一个，"
                f"或改选「未选择」并勾选「允许插值降级」。")
