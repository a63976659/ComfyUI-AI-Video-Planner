import { 取操作忙, 开始操作, 结束操作 } from "./操作锁.js";
// 计划数据：把当前节点的全部 widget + 时间轴打包保存到 插件根/计划数据/<名>.json，
// 下次通过下拉一键加载复原。UI 位于状态栏提示词编辑区上方的工具行末尾（居右）。
//
// 组件契约：
//   取节点()  → 当前绑定的长视频规划师节点（无绑定返回 null，保存/加载 toast 提示）
//   计划已加载() → 恢复规划表单与两条时间轴；取规划编辑状态() → 覆盖确认与表单并发保护
//
// 后端契约：GET /lvp/plan/list、GET /lvp/plan/load?name=X、POST /lvp/plan/save
//   加载返回 {数据, 缺失素材, 缺草稿, 格式版本, 修订}：
//   · 缺失素材＝已不在媒体池的参考素材文件名，服务端**保留原引用不剔除**
//     （refs 位置即 <Picture N> 标签，压缩会使其余素材前移错指），仅登记供 toast；加载不阻断，
//     真正拦截在执行前（采样前阻止引用缺失素材的可运行段）。
//   · 缺草稿＝该计划未含有效 剪辑草稿（旧版 v1 或空草稿）：确认加载后清空节点上不相干的旧草稿
//     并恢复默认表单，**不从执行 全局提示词 伪造 brief**；同时向用户明确提示。
//   · 旧数据（v1 段无 segment_id）加载时就地补齐稳定 segment_id（A3），后续保存固定该 id。
//   · 格式版本与修订号分离（schema vs 编辑轮次）；高于当前支持的未来版本后端直接 400 拒绝。
//
// 复用 ComfyUI 原生对话框（extensionManager.dialog.prompt/confirm，Vue 风格 + Promise），
// 与 提示词编辑器.js 的 弹确认() 同源；老版本 ComfyUI 无原生框时退回 window.prompt/confirm。
import { app } from "../../../scripts/app.js";
import { 真源, 取widget, 写值, 捕获节点快照, 提交节点快照, 分配段ID } from "./桥接/节点桥.js";

