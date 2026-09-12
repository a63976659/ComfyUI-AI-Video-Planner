// 状态栏/时间轴 ↔ node.widgets（节点为唯一真源）。不依赖 app，便于复用与测试。

export function 取widget(node, 名) {
    return (node?.widgets || []).find((w) => w.name === 名);
}

function 标脏(node) {
    node?.setDirtyCanvas?.(true, true);
    node?.graph?.setDirtyCanvas?.(true, true);
}

export function 读JSON(node, 名, 回退) {
    const w = 取widget(node, 名);
    try {
        const v = JSON.parse(w?.value ?? "null");
        return v ?? 回退;
    } catch {
        return 回退;
    }
}

export function 写值(node, 名, 值) {
    const w = 取widget(node, 名);
    if (!w) return false;
    w.value = 值;
    标脏(node);
    return true;
}

export function 写JSON(node, 名, 对象) {
    return 写值(node, 名, JSON.stringify(对象));
}

// 便捷真源读写（字段名与节点 widget 一致）
export const 真源 = {
    读任务类型: (n) => 取widget(n, "任务类型")?.value,
    写任务类型: (n, v) => 写值(n, "任务类型", v),
    读全局提示词: (n) => 取widget(n, "全局提示词")?.value ?? "",
    写全局提示词: (n, v) => 写值(n, "全局提示词", v),
    读参考素材: (n) => 读JSON(n, "参考素材", { 图片: [], 音频: [], 视频: [] }),
    写参考素材: (n, v) => 写JSON(n, "参考素材", v),
    读参考共用: (n) => !!取widget(n, "参考共用")?.value,
    写参考共用: (n, v) => 写值(n, "参考共用", !!v),
    读时间轴: (n) => 读JSON(n, "时间轴数据", { segments: [] }),
    写时间轴: (n, v) => 写JSON(n, "时间轴数据", v),
    读运行选择: (n) => 读JSON(n, "运行选择", {}),
    写运行选择: (n, v) => 写JSON(n, "运行选择", v),
    读输出分辨率: (n) => 取widget(n, "输出分辨率")?.value,
    写输出分辨率: (n, v) => 写值(n, "输出分辨率", v),
    读百万像素: (n) => 取widget(n, "百万像素")?.value,
    写百万像素: (n, v) => 写值(n, "百万像素", v),
};
