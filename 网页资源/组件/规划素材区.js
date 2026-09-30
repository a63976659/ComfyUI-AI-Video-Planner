import { app } from "../../../scripts/app.js";
import { 真源, 捕获节点快照, 提交节点快照 } from "./桥接/节点桥.js";
import { 打开媒体预览 } from "./媒体预览.js";

// 规划素材区（AI规划页左列）：规划期专用素材清单，真源＝剪辑草稿顶层 素材 键（缺省＝键不存在）。
// 文件经 /lvp/media/upload 落媒体库，但**不写节点「参考素材」全局池**（裁定 R4，设计 2026-09-29 §2）；
// 删除仅移出清单并同步剔除 全局素材/段 使用素材 引用，盘上文件保留（同 参考文件区 口径）。
export const 素材类型枚举 = ["图像", "视频", "音频", "文本"];   // 镜像 后端路由/规划路由.py _素材类型（测试_常量同步 锁）
const 类型表 = [
    { 型: "图像", accept: "image/*", 扩: ["jpg", "jpeg", "png", "gif", "webp", "bmp", "tiff", "avif"] },
    { 型: "视频", accept: "video/*", 扩: ["mp4", "mov", "webm", "avi", "mkv", "m4v"] },
    { 型: "音频", accept: "audio/*", 扩: ["mp3", "wav", "m4a", "aac", "ogg", "flac"] },
    { 型: "文本", accept: ".txt,.md", 扩: ["txt", "md"] },
];
// 类型角标表对外导出：素材墙的缩略角标与 @ 提及弹层（素材提及.js）共用同一份，避免两处各写一份而漂移。
// 音频＝♪（U+266A 文本字形，吃 CSS color，故能单独上绿色；用户 2026-09-30）；其余三类是 emoji，
// 浏览器按彩色字体位图渲染、color 对它们无效，所以绿色只可能落在 ♪ 上。
export const 图标 = { 图像: "🖼️", 视频: "🎬", 音频: "♪", 文本: "📄" };

export function 按扩展名定类型(名) {
    const 扩 = (名.split(".").pop() || "").toLowerCase();
    return (类型表.find((t) => t.扩.includes(扩)) || {}).型 || null;
}