const 列表接口 = "/lvp/plan/list";
const 加载接口 = "/lvp/plan/load";
const 保存接口 = "/lvp/plan/save";
const 无 = "（加载）";
const 控件样式 = "background:var(--comfy-input-bg,#1c1c1c);color:var(--fg-color,#ddd);border:1px solid var(--border-color,#444);border-radius:3px;max-width:180px";
// 与后端 计划路由.安全名 的 _非法名字符 + _名最长 逐字对齐（前端预校验一次给用户即时反馈，
// 后端仍会二次校验，前端漏过的非法名不会写坏磁盘）。
const 非法名字符 = /[\\/:*?"<>|\x00-\x1f]/;
const 名最长 = 100;
// 参与保存的普通 widget（值直接落 JSON）：与 节点/长视频规划师.py 的 inputs 一一对应，
// 但排除已在 真源 里有专属读写方法的 任务类型/全局提示词/输出分辨率/百万像素/参考共用/尾帧锚定/
// 运行选择/时间轴数据/参考素材（那些走 真源.读/写，JSON 字段自动 stringify/parse）。
const 直读widget名 = ["帧率", "步数", "采样器", "调度器"];

function toast(文本) { app?.ui?.toast?.showMessage?.(文本); }

async function 弹确认(标题, 消息) {
    const 框 = app?.extensionManager?.dialog;
    if (框?.confirm) {
        try { return !!(await 框.confirm({ title: 标题, message: 消息 })); }
        catch { return false; }
    }
    return window.confirm(`${标题}\n\n${消息}`);
}

async function 弹输入(标题, 消息, 默认值 = "") {
    const 框 = app?.extensionManager?.dialog;
    if (框?.prompt) {
        // 原生 prompt：确认→输入串、取消/关闭→null；异常一律按取消处理，绝不再弹 window.prompt 造成双框
        try { return await 框.prompt({ title: 标题, message: 消息, defaultValue: 默认值 }); }
        catch { return null; }
    }
    return window.prompt(`${标题}\n\n${消息}`, 默认值);
}

// 前端预校验（与后端 安全名 同源规则）；返回净名或空串
function 校验名(名) {
    if (typeof 名 !== "string") return "";
    const 净 = 名.trim();
    if (!净 || 净 === "." || 净 === "..") return "";
    if (非法名字符.test(净)) return "";
    if (净[0] === "." || 净[0] === " " || 净[净.length - 1] === "." || 净[净.length - 1] === " ") return "";
    if (净.length > 名最长) return "";
    return 净;
}

export function 创建计划数据(容器, { 取节点, 计划已加载, 取规划编辑状态, 取在途, 状态 }) {
    const 组 = document.createElement("label");
    // margin-left:auto 把整组推到工具行最右（工具行不换行；窄屏溢出时 auto 边距归零，本组紧随前组继续排）
    组.style.cssText = "display:flex;align-items:center;gap:4px;margin-left:auto";
    组.title = "把当前节点的全部参数与时间轴保存到 插件根/计划数据/<名>.json；下次一键加载复原";
    组.textContent = "计划数据";

    const 加载sel = document.createElement("select");
    加载sel.style.cssText = 控件样式;
    加载sel.title = "选择已保存的计划加载到当前节点（已有时间轴、剪辑草稿或规划表单内容时确认覆盖）";

    const 保存钮 = document.createElement("button");
    保存钮.className = "lvp-胶囊"; 保存钮.type = "button";
    保存钮.textContent = "保存";
    保存钮.title = "把当前节点的所有参数与时间轴保存为计划（同名二次确认后覆盖）";

    组.append(加载sel, 保存钮);
    容器.appendChild(组);

    let 计划列表 = [];

    function 建项(值, 标签) {
        const o = document.createElement("option");
        o.value = 值; o.textContent = 标签;
        return o;
    }

    // replaceChildren + textContent 重建（不走 innerHTML）：计划名来自磁盘文件名，
    // 当作纯文本插入，不给文件名里出现 < > 时变成标记的机会（与 画风预设选择.刷新选项UI 同源）。
    function 刷新选项UI() {
        加载sel.replaceChildren(建项("", 无), ...计划列表.map((p) => 建项(p.名, p.名)));
        // 不保留选中态：加载完把值清回 ""，避免"再次选同一个"因为 value 未变而不触发 change
        加载sel.value = "";
    }

    async function 刷新列表() {
        let data;
        try {
            const res = await fetch(列表接口);
            data = await res.json();
            if (!res.ok) throw new Error(data?.error || `HTTP ${res.status}`);
        } catch (e) {
            // 拉取失败保留已有清单（不清空），只留控制台痕迹：计划缺失不该淹没整个状态栏
            console.warn("[长视频规划师] 计划列表拉取失败：", e);
            return;
        }
        计划列表 = Array.isArray(data?.计划) ? data.计划 : [];
        刷新选项UI();
    }

    // 收集当前节点全部要保存的字段（与后端 计划加载 返回结构对称）
    function 收数据(node) {
        const 数据 = {
            任务类型: 真源.读任务类型(node) ?? "",
            全局提示词: 真源.读全局提示词(node) ?? "",
            输出分辨率: 真源.读输出分辨率(node) ?? "",
            百万像素: 真源.读百万像素(node),
            参考共用: 真源.读参考共用(node),
            尾帧锚定: 真源.读尾帧锚定(node),
            运行选择: 真源.读运行选择(node),
            时间轴: 真源.读时间轴(node),
            参考素材: 真源.读参考素材(node),
            // 剪辑草稿 真源＝node.properties（隔离执行缓存，不入执行 widget/不入 prompt）；
            //   随存档一并保存，下次加载完整往返（A2）。
            剪辑草稿: 真源.读剪辑草稿(node),
        };
        if (node.properties?.规划分集编辑?.分集) 数据.分集编辑 = JSON.parse(JSON.stringify(node.properties.规划分集编辑));
        for (const 名 of 直读widget名) {
            const v = 取widget(node, 名)?.value;
            if (v !== undefined) 数据[名] = v;
        }
        return 数据;
    }

    // 应用计划数据到节点：仅写字段存在的项（未来新增 widget 时老计划缺该字段 → 保持当前值不覆盖）。
    // 例外：剪辑草稿——无论字段是否存在都要写（A2）：自带有效草稿则恢复，缺草稿（旧计划无草稿）
    //   则写默认空草稿以**清除节点上不相干的旧 brief**，不从执行 prompt 伪造。
    function 应数据(node, 数据, 缺草稿) {
        if (!数据 || typeof 数据 !== "object") return;
        if (数据.任务类型 != null) 真源.写任务类型(node, 数据.任务类型);
        if (数据.全局提示词 != null) 真源.写全局提示词(node, 数据.全局提示词);
        if (数据.输出分辨率 != null) 真源.写输出分辨率(node, 数据.输出分辨率);
        if (数据.百万像素 != null) 真源.写百万像素(node, 数据.百万像素);
        if (数据.参考共用 != null) 真源.写参考共用(node, 数据.参考共用);
        if (数据.尾帧锚定 != null) 真源.写尾帧锚定(node, 数据.尾帧锚定);
        if (数据.运行选择 != null) 真源.写运行选择(node, 数据.运行选择);
        if (数据.时间轴 != null) 真源.写时间轴(node, 数据.时间轴);
        if (数据.参考素材 != null) 真源.写参考素材(node, 数据.参考素材);
        // 剪辑草稿 总写：有效草稿→恢复（旧段缺 segment_id 则就地补齐，A3），否则→默认空草稿。
        const 草 = 数据.剪辑草稿;
        const 有效 = !缺草稿 && 草 && typeof 草 === "object" && (草.brief || 草.segments);
        if (有效) 分配段ID(草.segments);
        真源.写剪辑草稿(node, 有效 ? 草 : { brief: {}, segments: [] });
        const 缓存 = 数据.分集编辑;
        if (有效 && 缓存?.项目 === 草.规划资料?.项目 && 缓存?.分集 && typeof 缓存.分集 === "object") {
            node.properties.规划分集编辑 = JSON.parse(JSON.stringify(缓存));
        } else delete node.properties.规划分集编辑;
        const 引用 = 有效 && 草.规划资料?.任务引用;
        if (引用?.id && 引用?.token) node.properties.规划成果任务 = { ...引用, stages: 草.规划资料?.阶段成果 || [] };
        else delete node.properties.规划成果任务;
        delete node.properties.规划任务缓存;
        for (const 名 of 直读widget名) {
            if (数据[名] != null) 写值(node, 名, 数据[名]);
        }
    }

    async function 保存() {
        const node = 取节点?.();
        if (!node) { toast("请先在画布上创建/选中一个长视频规划师节点"); return; }
        const 输入 = await 弹输入("保存计划数据", "输入计划名（不含扩展名）：");
        if (输入 == null) return;   // 用户取消
        const 净名 = 校验名(输入);
        if (!净名) {
            toast(`计划名非法：不能为空、不能含 \\ / : * ? " < > | 或控制字符、不能以点/空格开头结尾、长度 ≤ ${名最长}`);
            return;
        }
        const 已存 = 计划列表.some((p) => p.名 === 净名);
        if (已存) {
            const ok = await 弹确认("覆盖已有计划", `计划「${净名}」已存在，覆盖它？`);
            if (!ok) { toast("已取消，未保存"); return; }
        }
        try {
            const res = await fetch(保存接口, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ 名: 净名, 数据: 收数据(node) }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data?.error || `HTTP ${res.status}`);
            toast(`已保存：${净名}`);
            await 刷新列表();
        } catch (e) {
            toast("保存失败：" + (e?.message || e));
        }
    }

    async function 加载(名) {
        if (!名) return;
        // B3：加载会写 时间轴数据 + 剪辑草稿，流式批窗口内做这事会互相作废（两边都报错），一律先拒。
        if (取操作忙(状态) || 取在途?.()) { toast("当前操作进行中，请等待完成后再加载计划"); 加载sel.value = ""; return; }
        const node = 取节点?.();
        if (!node) { toast("请先在画布上创建/选中一个长视频规划师节点"); 加载sel.value = ""; return; }
        // 跨 await（覆盖确认 + 网络）后目标节点可能已换绑/删除/重配/内容被编辑：先捕获节点快照，
        // 提交时复核仍是同一目标才写回，过期回写一律丢弃（与填充/生成同源守卫，不另造状态系统）。
        //   加载会同时写 时间轴数据（widget）与 剪辑草稿（properties），两者都纳入守卫。
        const 快照 = 捕获节点快照(node, ["时间轴数据", "剪辑草稿"]);
        const 编辑状态 = 取规划编辑状态?.();
        const 当前 = 真源.读时间轴(node);
        const 段数 = Array.isArray(当前?.segments) ? 当前.segments.length : 0;
        const 草稿 = 真源.读剪辑草稿(node);
        const 草稿段数 = Array.isArray(草稿?.segments) ? 草稿.segments.length : 0;
        const 令牌 = 开始操作(状态, "加载计划");
        if (!令牌) { 加载sel.value = ""; return; }
        try {
            if (段数 > 0 || 草稿段数 > 0 || Object.keys(草稿?.brief || {}).length > 0 || 编辑状态?.有内容) {
                const ok = await 弹确认("覆盖当前计划",
                    `当前节点已有时间轴、剪辑草稿或规划表单内容，加载「${名}」将覆盖这些内容，继续？`);
                if (!ok) { 加载sel.value = ""; return; }
            }
            const res = await fetch(加载接口 + "?name=" + encodeURIComponent(名));
            const data = await res.json();
            if (!res.ok) throw new Error(data?.error || `HTTP ${res.status}`);
            if (编辑状态?.签名 !== 取规划编辑状态?.()?.签名) {
                toast("规划表单已变化，计划未应用，请重试"); return;
            }
            const 已提交 = 提交节点快照(快照, 取节点?.(), (目标) => 应数据(目标, data?.数据, data?.缺草稿));
            if (!已提交) { toast("节点、时间轴或草稿已变化，计划未应用，请重试"); return; }
            计划已加载?.();
            const 缺失 = Array.isArray(data?.缺失素材) ? data.缺失素材 : [];
            const 附注 = [];
            if (缺失.length) 附注.push(`跳过 ${缺失.length} 个缺失的参考素材：${缺失.join("、")}`);
            if (data?.缺草稿) 附注.push("该计划不含剪辑草稿，已清空草稿区并恢复默认表单（未从执行提示词伪造）");
            toast(附注.length ? `已加载：${名}（${附注.join("；")}）` : `已加载：${名}`);
        } catch (e) {
            toast("加载失败：" + (e?.message || e));
        } finally {
            结束操作(状态, 令牌);
            加载sel.value = "";   // 无论成败都清回占位，允许再次选同一条触发 change
        }
    }

    保存钮.onclick = 保存;
    加载sel.onchange = () => 加载(加载sel.value);

    刷新选项UI();   // 先渲染出只有「（加载）」占位的下拉，避免清单响应前是空白控件
    刷新列表();
    window.addEventListener("lvp-数据已变化", 刷新列表);

    return { 刷新列表, 重置选择: () => { 加载sel.value = ""; } };
}
