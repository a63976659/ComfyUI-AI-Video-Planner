import { 真源, 捕获节点快照, 提交节点快照 } from "./桥接/节点桥.js";
import { 打开媒体预览 } from "./媒体预览.js";
import { 设置节点忙碌, 刷新节点重置状态 } from "./节点重置.js";
import { 规范制作, 新制作ID, 取制作时长, 取制作镜头时段, 镜头参与制作, 解析SRT, 生成SRT, 取后期字幕, 制作产物URL } from "./制作数据.js";

let 样式已注入 = false;
function 注入样式() {
    if (样式已注入) return;
    const style = document.createElement("style");
    style.textContent = `
    .lvp-制作根{display:grid;grid-template-columns:190px minmax(280px,1fr) 350px;gap:8px;width:100%;min-width:840px;min-height:0;font:11px/1.4 system-ui;color:var(--fg-color,#ddd)}
    .lvp-制作列{min-width:0;overflow:auto;background:var(--comfy-menu-bg,#2b2b2b);padding:7px;border-radius:6px;box-sizing:border-box}
    .lvp-制作中{display:flex;flex-direction:column;gap:6px}
    .lvp-制作根 h3{font-size:12px;margin:0 0 5px;font-weight:600}.lvp-制作根 details{margin:0 0 8px;border-bottom:1px solid var(--border-color,#444);padding-bottom:6px}
    .lvp-制作根 summary{cursor:pointer;font-weight:600;padding:2px 0 5px}.lvp-制作根 details[open]>summary{color:var(--p-primary-color,#4a9eff)}
    .lvp-制作行{display:flex;align-items:center;gap:5px;margin:3px 0;min-width:0;flex-wrap:wrap}.lvp-制作行>label{flex:0 0 76px;color:var(--fg-color,#ddd)}
    .lvp-制作行>input:not([type=checkbox]),.lvp-制作行>select,.lvp-制作行>textarea{flex:1;min-width:65px;width:0;box-sizing:border-box;border:1px solid var(--border-color,#444);border-radius:4px;padding:3px 5px;background:var(--comfy-input-bg,#222);color:var(--fg-color,#ddd);font:11px system-ui}
    .lvp-制作行>textarea{min-height:42px;resize:vertical}.lvp-制作行 input[type=checkbox]{accent-color:var(--p-primary-color,#4a9eff)}
    .lvp-制作根 button,.lvp-制作根 a{font:11px system-ui}.lvp-制作根 button{cursor:pointer;min-height:22px;border:1px solid var(--border-color,#444);border-radius:4px;padding:3px 7px;background:var(--comfy-input-bg,#333);color:var(--fg-color,#ddd)}
    .lvp-制作根 button:hover{border-color:var(--p-primary-color,#4a9eff)}.lvp-制作根 button:focus-visible,.lvp-制作根 input:focus-visible,.lvp-制作根 select:focus-visible,.lvp-制作根 textarea:focus-visible{outline:2px solid var(--p-primary-color,#4a9eff);outline-offset:1px}
    .lvp-制作根 button:disabled{opacity:.45;cursor:default}.lvp-制作根 .lvp-制作主钮{background:var(--p-primary-color,#4a9eff);color:var(--p-primary-contrast-color,#fff);border-color:var(--p-primary-color,#4a9eff)}
    .lvp-制作工具{display:flex;gap:4px;flex-wrap:wrap;align-items:center}.lvp-制作工具 a{color:var(--p-primary-color,#4a9eff);padding:3px}
    .lvp-制作说明{font-size:10px;color:var(--p-text-muted-color,#aaa);white-space:pre-wrap;overflow-wrap:anywhere;margin:4px 0}.lvp-制作错误{color:var(--error-text-color,#ff9090)}
    .lvp-制作镜头{display:flex;gap:4px;padding:4px 0;border-bottom:1px solid var(--border-color,#444);align-items:center}.lvp-制作镜头>button:first-child{flex:1;text-align:left;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .lvp-制作镜头.选中>button:first-child{border-color:var(--p-primary-color,#4a9eff);color:var(--p-primary-color,#4a9eff)}
    .lvp-制作列表{max-height:110px;overflow:auto}.lvp-制作播放器{width:100%;max-height:115px;min-height:70px;object-fit:contain;background:var(--comfy-input-bg,#161616)}
    .lvp-制作结果{display:flex;flex-direction:column;gap:3px}.lvp-制作状态{white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px;min-height:16px}
    .lvp-制作卡{margin:5px 0;padding:6px;border:1px solid var(--border-color,#444);border-radius:4px}.lvp-制作卡>header{display:flex;align-items:center;justify-content:space-between;font-weight:600;gap:6px}
    .lvp-制作根 progress{width:100%;height:5px;accent-color:var(--p-primary-color,#4a9eff)}.lvp-制作报告{max-height:100px;overflow:auto}.lvp-制作报告 button{display:block;width:100%;text-align:left;margin:3px 0;white-space:normal}
    .lvp-制作绑定{display:flex;gap:6px;flex-wrap:wrap}.lvp-制作绑定 label{display:flex;gap:3px;align-items:center;cursor:pointer}
    @media(max-width:950px){.lvp-制作根{grid-template-columns:175px 290px 330px;min-width:811px}}
    @media(prefers-reduced-motion:no-preference){.lvp-制作根 button{transition:border-color .12s,opacity .12s}}
    `;
    document.head.appendChild(style); 样式已注入 = true;
}
function 元素(tag, cls = "", text = "") {
    const el = document.createElement(tag); if (cls) el.className = cls; if (text) el.textContent = text; return el;
}
const 终态 = new Set(["completed", "failed", "cancelled", "stopped", "interrupted", "完成", "失败", "已停止"]);
const 成功 = status => status === "completed" || status === "完成";
const 媒体类型 = name => /\.(png|jpg|jpeg|webp|bmp|gif)$/i.test(name) ? "图像" : /\.(mp4|mov|webm|mkv|avi)$/i.test(name) ? "视频" : /\.(wav|mp3|flac|m4a|ogg|aac|opus)$/i.test(name) ? "音频" : "文本";
const 展示文件 = name => String(name || "").split(/[\\/]/).at(-1);