const 样式已注入 = { v: false };
function 注入样式() {
    if (样式已注入.v) return;
    const s = document.createElement("style");
    s.textContent = `
      .lvp-规材{display:flex;flex-direction:column;gap:6px;flex:1;min-width:0;box-sizing:border-box;background:var(--comfy-menu-bg,#2b2b2b);padding:6px;border-radius:8px}
      .lvp-规材头{display:flex;gap:4px;align-items:center}
      .lvp-规材题{color:var(--fg-color,#ddd);font-size:10px;font-weight:600;flex:1 1 auto}
      /* 清空钮＝框架基元 .lvp-胶囊 ＋ 本区尺寸覆写（同 规划页面板 的 .lvp-生成 路子）：
         标题行是 10px 字阶，胶囊默认字号会顶高一截、把缩略图墙挤下去。 */
      .lvp-规材清空{font-size:10px;padding:1px 6px;line-height:14px}
      /* 置灰要看得见：胶囊自持 background/color，UA 的 disabled 观感在深色主题下几乎没差别，
         所以显式压暗＋取消手型，避免用户以为「按了没反应」而连点。 */
      .lvp-规材清空:disabled{opacity:.45;cursor:default}
      /* 方形缩略图墙（对齐 提示词编辑界面 的 .lvp-缩略 观感，但类名/样式自带，不跨页依赖 编辑页面板.js）：
         四类混排在一个网格里（用户 2026-09-30「取消分类，不同类型都在一起，画面简洁、不用上下翻页」），
         类型靠图面自身区分——图像/视频＝媒体首帧封面、音频＝绿色 ♪、文本＝📄，另在每块左下角钉该类型的图标角标
         （图像与视频的封面肉眼难分，角标是唯一的区分锚）；框尾 ＋ 虚线块弹一次多选文件、按扩展名分流。
         全部色走 var() 兜底（本文件白名单为空，禁裸 hex）。 */
      .lvp-规材框{display:grid;grid-template-columns:repeat(auto-fill,66px);grid-auto-rows:66px;gap:4px;padding:4px;box-sizing:border-box;flex:1;min-height:0;overflow-y:auto;border:1px solid var(--border-color,#3a3a3a);border-radius:6px;background:var(--comfy-menu-bg,#2b2b2b)}
      .lvp-规材缩略{position:relative;display:inline-flex;width:66px;height:66px;border:1px solid var(--border-color,#3a3a3a);border-radius:6px;overflow:hidden;background:var(--comfy-input-bg,#1a1a1a);cursor:pointer}
      .lvp-规材媒{width:100%;height:100%;object-fit:cover;display:block;pointer-events:none}
      .lvp-规材符{width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:26px;color:var(--p-text-muted-color,#9aa0a8)}
      .lvp-规材角标{position:absolute;left:1px;bottom:1px;padding:0 2px;border:0;border-radius:3px;background:rgba(0,0,0,.55);color:var(--p-primary-contrast-color,#fff);font-size:10px;line-height:14px;pointer-events:none}
      /* 音频标记上绿（用户 2026-09-30）：写在 符/角标 之后，同权重靠后写规则盖掉各自的灰/白字色；
         色值走 var() 兜底（本文件白名单为空，禁裸 hex），绿色 token 与 规划器设置.js 的 --p-green-400 同源。 */
      .lvp-规材音{color:var(--p-green-400,#7ee0a3)}
      .lvp-规材删{position:absolute;top:1px;right:1px;width:16px;height:16px;line-height:14px;text-align:center;border:0;border-radius:4px;background:rgba(0,0,0,.55);color:var(--p-primary-contrast-color,#fff);cursor:pointer;font-size:12px;padding:0}
      .lvp-规材删:hover{background:rgba(0,0,0,.75)}
      .lvp-规材添加{align-items:center;justify-content:center;padding:0;appearance:none;color:var(--p-primary-color,#4a9eff);font:32px/1 system-ui;cursor:pointer;border-style:dashed}
      .lvp-规材添加:hover{border-color:var(--p-primary-color,#4a9eff)}
      .lvp-规材拖{outline:1px dashed var(--p-primary-color,#4a9eff);outline-offset:-3px}
      /* 悬停全名浮层：挂 body 的单例（见 显名 注释），pointer-events:none 保证永远不吃掉瓦片的点击/悬停。
         word-break:break-all＝长文件名（无空格）也能折行看全，不溢出视口。 */
      .lvp-规材浮名{position:fixed;z-index:9999;display:none;max-width:min(320px,86vw);padding:2px 6px;border-radius:4px;background:var(--comfy-input-bg,#1c1c1c);border:1px solid var(--border-color,#444);color:var(--fg-color,#ddd);font:10px/1.35 system-ui;word-break:break-all;pointer-events:none;box-shadow:0 2px 8px rgba(0,0,0,.35)}`;
    document.head.appendChild(s);
    样式已注入.v = true;
}

function toast(消息, severity = "info") { app?.ui?.toast?.showMessage?.({ message: 消息, severity }); }

// 二次确认：优先用 ComfyUI 原生确认框（extensionManager.dialog.confirm，返回 Promise<bool>），
// 宿主未提供时退回同步 window.confirm——与 参考文件区.js / 提示词编辑器.js 的 弹确认() 同款结构。
async function 弹确认(标题, 消息) {
    const 框 = app?.extensionManager?.dialog;
    if (框?.confirm) {
        // 确认→true、取消/关闭→false；异常一律按「取消」处理，绝不再弹 window.confirm 造成双框。
        try { return !!(await 框.confirm({ title: 标题, message: 消息 })); }
        catch { return false; }
    }
    return window.confirm(`${标题}\n\n${消息}`);
}

