// 规划导入与配置页数据管理共用列表；只读取本机存档，不调用 AI。
import { app } from "../../../scripts/app.js";

async function 请求(url, body) {
    const r = await fetch(url, body === undefined ? { cache: "no-store" } : {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || "数据操作失败");
    return data;
}
const 确认 = (title, message) => app.extensionManager.dialog.confirm({ title, message });
let 列表序 = 0;
function 建(tag, text, parent) {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    parent?.appendChild(el); return el;
}
function 按钮(text, parent, fn) {
    const b = 建("button", text, parent); b.type = "button"; b.className = "lvp-data-btn";
    b.onclick = fn; return b;
}
function 样式() {
    if (document.getElementById("lvp-data-style")) return;
    const s = 建("style"); s.id = "lvp-data-style";
    s.textContent = `
      .lvp-data{display:flex;flex-direction:column;gap:10px;min-width:0;color:var(--p-text-color,#ddd)}
      .lvp-data-list{display:flex;flex-direction:column;gap:6px;max-height:340px;overflow:auto}
      .lvp-data-row{display:flex;align-items:center;gap:10px;border:1px solid var(--p-content-border-color,#444);border-radius:6px;padding:8px}
      .lvp-data-info{flex:1;min-width:0;overflow-wrap:anywhere}.lvp-data-info small{display:block;opacity:.7;margin-top:4px}
      .lvp-data-row select{max-width:45%;min-width:0;background:var(--comfy-input-bg,#222);color:inherit;border:1px solid var(--p-content-border-color,#444);border-radius:5px;padding:5px}
      .lvp-data-actions{display:flex;gap:8px;flex-wrap:wrap}.lvp-data-btn{border:1px solid var(--p-content-border-color,#444);border-radius:6px;padding:6px 10px;background:var(--comfy-input-bg,#222);color:inherit;cursor:pointer;white-space:nowrap}
      .lvp-data-btn:disabled{opacity:.45;cursor:default}.lvp-data-note{font-size:12px;line-height:1.6;overflow-wrap:anywhere}.lvp-data-error{color:var(--p-red-400,#ff7875)}
      .lvp-data-dialog{width:min(760px,90vw);max-height:85vh;overflow:auto;background:var(--comfy-menu-bg,#222);color:var(--p-text-color,#ddd);border:1px solid var(--p-content-border-color,#444);border-radius:12px;padding:20px;box-sizing:border-box}
      .lvp-data-dialog::backdrop{background:#0008}.lvp-data-dialog h3{margin:0 0 12px}.lvp-data-dialog .lvp-data-actions{justify-content:flex-end}
      .lvp-data-section{display:flex;flex-direction:column;gap:10px;border-top:1px solid var(--p-content-border-color,#444);padding-top:12px}
      #lvp-api-model-panel .lvp-data-settings.lvp-card{gap:8px;container-type:inline-size}
      .lvp-data-settings h3,.lvp-data-settings p{margin:0}
      .lvp-data-settings h3{font-size:13px;line-height:1.5}
      .lvp-data-settings .lvp-data-note{font-size:11px;line-height:1.5}
      .lvp-data-settings .lvp-data-columns{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;min-width:0}
      .lvp-data-settings .lvp-data-section{min-width:0;gap:7px;padding-top:8px}
      .lvp-data-settings .lvp-data-video{grid-column:1/-1}
      .lvp-data-settings .lvp-data-section>strong{font-size:12px}
      .lvp-data-settings .lvp-data{gap:6px}
      .lvp-data-settings .lvp-data-list{gap:5px;max-height:180px;overflow:auto;min-width:0}
      .lvp-data-settings .lvp-data-list>p{font-size:12px;color:var(--p-text-muted-color,#9aa0a8);padding:6px 0}
      .lvp-data-settings .lvp-data-row{min-width:0;gap:7px;padding:5px 6px}
      .lvp-data-settings .lvp-data-row>input{margin:0;flex:0 0 auto;accent-color:var(--p-primary-color,#3b82f6)}
      .lvp-data-settings .lvp-data-info strong{display:block;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;font-size:12px}
      .lvp-data-settings .lvp-data-info small{font-size:10px;line-height:1.4;margin-top:2px}
      .lvp-data-settings .lvp-data-actions{gap:6px}
      .lvp-data-settings .lvp-data-btn{padding:4px 8px;font-size:12px;min-height:28px;flex:0 0 auto}
      .lvp-data-settings .lvp-data-btn:focus-visible{outline:2px solid var(--p-primary-color,#3b82f6);outline-offset:2px}
      @container(max-width:660px){.lvp-data-settings .lvp-data-columns{grid-template-columns:minmax(0,1fr);gap:10px}}
    `;
    document.head.appendChild(s);
}

async function 另存为(kind, item) {
    const data = await 请求(`/lvp/data/export?type=${encodeURIComponent(kind)}&id=${encodeURIComponent(item.id)}`);
    const text = JSON.stringify(data, null, 2);
    const filename = (item.名称 || kind).replace(/[\\/:*?"<>|\x00-\x1f]/g, "_").slice(0, 80) + ".json";
    if (globalThis.showSaveFilePicker) {
        let handle;
        try { handle = await globalThis.showSaveFilePicker({ suggestedName: filename, types: [{ description: "规划 / 计划数据", accept: { "application/json": [".json"] } }] }); }
        catch (e) { if (e.name === "AbortError") return; if (!["SecurityError", "NotAllowedError", "TypeError"].includes(e.name)) throw e; }
        if (handle) { const stream = await handle.createWritable(); await stream.write(text); await stream.close(); return; }
    }
    const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
    const a = 建("a"); a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function 创建列表(parent, kind, { 单选 = false, 改选择 = () => {}, 允许文件导入 = true, 允许另存 = true,
    读取列表 = () => 请求("/lvp/data/list"), 自动刷新 = true } = {}) {
    const box = 建("div", undefined, parent); box.className = "lvp-data";
    const 单选组 = "lvp-history-" + ++列表序;
    const actions = 建("div", undefined, box); actions.className = "lvp-data-actions";
    const message = 建("p", "", box); message.className = "lvp-data-note"; message.setAttribute("role", "status");
    const list = 建("div", undefined, box); list.className = "lvp-data-list";
    const selected = new Set(), 分集选择 = new Map(); let data = null, signature = "", loading = false, closed = false, 操作中 = false;
    function 错误(e) { if (e?.name !== "AbortError") { message.textContent = e.message || String(e); message.classList.add("lvp-data-error"); } }
    async function refresh() {
        if (loading || closed || 操作中) return;
        loading = true;
        try {
            data = await 读取列表();
            if (closed) return;
            const entries = data[kind] || [];
            const valid = new Set(entries.filter(e => 单选 ? e.可导入 : !e.运行中).map(e => e.id));
            for (const id of selected) if (!valid.has(id)) selected.delete(id);
            改选择([...selected][0]);
            const next = JSON.stringify(entries);
            if (next !== signature) {
                signature = next; list.replaceChildren();
                if (!entries.length) 建("p", `暂无历史${kind}内容`, list);
                for (const item of entries) {
                    const row = 建("label", undefined, list); row.className = "lvp-data-row";
                    const check = 建("input", undefined, row); check.type = 单选 ? "radio" : "checkbox";
                    check.name = 单选组; check.checked = selected.has(item.id);
                    check.disabled = 单选 ? !item.可导入 : item.运行中;
                    check.onchange = () => {
                        if (单选) selected.clear();
                        if (check.checked) selected.add(item.id); else selected.delete(item.id);
                        改选择([...selected][0]);
                    };
                    const info = 建("span", undefined, row); info.className = "lvp-data-info";
                    const name = 建("strong", item.名称, info); name.title = item.名称;
                    const date = new Date(item.更新时间 * 1000).toLocaleString();
                    const size = kind === "视频片段" ? `${(item.大小 / 1024 ** 2).toFixed(1)} MB` : `${Math.ceil(item.大小 / 1024)} KB`;
                    const videoInfo = `${item.片段数 ? `${item.片段数} 个片段` : "1 个视频"} · ${size}`;
                    建("small", [date, kind === "规划" ? `${item.集数} 集 · ${item.状态}` : kind === "视频片段" ? videoInfo : size, item.运行中 ? "运行中 / 待恢复，不能清理" : ""].filter(Boolean).join(" · "), info);
                    if (kind === "视频片段") info.title = item.文件名;
                    if (单选 && kind === "规划" && item.分集?.length > 1) {
                        const episodes = 建("select", undefined, row); episodes.setAttribute("aria-label", `${item.名称}载入分集`);
                        for (const ep of item.分集) {
                            const op = 建("option", `第${ep.集号}集 · ${ep.名称} · ${ep.镜头数}镜头`, episodes); op.value = String(ep.集号);
                        }
                        const number = 分集选择.get(item.id);
                        episodes.value = String(item.分集.find(ep => ep.集号 === number)?.集号 ?? item.分集[0].集号);
                        分集选择.set(item.id, Number(episodes.value));
                        episodes.disabled = !item.可导入;
                        episodes.onchange = () => {
                            分集选择.set(item.id, Number(episodes.value)); selected.clear(); selected.add(item.id);
                            for (const input of list.querySelectorAll('input[type="radio"]')) input.checked = input === check;
                            改选择(item.id);
                        };
                    }
                    if (!单选 && 允许另存) {
                        const save = 按钮("另存为", row, async e => {
                            e?.preventDefault?.(); e?.stopPropagation?.(); save.disabled = true;
                            try { await 另存为(kind, item); } catch (e) { 错误(e); } finally { save.disabled = false; }
                        });
                    }
                }
            }
            const errors = (data.导入错误 || []).map(e => `${e.文件}：${e.说明}`);
            message.textContent = errors.length && !单选 ? errors.join("；") : `历史${kind} ${entries.length} ${kind === "视频片段" ? "组" : "条"}`;
            message.classList.toggle("lvp-data-error", !!errors.length && !单选);
        } catch (e) { 错误(e); } finally { loading = false; }
    }
    if (!单选) 按钮("刷新", actions, refresh);
    if (允许文件导入) 按钮("导入" + kind, actions, async () => {
        try {
            const result = await 请求("/lvp/data/folder", { 类型: kind });
            message.textContent = `请把${kind} JSON 数据文件拖入：${result.目录}。导入后与本地保存内容共用列表，源数据包保存在“已导入”子文件夹。`;
            await 打开文件导入(kind, result.目录);
            await refresh();
        } catch (e) { 错误(e); }
    });
    if (!单选) 按钮("清理选中", actions, async () => {
        if (操作中 || !selected.size) return;
        const ids = [...selected]; 操作中 = true;
        try {
            const video = kind === "视频片段";
            if (!await 确认(`清理历史${kind}`, video
                ? `已选择 ${ids.length} 组视频片段，将删除对应的视频文件和片段记录以释放空间。引用这些视频的工程将无法继续使用它们，请确认已完成制作或备份视频。`
                : `已选择 ${ids.length} 条${kind}。删除后不能再读取这些记录；请确认多集内容已全部制作完成，并已另存为备份。`)) return;
            const result = await 请求("/lvp/data/delete/prepare", { 类型: kind, ids });
            if (!await 确认("再次确认清理", video
                ? `将永久删除 ${result.数量} 个视频文件及其全部片段记录，无法撤销。是否确认清理？`
                : `将永久清理 ${result.数量} 条${kind}及其存档。是否确认清理？`)) return;
            await 请求("/lvp/data/delete/confirm", { 确认凭据: result.确认凭据 });
            selected.clear(); signature = "";
            window.dispatchEvent(new CustomEvent("lvp-数据已变化"));
        } catch (e) { 错误(e); } finally { 操作中 = false; await refresh(); }
    });
    const timer = 自动刷新 ? setInterval(() => {
        if (!box.isConnected) { closed = true; clearInterval(timer); return; }
        if (!document.hidden) refresh();
    }, 3000) : null;
    refresh();
    return { refresh, 关闭: () => { closed = true; clearInterval(timer); }, 选中: () => [...selected][0], 集号: () => 分集选择.get([...selected][0]), 错误 };
}

async function 打开文件导入(kind, directory) {
    const d = 建("dialog"); d.className = "lvp-data-dialog"; document.body.appendChild(d);
    建("h3", "导入" + kind, d);
    const tip = 建("p", `把 JSON 数据文件拖入已打开的文件夹：${directory}`, d); tip.className = "lvp-data-note";
    const list = 创建列表(d, kind, { 单选: true, 允许文件导入: false });
    const footer = 建("div", undefined, d); footer.className = "lvp-data-actions";
    按钮("完成", footer, () => d.close());
    // 文件夹已打开，这个弹窗只负责实时观察导入结果。
    return await new Promise(resolve => { d.addEventListener("close", () => { list.关闭(); d.remove(); window.dispatchEvent(new CustomEvent("lvp-数据已变化")); resolve(); }, { once: true }); d.showModal(); });
}

export async function 打开规划导入() {
    样式();
    const d = 建("dialog"); d.className = "lvp-data-dialog"; document.body.appendChild(d);
    建("h3", "载入规划", d);
    const list = 创建列表(d, "规划", { 单选: true, 允许文件导入: false, 改选择: id => { if (accept) accept.disabled = !id; } });
    const footer = 建("div", undefined, d); footer.className = "lvp-data-actions";
    let value = null, busy = false;
    按钮("取消", footer, () => { if (!busy) d.close(); });
    const accept = 按钮("确认载入", footer, async () => {
        const id = list.选中(); if (!id || busy) return;
        busy = true; accept.disabled = true;
        try { value = await 请求(`/lvp/data/planning/load?id=${encodeURIComponent(id)}${list.集号() ? `&episode=${list.集号()}` : ""}`); d.close(); }
        catch (e) { list.错误(e); } finally { busy = false; accept.disabled = !list.选中(); }
    }); accept.disabled = true;
    d.addEventListener("cancel", e => { if (busy) e.preventDefault(); });
    return await new Promise(resolve => { d.addEventListener("close", () => { list.关闭(); d.remove(); resolve(value); }, { once: true }); d.showModal(); });
}

export function 创建数据管理({ el }) {
    样式();
    const root = el("div", { class: "lvp-card lvp-data lvp-data-settings" });
    建("h3", "数据管理", root);
    const tip = 建("p", "历史数据不会自动清理；清理需两次确认。另存为 JSON 可分享，图片、视频、音频需另行同步。", root); tip.className = "lvp-data-note";
    const columns = 建("div", undefined, root); columns.className = "lvp-data-columns";
    let 在途 = null;
    const 读取列表 = () => {
        if (!在途) 在途 = 请求("/lvp/data/list").finally(() => { 在途 = null; });
        return 在途;
    };
    const 列表 = [];
    for (const kind of ["规划", "计划", "视频片段"]) {
        const video = kind === "视频片段";
        const section = 建("section", undefined, columns); section.className = "lvp-data-section" + (video ? " lvp-data-video" : "");
        建("strong", "历史" + kind, section);
        if (video) { const note = 建("p", "按生成视频分组，清理会删除视频文件及其全部片段记录，释放磁盘空间。", section); note.className = "lvp-data-note"; }
        列表.push(创建列表(section, kind, { 读取列表, 自动刷新: false, 允许文件导入: !video, 允许另存: !video }));
    }
    const timer = setInterval(() => {
        if (!root.isConnected) { 列表.forEach(list => list.关闭()); clearInterval(timer); return; }
        if (!document.hidden) 列表.forEach(list => list.refresh());
    }, 3000);
    return { 根: root };
}