export function 创建视频制作页面板(容器, { 取节点, 弹确认, 全刷 }) {
    注入样式();
    const 根 = 元素("div", "lvp-制作根"), 左 = 元素("aside", "lvp-制作列"), 中 = 元素("section", "lvp-制作列 lvp-制作中"), 右 = 元素("aside", "lvp-制作列");
    根.append(左, 中, 右); 容器.appendChild(根);
    let 当前 = null, 段ID = "", 元数据 = {}, 会话 = 0, 激活 = false, 轮询计时 = null, 轮询中 = false, 控制器 = null, 任务 = null, 任务态 = null;
    let 状态文字 = "请绑定长视频规划师节点", 错误 = false, 结果 = null, 报告 = null, 结果任务 = null, 创建中 = false;
    const 开展分区 = new Map();
    const 按钮 = (父, 文, fn, 禁 = false, 主 = false) => {
        const b = 元素("button", 主 ? "lvp-制作主钮" : "", 文); b.type = "button"; b.disabled = 禁;
        b.onclick = () => { const seq = 会话, node = 当前; Promise.resolve().then(() => { if (seq === 会话 && node === 当前) return fn(); }).catch(e => { if (seq === 会话) 显示错误(e); }); }; 父.appendChild(b); return b;
    };
    function 提示(文, 有错 = false) { 状态文字 = String(文); 错误 = 有错; 刷执行区(); 刷新节点重置状态(当前); }
    function 显示错误(e) { if (e?.name === "AbortError") return; 提示(e?.message || String(e), true); }
    function 存活(seq = 会话, node = 当前) { return seq === 会话 && node === 当前 && node && 取节点() === node; }
    const 读草 = () => { const d = 当前 ? 真源.读剪辑草稿(当前) : { brief: {}, segments: [] }; return { ...d, 制作: 规范制作(d.制作) }; };
    function 取提交草稿() { const 草 = 读草(); return { ...草, 制作: 规范制作(草.制作) }; }
    function 写制作(改, 重画 = true) {
        if (!存活()) return false;
        const 草 = 读草(), p = 规范制作(草.制作); 改(p, 草);
        真源.写剪辑草稿(当前, { ...草, 制作: p });
        if (重画) 渲染();
        return true;
    }
    function 提交(快照, 改) {
        const ok = 提交节点快照(快照, 取节点(), node => {
            const 草 = 真源.读剪辑草稿(node), p = 规范制作(草.制作); 改(p, 草);
            真源.写剪辑草稿(node, { ...草, 制作: p });
        });
        if (!ok) throw new Error("节点或草稿已变化，本次结果未覆盖草稿，请重试。");
        渲染(); return true;
    }
    async function 请求(path, data, options = {}) {
        const resp = await fetch("/lvp/production/" + path, { ...options, ...(data === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json", ...options.headers }, body: JSON.stringify(data) }) });
        const json = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(json.error || json.错误 || `请求失败（${resp.status}）`);
        return json;
    }
    function 分区(父, 名, 默认展开 = false) {
        const key = 名.replace(/ · \d+$/, "");
        const d = 元素("details"), summary = 元素("summary", "", 名); d.open = 开展分区.get(key) ?? 默认展开;
        d.ontoggle = () => 开展分区.set(key, d.open); d.appendChild(summary); 父.appendChild(d); return d;
    }
    function 字段(父, 名, 值, 改, 类型 = "text", 选项 = null, 限制 = {}) {
        const row = 元素("div", "lvp-制作行"), label = 元素("label", "", 名), input = 元素(选项 ? "select" : 类型 === "textarea" ? "textarea" : "input");
        const id = 新制作ID("field"); input.id = id; label.htmlFor = id;
        if (选项) for (const 项 of 选项) { const val = typeof 项 === "string" ? 项 : 项.value, text = typeof 项 === "string" ? 项 : 项.label; const o = 元素("option", "", text); o.value = val; input.appendChild(o); }
        else if (类型 !== "textarea") input.type = 类型;
        Object.assign(input, 限制);
        if (类型 === "checkbox") input.checked = !!值; else input.value = 值 ?? "";
        input.onchange = () => {
            if (input.checkValidity && !input.checkValidity()) { input.reportValidity?.(); return; }
            const value = 类型 === "checkbox" ? input.checked : 类型 === "number" ? Number(input.value) : input.value;
            if (类型 === "number" && !Number.isFinite(value)) return;
            try { 改(value); } catch (e) { 显示错误(e); }
        };
        row.append(label, input); 父.appendChild(row); return input;
    }
    const 数字 = (父, 名, v, 改, min = 0, max = undefined, step = 0.1) => 字段(父, 名, v, 改, "number", null, { min, ...(max === undefined ? {} : { max }), step });
    const 说明 = (父, 文, 错 = false) => { const el = 元素("p", "lvp-制作说明" + (错 ? " lvp-制作错误" : ""), 文); 父.appendChild(el); return el; };
    function 文件选择(父, 名, 值, 型, 改) {
        const 清单 = new Map();
        for (const m of [...(元数据.media || []).map(x => ({ 名: x.name || x.名, 类型: x.type || x.类型 || 媒体类型(x.name || x.名) })), ...(读草().素材 || [])]) {
            if (m.名 && (!型 || 型.includes(m.类型))) 清单.set(m.名, m);
        }
        if (值 && !清单.has(值)) 清单.set(值, { 名: 值, 类型: "" });
        const opts = [{ value: "", label: "请选择素材" }, ...[...清单].map(([名]) => ({ value: 名, label: 展示文件(名) }))];
        const input = 字段(父, 名, 值, 改, "text", opts); input.title = 值 || "上传素材后选择"; return input;
    }
    function 选文件(accept, 回调, 多选 = false) {
        const seq = 会话, node = 当前, 快照 = 捕获节点快照(node), input = 元素("input");
        input.type = "file"; input.accept = accept; input.multiple = 多选;
        input.onchange = () => {
            if (!存活(seq, node)) return;
            Promise.resolve(回调(多选 ? [...input.files] : input.files[0], 快照, seq, node)).catch(e => { if (存活(seq, node)) 显示错误(e); });
        };
        input.click();
    }
    async function 拉元数据() {
        const seq = 会话, node = 当前;
        try { const data = await 请求("meta"); if (!存活(seq, node)) return; 元数据 = data; 渲染(); }
        catch (e) { if (存活(seq, node)) 显示错误(e); }
    }
    async function 上传(files, 快照, seq, node) {
        if (!files?.length) return;
        提示(`上传 ${files.length} 个素材…`);
        const 已上传 = [], 失败 = [];
        for (const file of files) {
            const fd = new FormData(); fd.append("file", file);
            try {
                const r = await fetch("/lvp/media/upload", { method: "POST", body: fd }), j = await r.json().catch(() => ({}));
                if (!r.ok || !j.name) throw new Error(j.error || "上传失败");
                已上传.push({ 名: j.name, 类型: 媒体类型(j.name) });
            } catch (e) { 失败.push(`${file.name}：${e.message}`); }
            if (!存活(seq, node)) return;
        }
        if (已上传.length) 提交(快照, (_p, 草) => { const map = new Map((草.素材 || []).map(m => [m.名, m])); for (const m of 已上传) map.set(m.名, m); 草.素材 = [...map.values()]; });
        提示(失败.length ? `${已上传.length} 个上传成功；${失败.join("；")}` : `已上传 ${已上传.length} 个素材`, !!失败.length);
        await 拉元数据();
    }
    function 渲染左() {
        左.textContent = "";
        左.appendChild(元素("h3", "", "视频制作 · 后期"));
        const tools = 元素("div", "lvp-制作工具"); 左.appendChild(tools);
        按钮(tools, "刷新", 拉元数据, !当前);
        按钮(tools, "备份工程", 导出工程, !当前);
        按钮(tools, "恢复备份", () => 选文件(".zip", 导入工程), !当前);
        const p = 规范制作(读草().制作);
        const 镜 = 分区(左, `视频片段 · ${p.片段.length}`, true);
        const list = 元素("div", "lvp-制作列表"); 镜.appendChild(list);
        p.片段.forEach((s, i) => {
            const row = 元素("div", "lvp-制作镜头" + (段ID === s.id ? " 选中" : ""));
            const b = 按钮(row, `${i + 1}. ${s.名称 || "生成片段"} · ${Number(s.时长).toFixed(1)}s${镜头参与制作(s) ? "" : " · 不参与"}`, () => { 段ID = s.id; 渲染(); });
            b.setAttribute("aria-pressed", String(段ID === s.id)); b.title = s.文件名 || ""; list.appendChild(row);
        });
        if (!p.片段.length) 说明(镜, "运行当前工作流后，最终视频会自动加入。已有配音、台词和字幕会跟随对应片段。");
        else 说明(镜, "仅调整生成结果，不影响原来的生成规划。");
        const 画 = 分区(左, "成片画布", false);
        for (const [key, 名, min, max, step] of [["宽", "宽度", 64, 7680, 2], ["高", "高度", 64, 7680, 2], ["帧率", "帧率", 1, 120, .01]]) 数字(画, 名, p.画布[key], v => 写制作(x => { x.画布[key] = v; x.画布手动 = true; }), min, max, step);
        说明(画, p.画布手动 ? "使用手动画布；后续视频不会改变它。" : p.画布已初始化 ? "画布来自首次导入的视频；后续视频按此画布适配。" : "首次导入自动设置画布，也可提前手动设置。");
        const 后 = 分区(左, "画面与声音优化", false);
        for (const [key, min, max] of [["亮度", -1, 1], ["对比度", .1, 3], ["饱和度", 0, 3]]) 数字(后, key, p.后处理[key], v => 写制作(x => x.后处理[key] = v), min, max, .05);
        for (const key of ["去闪烁", "防抖", "插帧", "响度标准化", "音乐压低"]) 字段(后, key, p.后处理[key], v => 写制作(x => x.后处理[key] = v), "checkbox");
        说明(后, "优化会用于预览和成片；先预览确认效果。");
    }
    function 渲染右() {
        右.textContent = ""; const p = 规范制作(读草().制作), s = p.片段.find(x => x.id === 段ID);
        const 选 = 分区(右, "当前片段", true);
        if (!s) 说明(选, "等待当前工作流输出视频，然后选择片段进行后期调整。");
        else {
            const 改 = (k, v) => 写制作(x => { const clip = x.片段.find(a => a.id === 段ID); if (clip) clip[k] = v; });
            字段(选, "片段名称", s.名称, v => 改("名称", v));
            说明(选, 展示文件(s.文件名));
            字段(选, "参与制作", 镜头参与制作(s), v => 改("启用", v), "checkbox");
            const row = 元素("div", "lvp-制作工具"); 选.appendChild(row);
            const i = p.片段.findIndex(x => x.id === 段ID);
            for (const [名, dir] of [["前移", -1], ["后移", 1]]) 按钮(row, 名, () => 写制作(x => { const at = x.片段.findIndex(a => a.id === 段ID), to = at + dir; if (to >= 0 && to < x.片段.length) [x.片段[at], x.片段[to]] = [x.片段[to], x.片段[at]]; }), i + dir < 0 || i + dir >= p.片段.length);
            按钮(row, "查看源视频", () => 打开媒体预览({ 名: s.文件名, 类型: "视频" }));
            const 源末 = Number(s.源结束 ?? s.素材时长), 源起 = Number(s.源开始 || 0);
            数字(选, "裁切起点(秒)", s.起点, v => { if (v < 源起 || v + Number(s.时长) > 源末 + .001) throw new Error("裁切范围超出原片段，请先缩短时长。"); 改("起点", v); }, 源起, 源末, .01);
            数字(选, "保留时长(秒)", s.时长, v => { if (v + Number(s.起点) > 源末 + .001) throw new Error("保留范围超出原片段。"); 改("时长", v); }, .01, Math.max(.01, 源末 - Number(s.起点)), .01);
            说明(选, "起点是源视频位置；裁切、排序和停用片段时，绑定配音与字幕一起调整。");
            字段(选, "画面适配", s.适配 || "完整显示", v => 改("适配", v), "text", ["完整显示", "填满裁切"]);
            字段(选, "片段声音", s.声音, v => 改("声音", v), "text", s.配音?.文件名 ? ["配音", "原声", "静音"] : ["原声", "静音"]);
            数字(选, "音量", s.音量 ?? 1, v => 改("音量", v), 0, 4, .05);
            if (s.配音?.文件名) { 说明(选, "已绑定配音：" + 展示文件(s.配音.文件名)); 按钮(选, "试听配音", () => 打开媒体预览({ 名: s.配音.文件名, 类型: "音频" })); }
            字段(选, "转场", s.转场, v => 改("转场", v), "text", ["硬切", "淡入淡出"]);
            字段(选, "原配音台词", s.台词, () => {}, "textarea", null, { readOnly: true });
            说明(选, "这里记录已生成的配音内容；显示文字在下方字幕中修改，修改字幕不会改变声音。");
            const 字幕 = 分区(选, `本段字幕 · ${(s.字幕 || []).length}`, false);
            说明(字幕, "时间相对原导入片段；裁掉的范围不会显示。");
            按钮(字幕, "添加本段字幕", () => 改("字幕", [...(s.字幕 || []), { 开始: Math.max(0, s.起点 - s.源开始), 结束: Math.max(0, s.起点 - s.源开始) + s.时长, 文本: "" }]));
            (s.字幕 || []).forEach((sub, n) => {
                const card = 元素("div", "lvp-制作卡"); 字幕.appendChild(card);
                const 写字 = (k, v) => 写制作(x => x.片段.find(a => a.id === 段ID).字幕[n][k] = v);
                for (const key of ["开始", "结束"]) 数字(card, "本段" + key, sub[key], v => 写字(key, v), 0, undefined, .01);
                字段(card, "本段字幕文本", sub.文本, v => 写字("文本", v), "textarea");
                按钮(card, "删除字幕", () => 写制作(x => x.片段.find(a => a.id === 段ID).字幕.splice(n, 1)));
            });
            按钮(选, "删除片段", async () => { const id = 段ID; if (await 弹确认("删除后期片段", "仅从成片中移除此片段，原视频和生成规划保留。")) 写制作(x => x.片段 = x.片段.filter(a => a.id !== id)); });
        }
        渲染音轨(p); 渲染字幕(p, 读草()); 渲染文字(p);
    }
    function 渲染音轨(p) {
        const section = 分区(右, `背景音乐与音效 · ${p.音轨.length}`, false);
        按钮(section, "上传音乐或音效", () => 选文件("audio/*", 上传, true), !当前);
        按钮(section, "添加音乐或音效", () => 写制作(x => x.音轨.push({ id: 新制作ID("track"), 类型: "音乐", 文件名: "", 开始: 0, 起点: 0, 时长: 取制作时长(读草()), 音量: 1, 循环: false, 淡入: 0, 淡出: 0 })), !当前);
        p.音轨.forEach((track, i) => {
            const card = 元素("div", "lvp-制作卡"), head = 元素("header", "", `${track.类型} · ${展示文件(track.文件名) || "选择音频"}`); card.appendChild(head); section.appendChild(card);
            const 改 = (k, v) => 写制作(x => x.音轨[i][k] = v);
            按钮(head, "删除", () => 写制作(x => x.音轨.splice(i, 1)));
            字段(card, "轨道类型", track.类型, v => 改("类型", v), "text", ["音乐", "音效"]);
            文件选择(card, "声音文件", track.文件名, ["音频", "视频"], v => 改("文件名", v));
            if (track.文件名) 按钮(card, "试听", () => 打开媒体预览({ 名: track.文件名, 类型: 媒体类型(track.文件名) }));
            for (const key of ["开始", "起点", "时长", "淡入", "淡出"]) 数字(card, key + "(秒)", track[key] ?? 0, v => 改(key, v));
            数字(card, "音量", track.音量 ?? 1, v => 改("音量", v), 0, 4, 0.05);
            字段(card, "循环", track.循环, v => 改("循环", v), "checkbox");
        });
        说明(section, "开始是成片时间；起点是源音频位置。音乐压低与响度统一在左侧后处理设置。");
    }
    function 渲染字幕(p, 草) {
        const section = 分区(右, `字幕样式与额外字幕 · ${取后期字幕(草).length}`, false), 改 = (k, v) => 写制作(x => x.字幕[k] = v);
        说明(section, "对应段字幕已自动导入，在当前片段中修改。这里设置统一样式，或添加按成片时间显示的额外字幕。");
        字段(section, "启用字幕", p.字幕.启用, v => 改("启用", v), "checkbox");
        数字(section, "字号", p.字幕.字号, v => 改("字号", v), 8, 120, 1);
        字段(section, "颜色", p.字幕.颜色, v => 改("颜色", v), "color");
        字段(section, "位置", p.字幕.位置, v => 改("位置", v), "text", ["顶部", "中部", "底部"]);
        const row = 元素("div", "lvp-制作工具"); section.appendChild(row);
        按钮(row, "导入 SRT", () => 选文件(".srt", async (f, snap, seq, node) => { if (!f) return; const 条目 = 解析SRT(await f.text()); if (!存活(seq, node)) return; 提交(snap, x => x.字幕.条目 = 条目); 提示(`已导入 ${条目.length} 条字幕`); }), !当前);
        按钮(row, "下载 SRT", () => 下载文本("字幕.srt", 生成SRT(取后期字幕(草)), "application/x-subrip"), !取后期字幕(草).length);
        按钮(row, "添加字幕", () => 写制作(x => x.字幕.条目.push({ 开始: 0, 结束: 3, 文本: "" })), !当前);
        p.字幕.条目.forEach((sub, i) => {
            const card = 元素("div", "lvp-制作卡"); section.appendChild(card);
            for (const key of ["开始", "结束"]) 数字(card, key, sub[key], v => 写制作(x => x.字幕.条目[i][key] = v));
            字段(card, "字幕文本", sub.文本, v => 写制作(x => x.字幕.条目[i].文本 = v), "textarea");
            按钮(card, "删除", () => 写制作(x => x.字幕.条目.splice(i, 1)));
        });
    }
    function 渲染文字(p) {
        const section = 分区(右, `文字叠加 · ${p.文字.length}`, false);
        按钮(section, "添加文字", () => 写制作(x => { const s = x.片段.find(a => a.id === 段ID), 偏移 = s ? Math.max(0, s.起点 - s.源开始) : 0; x.文字.push({ 片段id: 段ID || "", 开始: 偏移, 结束: 偏移 + Math.min(5, s?.时长 || 5), 文本: "", 位置: "顶部", 字号: 48 }); }), !当前);
        p.文字.forEach((text, i) => {
            const card = 元素("div", "lvp-制作卡"); section.appendChild(card); const 改 = (k, v) => 写制作(x => x.文字[i][k] = v);
            字段(card, "跟随片段", text.片段id || "", v => 改("片段id", v), "text", [{ value: "", label: "成片固定时间" }, ...p.片段.map(a => ({ value: a.id, label: a.名称 }))]);
            说明(card, text.片段id ? "时间相对原导入片段，随此片段裁切和移动。" : "时间相对整条成片。");
            字段(card, "文字内容", text.文本, v => 改("文本", v), "textarea");
            for (const key of ["开始", "结束"]) 数字(card, key, text[key], v => 改(key, v));
            字段(card, "位置", text.位置, v => 改("位置", v), "text", ["顶部", "中部", "底部"]); 数字(card, "字号", text.字号, v => 改("字号", v), 8, 160, 1);
            按钮(card, "删除", () => 写制作(x => x.文字.splice(i, 1)));
        });
    }
    let 执行工具, 进度, 状态行, 播放器, 下载区, 报告区, 历史区, 历史内容;
    function 渲染中() {
        中.textContent = "";
        const title = 元素("h3", "", `成片预览 · ${取制作时长(读草()).toFixed(1)} 秒`); 中.appendChild(title);
        执行工具 = 元素("div", "lvp-制作工具"); 中.appendChild(执行工具);
        状态行 = 元素("div", "lvp-制作状态"); 状态行.setAttribute("role", "status"); 状态行.setAttribute("aria-live", "polite"); 中.appendChild(状态行);
        进度 = 元素("progress"); 进度.max = 1; 中.appendChild(进度);
        const 旧时间 = 播放器?.currentTime || 0, 旧src = 播放器?.getAttribute?.("src"), 正在播 = 播放器 && !播放器.paused;
        播放器?.pause?.();
        播放器 = 元素("video", "lvp-制作播放器"); 播放器.controls = true; 播放器.playsInline = true; 播放器.preload = "metadata"; 中.appendChild(播放器);
        下载区 = 元素("div", "lvp-制作工具"); 中.appendChild(下载区);
        报告区 = 元素("div", "lvp-制作报告"); 中.appendChild(报告区);
        历史区 = 分区(中, "制作历史", false);
        历史内容 = 元素("div"); 历史区.appendChild(历史内容);
        说明(中, "按参与片段的顺序合成；先预览，再导出完整成片。");
        刷历史();
        刷执行区(); 刷结果();
        if (旧src && 播放器.getAttribute?.("src") === 旧src) {
            播放器.onloadedmetadata = () => { 播放器.currentTime = Math.min(旧时间, 播放器.duration || 旧时间); if (正在播 && 激活) 播放器.play?.().catch?.(() => {}); };
        }
    }
    // 任务创建、停止与轮询仅更新历史内容，保留 details 展开态、滚动和播放器实例。
    function 刷历史() {
        if (!历史内容) return;
        const scrollTop = 历史内容.scrollTop;
        历史内容.textContent = "";
        const p = 规范制作(读草().制作), 拥有 = new Map((Array.isArray(p.任务历史) ? p.任务历史 : []).filter(j => j && typeof j.id === "string" && typeof j.token === "string").map(j => [j.id, j]));
        if (p.最近任务?.id && p.最近任务?.token) 拥有.set(p.最近任务.id, p.最近任务);
        // 任务归属由当前工程的凭据决定：清空工程后不再展示其它工程的旧任务。
        const 历史 = new Map((元数据.jobs || []).filter(j => 拥有.has(j.id)).map(j => [j.id, j]));
        for (const job of 拥有.values()) if (!历史.has(job.id)) 历史.set(job.id, job);
        if (任务?.id && 任务态 && 拥有.has(任务.id)) 历史.set(任务.id, { ...历史.get(任务.id), ...任务态, id: 任务.id, 模式: 任务.模式 });
        for (const job of [...历史.values()].reverse()) {
            const row = 元素("div", "lvp-制作工具"); 历史内容.appendChild(row);
            说明(row, `${job.模式 || job.mode || "制作"} · ${job.status || ""} · ${job.id}`);
            const 凭据 = 拥有.get(job.id);
            if (凭据) {
                const b = 按钮(row, "取回此任务", () => { 清轮询(); 任务 = 凭据; 任务态 = null; 结果 = null; 报告 = null; 结果任务 = null; 提示("正在取回历史任务…"); 刷结果(); 开始轮询(); });
                b.title = `取回 ${job.id}，可查看产物或恢复未完成的原工程`;
            }
        }
        说明(历史内容, "最近 20 个任务的访问凭据保存在原工程草稿。仅此工程拥有凭据的任务可取回或恢复；切换节点不会关联其他工程。导出工程包会移除控制凭据。");
        历史内容.scrollTop = scrollTop;
    }
    function 刷执行区() {
        if (!执行工具) return;
        执行工具.textContent = "";
        const 忙 = 创建中 || (任务 && !终态.has(任务态?.status));
        按钮(执行工具, "校验工程", 校验工程, !当前 || 创建中);
        for (const 模式 of ["预览", "成片"]) {
            const b = 按钮(执行工具, 模式 === "成片" ? "导出成片" : 模式, () => 创建任务(模式), !当前 || 忙 || !取制作时长(读草()), 模式 === "成片");
            b.title = 模式 === "预览" ? "合成当前视频、对应配音、字幕和后期设置，供播放检查" : "将参与片段和后期设置导出为完整视频";
        }
        if (任务 && !终态.has(任务态?.status)) 按钮(执行工具, "停止", () => 控制任务("cancel"), !任务.token);
        if (任务 && ["failed", "cancelled", "stopped", "interrupted", "失败", "已停止"].includes(任务态?.status)) 按钮(执行工具, "恢复", () => 控制任务("resume"), !任务.token);
        状态行.textContent = 状态文字; 状态行.classList.toggle("lvp-制作错误", 错误);
        const 已 = Number(任务态?.已完成 || 0), 总 = Number(任务态?.总数 || 0);
        if (任务态 && !终态.has(任务态.status) && !总) 进度.removeAttribute("value"); else { 进度.max = 总 || 1; 进度.value = 成功(任务态?.status) ? 总 || 1 : 已; }
        进度.hidden = !任务态;
    }
    function 刷结果() {
        if (!播放器) return;
        下载区.textContent = ""; 报告区.textContent = "";
        if (结果?.video && 结果任务) 播放器.src = 制作产物URL(结果任务, 结果.video);
        else { 播放器.removeAttribute("src"); 说明(下载区, "生成结果自动加入后，点击预览在此播放。"); }
        for (const [key, label] of [["video", "下载视频"], ["subtitles", "下载字幕"], ["project", "下载工程"], ["package", "下载工程包"], ["report", "下载质量报告"]]) {
            const name = 结果?.[key]; if (typeof name !== "string") continue;
            const a = 元素("a", "", label); a.href = 制作产物URL(结果任务, name); a.download = 展示文件(name); 下载区.appendChild(a);
        }
        if (报告) {
            const issues = 报告.issues || 报告.问题 || 报告.warnings || [];
            报告区.appendChild(元素("h3", "", `质量报告 · ${Array.isArray(issues) ? issues.length : 0} 项`));
            if (报告.状态) 说明(报告区, "检查状态：" + 报告.状态);
            if (报告.指标 && typeof 报告.指标 === "object") 说明(报告区, Object.entries(报告.指标).map(([k, v]) => `${k}：${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · "));
            if (报告.summary || 报告.摘要) 说明(报告区, typeof (报告.summary || 报告.摘要) === "string" ? 报告.summary || 报告.摘要 : JSON.stringify(报告.summary || 报告.摘要));
            if (Array.isArray(issues)) for (const issue of issues) {
                const t = Number(issue.time ?? issue.时间 ?? issue.start ?? issue.开始 ?? 0), msg = typeof issue === "string" ? issue : issue.message || issue.说明 || issue.问题 || issue.description || issue.type || issue.类型 || JSON.stringify(issue);
                按钮(报告区, `${Number.isFinite(t) ? t.toFixed(1) + "s · " : ""}${msg}`, () => { if (结果?.video && Number.isFinite(t)) { 播放器.currentTime = Math.max(0, t); 播放器.focus?.(); } });
            }
            if (!issues.length) 说明(报告区, "已完成的自动检查没有报告问题。请播放确认画面、对白与剪辑效果。");
            const 未检测 = 报告.未检测 || 报告.not_checked || [];
            if (Array.isArray(未检测) && 未检测.length) 说明(报告区, "尚未检测：" + 未检测.map(v => typeof v === "string" ? v : v.说明 || v.类型 || JSON.stringify(v)).join("、"));
        }
    }
    async function 读取报告(result, job, seq, node) {
        if (result?.report && typeof result.report === "object") { 报告 = result.report; 刷结果(); return; }
        if (typeof result?.report !== "string") return;
        try { const r = await fetch(制作产物URL(job, result.report)); if (!r.ok) throw new Error(`质量报告读取失败（${r.status}）`); const j = await r.json(); if (存活(seq, node) && 结果任务?.id === job.id) { 报告 = j; 刷结果(); } }
        catch (e) { if (存活(seq, node)) 显示错误(e); }
    }
    async function 校验工程() {
        if (!存活()) return; const seq = 会话, node = 当前;
        提示("检查视频、配音、字幕与裁切范围…");
        const j = await 请求("validate", { 草稿: 取提交草稿() }); if (!存活(seq, node)) return;
        const warnings = j.warnings || [];
        提示(`校验完成 · ${Number(j.时长 || 取制作时长(读草())).toFixed(1)}秒${warnings.length ? "\n" + warnings.map(x => typeof x === "string" ? x : x.message || x.问题 || JSON.stringify(x)).join("\n") : " · 可以制作"}`, false);
    }
    async function 创建任务(模式) {
        if (!存活() || 创建中) return;
        if (任务 && 任务态 && !终态.has(任务态.status)) throw new Error("当前制作任务仍在运行，请先停止或等待完成。");
        const seq = 会话, node = 当前, snap = 捕获节点快照(node), 草稿 = 取提交草稿();
        创建中 = true; 提示(`正在提交${模式}任务…`);
        设置节点忙碌(node, "制作提交", "当前工程正在提交制作任务，请等待提交完成");
        try {
            const j = await 请求("jobs", { 草稿, 模式 });
            if (!j.id || !j.token) throw new Error("制作接口没有返回任务凭据。");
            if (!存活(seq, node)) { await 请求(`jobs/${encodeURIComponent(j.id)}/cancel`, {}, { headers: { "X-LVP-Production-Token": j.token } }); return; }
            const ok = 提交节点快照(snap, 取节点(), target => {
                const d = 真源.读剪辑草稿(target), p = 规范制作(d.制作), entry = { id: j.id, token: j.token, 模式 };
                p.最近任务 = entry;
                p.任务历史 = [...(Array.isArray(p.任务历史) ? p.任务历史 : []).filter(x => x?.id !== j.id && typeof x?.id === "string" && typeof x?.token === "string"), entry].slice(-20);
                真源.写剪辑草稿(target, { ...d, 制作: p });
            });
            if (!ok) { await 请求(`jobs/${encodeURIComponent(j.id)}/cancel`, {}, { headers: { "X-LVP-Production-Token": j.token } }); throw new Error("提交期间草稿已变化，已停止该任务，请重新提交。"); }
            清轮询(); 任务 = { id: j.id, token: j.token, 模式 }; 任务态 = { status: j.status || "queued" }; 结果 = null; 报告 = null; 结果任务 = null;
            刷历史(); 提示(`${模式}任务已提交`); 刷结果(); 开始轮询();
        } finally {
            设置节点忙碌(node, "制作提交");
            if (seq === 会话) { 创建中 = false; 刷执行区(); 刷新节点重置状态(node); }
        }
    }
    async function 控制任务(action) {
        const job = 任务, seq = 会话, node = 当前; if (!job?.token) return;
        设置节点忙碌(node, "制作控制", "当前工程正在操作制作任务，请等待完成");
        try {
        const j = await 请求(`jobs/${encodeURIComponent(job.id)}/${action}`, {}, { headers: { "X-LVP-Production-Token": job.token } });
        if (!存活(seq, node) || 任务?.id !== job.id) return;
        任务态 = { ...任务态, ...j, status: j.status || (action === "resume" ? "queued" : "cancelled") };
        刷历史();
        提示(action === "resume" ? "任务已恢复，继续处理未完成镜头" : "已请求停止制作任务");
        清轮询(); 开始轮询();
        } finally { 设置节点忙碌(node, "制作控制"); }
    }
    function 清轮询() { if (轮询计时 != null) clearTimeout(轮询计时); 轮询计时 = null; 控制器?.abort(); 控制器 = null; 轮询中 = false; }
    function 开始轮询() {
        if (!激活 || !任务?.token || !存活() || 轮询中) return;
        const job = 任务, seq = 会话, node = 当前, controller = new AbortController(); 控制器 = controller; 轮询中 = true;
        请求(`jobs/${encodeURIComponent(job.id)}`, undefined, { signal: controller.signal, headers: { "X-LVP-Production-Token": job.token } }).then(async j => {
            if (controller.signal.aborted || !存活(seq, node) || 任务?.id !== job.id) return;
            任务态 = j;
            刷历史();
            提示(`${j.阶段 || j.status || "制作中"}${j.总数 ? ` · ${j.已完成 || 0}/${j.总数}` : ""}${j.error ? "\n" + j.error : ""}`, !!j.error);
            if (成功(j.status) && j.result) { 结果 = j.result; 结果任务 = job; 报告 = null; 刷结果(); await 读取报告(j.result, job, seq, node); }
        }).catch(e => { if (!controller.signal.aborted && 存活(seq, node)) 提示(`任务状态读取失败：${e.message}。正在重试，可停止或重新打开制作页。`, true); }).finally(() => {
            if (控制器 !== controller) return;
            控制器 = null; 轮询中 = false;
            if (激活 && 存活(seq, node) && 任务?.id === job.id && !终态.has(任务态?.status)) 轮询计时 = setTimeout(() => { 轮询计时 = null; 开始轮询(); }, 1000);
        });
    }
    async function 导出工程() {
        const seq = 会话, node = 当前; 提示("正在打包工程和素材…"); const j = await 请求("export", { 草稿: 读草() });
        if (!存活(seq, node)) return;
        if (!j.result?.package || !j.id || !j.token) throw new Error("导出接口没有返回工程包。");
        const a = 元素("a"); a.href = 制作产物URL(j, j.result.package); a.download = 展示文件(j.result.package); a.click();
        提示("工程包已生成并开始下载");
    }
    async function 导入工程(file, snap, seq, node) {
        if (!file) return;
        if (!(await 弹确认("导入视频工程", "将恢复后期片段与制作设置，当前生成规划保持不变。确认恢复？"))) return;
        if (!存活(seq, node)) return;
        提示("正在导入工程包…"); const fd = new FormData(); fd.append("file", file);
        const j = await 请求("import", undefined, { method: "POST", body: fd }); if (!存活(seq, node)) return;
        if (!j.草稿 || !Array.isArray(j.草稿.segments)) throw new Error("工程包没有有效剪辑草稿。");
        const ok = 提交节点快照(snap, 取节点(), target => { const d = 真源.读剪辑草稿(target), 素 = new Map((d.素材 || []).map(x => [x.名, x])); for (const m of j.草稿.素材 || []) 素.set(m.名, m); 真源.写剪辑草稿(target, { ...d, 素材: [...素.values()], 制作: 规范制作(j.草稿.制作) }); });
        if (!ok) throw new Error("确认或导入期间草稿已变化，本次导入未覆盖草稿。");
        清轮询(); 任务 = null; 任务态 = null; 结果 = null; 报告 = null; 结果任务 = null;
        提示(`工程导入完成 · ${规范制作(j.草稿.制作).片段.length} 个后期片段`); 全刷?.(); 渲染(); await 拉元数据();
    }
    function 下载文本(name, text, mime) {
        const url = URL.createObjectURL(new Blob([text], { type: mime + ";charset=utf-8" })), a = 元素("a"); a.href = url; a.download = name; a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
    function 渲染() {
        const node = 取节点();
        if (node !== 当前) { 绑定节点(node); return; }
        if (当前) {
            const 段组 = 规范制作(读草().制作).片段; if (!段组.some(s => s.id === 段ID)) 段ID = 段组[0]?.id || "";
        }
        const scrolls = [左.scrollTop, 中.scrollTop, 右.scrollTop];
        渲染左(); 渲染中(); 渲染右();
        [左, 中, 右].forEach((el, i) => el.scrollTop = scrolls[i]);
    }
    function 绑定节点(node) {
        会话++; 清轮询(); 播放器?.pause?.(); 当前 = node; 段ID = ""; 结果 = null; 报告 = null; 结果任务 = null; 任务态 = null; 创建中 = false; 元数据 = {};
        任务 = node ? 规范制作(真源.读剪辑草稿(node).制作).最近任务 || null : null;
        状态文字 = node ? "运行当前工作流后自动加入视频；调整片段、声音和字幕，再导出成片。" : "请绑定长视频规划师节点"; 错误 = false;
        渲染(); if (激活 && node) { 拉元数据(); 开始轮询(); }
    }
    function 设激活(v) {
        激活 = !!v;
        刷新节点重置状态(当前);
        if (!激活) { 清轮询(); 播放器?.pause?.(); return; }
        if (取节点() !== 当前) 绑定节点(取节点()); else { 渲染(); if (当前) { 拉元数据(); 开始轮询(); } }
    }
    function 销毁() { 激活 = false; 会话++; 清轮询(); 播放器?.pause?.(); 根.remove(); }
    渲染();
    return { 重渲染: 渲染, 绑定节点, 设激活, 销毁,
        取重置阻止原因: node => node === 当前 && (创建中 || (激活 && 任务 && !终态.has(任务态?.status)))
            ? "当前工程的制作任务尚未结束，请先停止或等待完成" : "",
        重置: node => { 开展分区.clear(); [左, 中, 右].forEach(el => { el.scrollTop = 0; }); 绑定节点(node); },
    };
}