// 悬停全名浮层＝模块级单例（同 媒体预览.js 口径）。⚠️ 必须挂 document.body，不能做成瓦片的 CSS 子元素：
//   ①`.lvp-规材框` 有 overflow-y:auto、`.lvp-规材缩略` 有 overflow:hidden，越界的提示会被裁掉；
//   ②规划页容器写了 container-type:inline-size（⇒ contain:layout），它就成了 position:fixed 后代的
//     包含块，fixed 坐标会相对页面而不是视口。原生 title 又要点约 1 秒才出、样式不受控。
let 名浮层 = null;
function 显名(瓦, 文) {
    if (!名浮层?.isConnected) {
        名浮层 = document.createElement("div");
        名浮层.className = "lvp-规材浮名";
        document.body.appendChild(名浮层);
    }
    名浮层.textContent = 文;
    名浮层.style.display = "block";   // 先显形才量得到宽高，再据视口夹位（量不到时会算出 NaN 坐标）
    const 尺 = 瓦.getBoundingClientRect(), 边距 = 6, 间隙 = 4;   // 局部变量别叫「框」，本文件里 框＝素材墙容器
    let 左 = 尺.left + 尺.width / 2 - 名浮层.offsetWidth / 2;
    左 = Math.max(边距, Math.min(左, window.innerWidth - 边距 - 名浮层.offsetWidth));
    let 上 = 尺.bottom + 间隙;
    if (上 + 名浮层.offsetHeight > window.innerHeight - 边距) 上 = 尺.top - 间隙 - 名浮层.offsetHeight;
    名浮层.style.left = 左 + "px";
    名浮层.style.top = 上 + "px";
}
function 隐名() { if (名浮层) 名浮层.style.display = "none"; }

