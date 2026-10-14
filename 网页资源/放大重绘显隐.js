import { app } from "../../scripts/app.js";

// 放大和重绘节点的组件显隐：「放大方式」决定两个权重下拉里显示哪一个，「重绘开关」决定五个重绘参数。
// 顺带管节点尺寸：新建时默认宽加倍，此后换档/切屏只按可见组件重算高度，宽度以存档或用户拖出的为准。
// 🔒 这里一律按 widget 的**数据键**匹配（widget.name＝schema 的 id）：显示名是后端 display_name 改的
// 「重绘×」，按标签匹配会在改名当天静默失效（组件不再隐藏，而界面承诺的是「关了就不显示」）。
// 数据键真源在 Python（节点/精修与放大.py），前端清单由 测试/测试_常量同步.py 的镜像锁把住。
const 节点类 = "精修与放大";
const 方式widget名 = "放大方式";
const H3权重widget名 = "H3放大权重";
const 像素权重widget名 = "像素放大模型";
const 开关widget名 = "重绘开关";
// 三项与后端 options 同序；Lanczos 两档都不显示，故只作清单完整性用。
const 放大方式值 = ["H3潜空间", "像素模型", "Lanczos"];
const 重绘widget名 = ["精修强度", "精修步数", "精修种子", "采样器", "调度器"];
const [方式H3, 方式像素] = 放大方式值;
const 默认宽倍数 = 2;   // 新建时的默认宽＝宿主算出的宽度 × 本值；只在新建那一轮生效，存档尺寸优先

const 取widget = (node, 名) => (node.widgets || []).find(w => w.name === 名);

function 设显隐(widget, 可见) {
    const 隐藏 = !可见;
    // 双路径：canvas 布局走 widget.hidden（getLayoutWidgets/isWidgetVisible 读它），
    // Vue 渲染路径读 options.hidden；只设一处会留下占高或能点到的幽灵控件。
    if (!!widget.hidden === 隐藏 && (widget.options || {}).hidden === 隐藏) return false;
    widget.hidden = 隐藏;
    (widget.options ||= {}).hidden = 隐藏;
    return true;
}

function 应用显隐(node) {
    const 方式 = 取widget(node, 方式widget名)?.value;
    const 重绘 = !!取widget(node, 开关widget名)?.value;
    const 目标 = new Map([[H3权重widget名, 方式 === 方式H3], [像素权重widget名, 方式 === 方式像素]]);
    for (const 名 of 重绘widget名) 目标.set(名, 重绘);
    let 变了 = false;
    for (const [名, 可见] of 目标) {
        const widget = 取widget(node, 名);
        if (widget && 设显隐(widget, 可见)) 变了 = true;
    }
    if (!变了 && !node._lvp需加倍) return;          // 值没变就不重排，别抢用户手动拖过的节点尺寸
    const [算宽, 算高] = node.computeSize();
    // 宽度只取「更宽的一方」：宿主 computeSize 完全不看当前尺寸、只按标签与控件内容算，
    // 拿它直接 setSize 会把用户拉宽的节点打回默认宽（换档、切屏各触发一次）。只有高度必须跟可见组件数收。
    let 宽 = Math.max(node.size?.[0] ?? 算宽, 算宽);
    if (node._lvp需加倍) { 宽 *= 默认宽倍数; node._lvp需加倍 = false; }
    node.setSize?.([宽, 算高]);
    node.setDirtyCanvas?.(true, true);
}

function 挂钩(node, 名) {
    const widget = 取widget(node, 名);
    if (!widget || widget._lvp显隐挂钩) return;   // 幂等：模块热重载或双钩子同轮触发不二次包装
    const 原回调 = widget.callback;
    widget.callback = function (...args) {
        原回调?.apply(this, args);               // 宿主的标脏/联动必须照常
        应用显隐(node);
    };
    widget._lvp显隐挂钩 = true;
}

function 挂钩配置(node) {
    if (node._lvp显隐配置钩) return;
    const 原配置 = node.configure;
    // 粘贴/克隆是把 widgets_values 直接塞回 widget，不走 widget.callback：
    // 宿主又没有 paste 后的逐节点钩子，只能在 configure 收尾处按新值纠正一次。
    node.configure = function (...args) {
        const 结果 = 原配置.apply(this, args);
        node._lvp需加倍 = false;      // 走到 configure＝有存档/克隆尺寸，那一份说了算，不再乘默认倍数
        应用显隐(node);
        return 结果;
    };
    node._lvp显隐配置钩 = true;
}

function 装配(node, 来源) {
    if (node.comfyClass !== 节点类) return;
    if (来源 === "创建") {
        // 只有拖出来/双击新建的节点才加倍默认宽：graph.configure 期间宿主自己会回填存档尺寸，
        // 而 nodeCreated 走 invokeExtensionsAsync，续体有可能晚于 configure，故 loadedGraphNode 到过的也不再加倍。
        if (!node._lvp已载入 && !app.configuringGraph) node._lvp需加倍 = true;
    } else {
        node._lvp已载入 = true;
    }
    挂钩(node, 方式widget名);
    挂钩(node, 开关widget名);
    挂钩配置(node);
    应用显隐(node);
}

app.registerExtension({
    name: "ComfyUI-AI-Video-Planner.放大重绘显隐",
    nodeCreated: (node) => 装配(node, "创建"),
    loadedGraphNode: (node) => 装配(node, "载入"),
    // configure 回填 widget 值不走回调：重载/粘贴后按整图当前值再兜一遍，避免留下上一次的显隐。
    afterConfigureGraph() {
        for (const node of app.graph?._nodes || []) {
            if (node.comfyClass === 节点类) 装配(node, "载入");
        }
    },
});
