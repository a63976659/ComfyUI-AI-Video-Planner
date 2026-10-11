// 缓存面板 —— 节点工具条上的运行时段产物磁盘缓存统计、清理与失效版本编辑。
//
// 后端契约（见 后端路由/缓存路由.py）：
//   GET  /lvp/cache/stats → {版本, 根目录, 条目数, 大小字节}
//   POST /lvp/cache/clear → {版本, 删除数, 释放字节}   —— 只删当前版本目录内本模块产出的 .pt/.part（白名单）
// 失效版本 直写节点 widget「缓存失效版本」（经 真源 读写，与后端 execute 的 int 归一同源）：
//   原 widget 仅隐藏显示、仍参与保存与提交，改值即进宿主缓存签名 → 触发重跑；再叠加 执行核心.fingerprint_inputs 的
//   素材内容维（§B-4），共同保证「换模型手动作废」与「同名换素材自动作废」都真能重采样。
//
// 🔒 刻意**不在构造/展开/绑定时自动发 stats 请求**：只由「重新统计」按钮、以及清理成功后触发。
//   这样既有 异步回写隔离.test.mjs 的 fetch 白名单（仅 plan/plan/prompts）不被打乱。
import { 真源 } from "./桥接/节点桥.js";

const 查询接口 = "/lvp/cache/stats";
const 清理接口 = "/lvp/cache/clear";
const 样式已注入 = { v: false };

// 人类可读字节（与后端 执行核心._人类字节 同口径：B 取整、其余保留 1 位小数、量级自适应）。
export function 人类字节(字节) {
    let 数 = Number(字节);
    if (!Number.isFinite(数) || 数 < 0) 数 = 0;
    const 单位 = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    while (数 >= 1024 && i < 单位.length - 1) { 数 /= 1024; i += 1; }
    return i === 0 ? `${Math.round(数)}B` : `${数.toFixed(1)}${单位[i]}`;
}

function 注入样式() {
    if (样式已注入.v || typeof document === "undefined") return;
    const s = document.createElement("style");
    s.textContent = `
      .lvp-cache{display:contents}
      .lvp-cache统计{color:var(--p-text-muted-color,#8c8c8c);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:260px}
      .lvp-cache钮{padding:4px 9px;border:1px solid var(--border-color,#444);border-radius:6px;background:var(--comfy-input-bg,#2f2f2f);color:var(--fg-color,#ccc);cursor:pointer;font:inherit;white-space:nowrap}
      .lvp-cache钮:hover{border-color:var(--p-primary-color,#4a9eff)}
      .lvp-cache失{display:flex;align-items:center;gap:4px;white-space:nowrap}
      .lvp-cache输{width:56px;background:var(--comfy-input-bg,#1c1c1c);color:var(--fg-color,#ddd);border:1px solid var(--border-color,#444);border-radius:3px;padding:2px 4px;font:inherit}`;
    document.head.appendChild(s);
    样式已注入.v = true;
}

export function 创建缓存面板(容器, { 取节点, 弹确认, toast }) {
    注入样式();

    const 统计 = document.createElement("span");
    统计.className = "lvp-cache统计";
    统计.textContent = "段缓存：点「重新统计」查看";

    const 刷新钮 = document.createElement("button");
    刷新钮.className = "lvp-cache钮"; 刷新钮.type = "button"; 刷新钮.textContent = "重新统计";

    const 清理钮 = document.createElement("button");
    清理钮.className = "lvp-cache钮"; 清理钮.type = "button"; 清理钮.textContent = "清空段缓存";
    清理钮.title = "删除当前格式版本的全部段缓存 .pt（下次生成全部重采样）；不碰旧版本目录与其它文件";

    // 失效版本编辑（写节点 widget）
    const 失区 = document.createElement("span");
    失区.className = "lvp-cache失";
    const 失标 = document.createElement("span");
    失标.textContent = "失效版本";
    const 失输 = document.createElement("input");
    失输.className = "lvp-cache输"; 失输.type = "number"; 失输.min = "0"; 失输.step = "1"; 失输.value = "0";
    失输.title = "换模型/权重后手动 +1（或直接改数值）以整体作废段缓存重采样";
    const 加一钮 = document.createElement("button");
    加一钮.className = "lvp-cache钮"; 加一钮.type = "button"; 加一钮.textContent = "+1";

    失区.append(失标, 失输, 加一钮);
    容器.className = "lvp-cache";
    容器.append(统计, 刷新钮, 清理钮, 失区);

    async function 刷新() {
        统计.textContent = "统计中…";
        try {
            const res = await fetch(查询接口, { cache: "no-store" });
            const 数据 = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(数据?.error || `HTTP ${res.status}`);
            统计.textContent = `段缓存 ${数据.条目数 | 0} 项 · ${人类字节(数据.大小字节)} · 格式 ${数据.版本 || "?"}`;
        } catch (e) {
            统计.textContent = `统计不可用：${e.message || e}`;
        }
    }

    async function 清理() {
        const ok = await 弹确认("清空段缓存", "将删除当前格式版本的全部段缓存产物（.pt），"
            + "下次生成所有段都会重新采样（不可撤销，仅影响本机磁盘缓存，不碰旧版本目录与其它文件）。继续？");
        if (!ok) return;
        清理钮.disabled = true;
        try {
            const res = await fetch(清理接口, { method: "POST" });
            const 数据 = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(数据?.error || `HTTP ${res.status}`);
            toast(`已清空段缓存：删除 ${数据.删除数 | 0} 项，释放 ${人类字节(数据.释放字节)}`);
        } catch (e) {
            toast(`清空段缓存失败：${e.message || e}`, "error");
        } finally {
            清理钮.disabled = false;
            await 刷新();
        }
    }

    function 同步失效版本() {
        const n = 取节点();
        失输.value = String(n ? 真源.读缓存失效版本(n) : 0);
    }

    function 写失效版本(v) {
        const n = 取节点();
        if (!n) { toast("请先绑定长视频规划师节点", "error"); 同步失效版本(); return; }
        真源.写缓存失效版本(n, v);
        同步失效版本();   // 回显归一后的整数值
    }

    刷新钮.onclick = () => 刷新();
    清理钮.onclick = () => 清理().catch(() => {});   // 弹确认 reject 视同取消，不留 unhandled rejection
    // 提交式写入（onchange：失焦/Enter/步进器）：敲键过程不写不回显，避免回显抢光标、
    // 清空重输时 Number("")→0 误写、每键 toast/标脏（中间态进 undo 栈）三类副作用。
    失输.onchange = () => 写失效版本(失输.value);
    加一钮.onclick = () => {
        const n = 取节点();
        写失效版本((n ? 真源.读缓存失效版本(n) : 0) + 1);
    };

    return { 刷新, 清理, 同步失效版本 };
}