export function 创建规划素材区(容器, { 取节点 }) {
    注入样式();
    const 根 = document.createElement("div");
    根.className = "lvp-规材";
    const 头 = document.createElement("div"); 头.className = "lvp-规材头";
    const 题 = document.createElement("span"); 题.className = "lvp-规材题"; 题.textContent = "规划素材";
    // 清空＝标题行最右的批量出口（用户 2026-09-30）：逐张点 × 太累，但一次摘掉整面墙不可逆 ⇒ 走弹窗二次确认；
    //   题 有 flex:1 1 auto，按钮排在题后就被推到行尾；配色沿用框架层跨页基元 .lvp-胶囊
    //   （状态栏面板.js 注入，本区必然渲染在其页面内），本文件只加尺寸覆写。
    const 清空钮 = document.createElement("button");
    清空钮.className = "lvp-胶囊 lvp-规材清空"; 清空钮.type = "button"; 清空钮.textContent = "清空素材";
    清空钮.title = "一键移除本节点全部规划素材，并同步剔除全局素材与各段「使用素材」引用（弹窗确认后生效，磁盘文件保留）";
    清空钮.onclick = 清空;
    头.append(题, 清空钮);
    // 一个隐藏多选 file input（框尾 ＋ 块触发）：accept 取四类型并集，落哪个类型仍由 按扩展名定类型 判，
    // 与拖入路径同一条分流口径（用户 2026-09-30 取消分组后不再需要「按类型分别选文件」）。
    const 输入 = document.createElement("input");
    输入.type = "file"; 输入.accept = 类型表.map((t) => t.accept).join(","); 输入.multiple = true; 输入.style.display = "none";
    输入.onchange = () => { if (输入.files.length) 上传([...输入.files]); 输入.value = ""; };
    头.appendChild(输入);
    const 框 = document.createElement("div"); 框.className = "lvp-规材框";
    框.onscroll = 隐名;   // 滚动会让瓦片位移、浮层原地不动，一滚就收
    根.append(头, 框);
    根.ondragover = (e) => { e.preventDefault(); 根.classList.add("lvp-规材拖"); };
    根.ondragleave = () => 根.classList.remove("lvp-规材拖");
    根.ondrop = (e) => { e.preventDefault(); 根.classList.remove("lvp-规材拖"); if (e.dataTransfer?.files?.length) 上传([...e.dataTransfer.files]); };
    容器.appendChild(根);

    function 读清单() {
        const n = 取节点();
        return n ? (真源.读剪辑草稿(n).素材 || []) : [];
    }
    function 渲染() {
        框.textContent = "";
        隐名();   // 重建式渲染：旧瓦片已离开 DOM，浮层再指着它就是一条悬空名字
        const 清单 = 读清单();
        题.textContent = `规划素材 ${清单.length}`;
        清空钮.disabled = !清单.length;   // 没素材就点不动：比点了才 toast 更早给出可见反馈（置灰观感见上方 :disabled 覆写）
        题.title = `素材仅供 AI 规划判断用法（不进节点全局素材池）；可直接拖入本区，或点末尾 ＋ 选文件｜${类型表.map((t) => `${t.型} ${清单.filter((m) => m.类型 === t.型).length}`).join(" ")}`;
        for (const m of 清单) {
            const 瓦 = document.createElement("span"); 瓦.className = "lvp-规材缩略";
            // 全名交给悬停浮层即时显示，原生 title 只留「类型＋可点击」这句操作提示（否则两套提示叠着出）。
            瓦.title = `${m.类型}｜点击预览`;
            瓦.onmouseenter = () => 显名(瓦, m.名);
            瓦.onmouseleave = 隐名;
            瓦.onclick = () => 打开媒体预览({ 名: m.名, 类型: m.类型 });
            if (m.类型 === "图像" || m.类型 === "视频") {
                // 图像直接 <img>；视频用 #t=0.1 + preload=metadata 取首帧作封面（同 参考文件区 口径）
                const url = "/lvp/media/file?name=" + encodeURIComponent(m.名);
                const 媒 = document.createElement(m.类型 === "图像" ? "img" : "video");
                媒.className = "lvp-规材媒";
                if (m.类型 === "图像") { 媒.src = url; 媒.alt = m.名; }
                else { 媒.src = url + "#t=0.1"; 媒.muted = true; 媒.preload = "metadata"; 媒.playsInline = true; }
                瓦.appendChild(媒);
            } else {
                // 音频/文本无可视封面 → 图标占位块（与图/视频缩略图同尺寸，网格不跳高），字形一律取 图标 表
                const 符 = document.createElement("span"); 符.className = "lvp-规材符";
                if (m.类型 === "音频") 符.classList.add("lvp-规材音");   // 绿色只落在 ♪ 上（emoji 不吃 color）
                符.textContent = 图标[m.类型];
                瓦.appendChild(符);
            }
            // 混排后没有组头可读类型，角标＝每块的类型锚（尤其图/视封面难分）
            const 角 = document.createElement("span"); 角.className = "lvp-规材角标";
            if (m.类型 === "音频") 角.classList.add("lvp-规材音");   // 角标同样是绿色 ♪
            角.textContent = 图标[m.类型];
            const 删 = document.createElement("button"); 删.className = "lvp-规材删"; 删.type = "button"; 删.textContent = "×"; 删.title = `移除 ${m.名}（媒体库文件保留）`;
            删.onclick = (e) => { e.stopPropagation(); 删除(m.名); };   // 删钮在可点击瓦片内：拦住冒泡，否则移除同时弹预览
            瓦.append(角, 删);
            框.appendChild(瓦);
        }
        const 加 = document.createElement("button"); 加.className = "lvp-规材缩略 lvp-规材添加"; 加.type = "button";
        加.textContent = "＋"; 加.title = "上传素材（图/视/音/文本，按扩展名自动归类）"; 加.setAttribute("aria-label", 加.title);
        加.onclick = () => 输入.click();
        框.appendChild(加);
    }
    // 重建式写草稿：保态携带 禁用字幕/segments/brief，其余缺省不写键；删名同步剔除引用
    function 写回(新清单, 快照) {
        const 已提交 = 提交节点快照(快照, 取节点(), (目标) => {
            const 草 = 真源.读剪辑草稿(目标);
            const 写 = { brief: 草.brief || {}, segments: 草.segments || [] };
            if (草?.禁用字幕 === true) 写.禁用字幕 = true;
            const 名集 = new Set(新清单.map((x) => x.名));
            if (新清单.length) 写.素材 = 新清单;
            const 全 = (草.全局素材 || []).filter((n) => 名集.has(n));
            if ((草.全局素材 || []).length && 全.length) 写.全局素材 = 全;
            写.segments = (草.segments || []).map((s) => {
                if (!Array.isArray(s?.使用素材) || !s.使用素材.length) return s;
                const 用 = s.使用素材.filter((n) => 名集.has(n));
                const 副 = { ...s };
                if (用.length) 副.使用素材 = 用; else delete 副.使用素材;
                return 副;
            });
            真源.写剪辑草稿(目标, 写);
        });
        if (!已提交) toast("节点或草稿已变化，本次素材操作未生效", "warn");
        return 已提交;
    }
    async function 上传(文件组) {
        const 节点 = 取节点();
        if (!节点) { toast("请先绑定长视频规划师节点", "error"); return; }
        const 快照 = 捕获节点快照(节点, ["剪辑草稿"]);
        const 现有 = 读清单().slice();
        let 变了 = false;
        for (const f of 文件组) {
            const 型 = 按扩展名定类型(f.name);
            if (!型) { toast(`不支持的文件类型：${f.name}（限图/视/音/txt/md）`, "warn"); continue; }
            const fd = new FormData(); fd.append("file", f);
            try {
                const r = await fetch("/lvp/media/upload", { method: "POST", body: fd });
                const j = await r.json().catch(() => ({}));
                if (!r.ok) throw new Error(j?.error || `上传失败（${r.status}）`);
                if (!现有.some((m) => m.名 === j.name)) { 现有.push({ 名: j.name, 类型: 型 }); 变了 = true; }
            } catch (e) { toast(`${f.name}：${e.message}`, "error"); }
        }
        if (变了 && 写回(现有, 快照)) 渲染();
    }
    function 删除(名) {
        const 节点 = 取节点(); if (!节点) return;
        const 快照 = 捕获节点快照(节点, ["剪辑草稿"]);
        if (写回(读清单().filter((m) => m.名 !== 名), 快照)) 渲染();
    }
    // 清空＝按 删除 的同一条口径一次做完：传空清单给 写回 ⇒ 素材 键不写（缺省＝键不存在），
    //   并连带剔除 全局素材 与各段 使用素材 引用；磁盘文件一律不动。
    // ⚠️ 快照必须在 await 确认框**之前**捕获：弹窗开着时别处（另一页/另一次上传）改了草稿，
    //   提交校验会判失效并 toast 未生效，绝不会把别人的新草稿覆盖成空。
    async function 清空() {
        const 节点 = 取节点();
        if (!节点) { toast("请先绑定长视频规划师节点", "error"); return; }
        const 清单 = 读清单();
        // disabled 只在 渲染 时刷，而 素材/全局素材 也会被别处写回 ⇒ 这里再判一次，别弹空确认框。
        if (!清单.length) { toast("没有可清空的素材"); return; }
        const 快照 = 捕获节点快照(节点, ["剪辑草稿"]);
        const 计数 = 类型表.map((t) => `${t.型} ${清单.filter((m) => m.类型 === t.型).length}`).join("／");
        const 确认 = await 弹确认("清空规划素材",
            `将移除全部 ${清单.length} 条规划素材（${计数}），并同步剔除全局素材引用与各段「使用素材」引用；` +
            "\n\n媒体库里的文件不会删除，之后可重新添加。确认清空？");
        if (!确认) return;
        // 写回成功必须紧跟 渲染()（同 上传/删除 口径）：只 toast 不重绘的话，墙上的瓦片、标题计数、
        //   清空钮的 disabled 三处都停在清空前，看起来像「确认了却没生效」。
        if (写回([], 快照)) { 渲染(); toast(`已清空 ${清单.length} 条规划素材（磁盘文件保留）`); }
    }

    渲染();
    return { 刷新: 渲染 };
}
