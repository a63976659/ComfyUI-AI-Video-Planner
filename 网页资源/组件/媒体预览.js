const 文本预览字节上限 = 65536;   // 只读开头 64KB：长 md/txt 不整个塞进 DOM
const 文本显示字数上限 = 20000;

// 单例：同一时刻只允许一层预览。重开先拆旧的（含暂停媒体），否则叠层后 Esc 只关最上层、
// 旧 video/audio 仍在后台放声音（浏览器不会因节点脱离 DOM 自动停）。
let 当前 = null;

const 样式已注入 = { v: false };
function 注入样式() {
    if (样式已注入.v) return;
    const s = document.createElement("style");
    // 观感照宿主 lightbox 通用做法：蒙版居中、内容按视口 contain 缩放、× / 点空白 / Esc 三种关法。
    // 配色全走 var() 兜底或 rgba（本文件在 测试_主题跟随 护栏名单内，白名单为空＝禁裸 hex）。
    s.textContent = `
      .lvp-预遮罩{position:fixed;inset:0;z-index:10000;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.6)}
      .lvp-预框{display:flex;flex-direction:column;gap:6px;max-width:92vw;max-height:88vh;padding:8px 10px;box-sizing:border-box;background:var(--comfy-menu-bg,#2b2b2b);border:1px solid var(--border-color,#3a3a3a);border-radius:10px}
      .lvp-预头{display:flex;align-items:center;gap:6px;flex:0 0 auto}
      .lvp-预题{flex:1 1 auto;min-width:0;color:var(--fg-color,#ddd);font:12px system-ui;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .lvp-预关{flex:0 0 auto;width:22px;height:22px;line-height:20px;padding:0;text-align:center;border:1px solid var(--border-color,#444);border-radius:6px;background:var(--comfy-input-bg,#2f2f2f);color:var(--fg-color,#ccc);cursor:pointer;font:14px system-ui}
      .lvp-预体{display:flex;align-items:center;justify-content:center;min-width:0;min-height:0;overflow:hidden}
      .lvp-预媒{max-width:88vw;max-height:calc(88vh - 60px);width:auto;height:auto;object-fit:contain;display:block;border-radius:6px;background:var(--comfy-input-bg,#000)}
      .lvp-预音{width:min(520px,84vw)}
      .lvp-预文{margin:0;padding:8px 10px;max-width:84vw;max-height:calc(88vh - 60px);min-width:min(360px,84vw);overflow:auto;white-space:pre-wrap;word-break:break-word;background:var(--comfy-input-bg,#1a1a1a);color:var(--fg-color,#ddd);border:1px solid var(--border-color,#3a3a3a);border-radius:6px;font:12px/1.5 ui-monospace,Consolas,monospace}
      .lvp-预注{flex:0 0 auto;color:var(--p-text-muted-color,#9aa0a8);font:11px system-ui}`;
    document.head.appendChild(s);
    样式已注入.v = true;
}

function 拆() {
    if (!当前) return;
    const { 遮罩, 解绑按键 } = 当前;
    当前 = null;
    解绑按键();
    // 先 pause 再 remove：正在播放的 video/audio 离开 DOM 不会自行停止
    for (const 媒 of 遮罩.querySelectorAll("video,audio")) 媒.pause?.();
    遮罩.remove();
}

function 记字节(n) {
    return n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.ceil(n / 1024))} KB`;
}

async function 读文本(url, 正文, 注, 遮罩) {
    // Range 取开头：后端 媒体文件 用 aiohttp FileResponse，支持 Range ⇒ 206 + Content-Range。
    // 仍要兼容「服务器忽略 Range 返回 200 全量」的情况，故按实收字节判断是否截断。
    let resp;
    try {
        resp = await fetch(url, { headers: { Range: `bytes=0-${文本预览字节上限 - 1}` } });
    } catch (e) {
        if (当前?.遮罩 === 遮罩) 正文.textContent = `读取失败：${e.message || e}`;
        return;
    }
    if (!resp.ok && resp.status !== 206) {
        if (当前?.遮罩 === 遮罩) 正文.textContent = `读取失败（${resp.status}）`;
        return;
    }
    const 全文 = new TextDecoder("utf-8").decode(await resp.arrayBuffer());
    if (当前?.遮罩 !== 遮罩) return;   // 跨 await 回写作废：弹窗已关/已被新预览替换则丢弃
    const 超字数 = 全文.length > 文本显示字数上限;
    正文.textContent = 超字数 ? 全文.slice(0, 文本显示字数上限) : 全文;
    const 总 = Number((resp.headers.get("Content-Range") || "").split("/")[1]) || 0;
    const 片段 = [];
    if (总 > 全文.length) 片段.push(`仅预览开头 ${记字节(全文.length)}／共 ${记字节(总)}`);
    if (超字数) 片段.push(`仅显示开头 ${文本显示字数上限} 字`);
    注.textContent = 片段.join("，");
}

// 素材 = { 名, 类型 }，类型 ∈ 图像/视频/音频/文本（镜像 规划路由._素材类型）。
// 图像＝等比放大，视频/音频＝原生 controls 播放（可拖进度），文本＝只读预览开头。
export function 打开媒体预览(素材) {
    const 名 = String(素材?.名 || "");
    if (!名) return;
    注入样式();
    拆();
    const url = "/lvp/media/file?name=" + encodeURIComponent(名);
    const 遮罩 = document.createElement("div"); 遮罩.className = "lvp-预遮罩";
    const 框 = document.createElement("div"); 框.className = "lvp-预框";
    const 头 = document.createElement("div"); 头.className = "lvp-预头";
    const 题 = document.createElement("span"); 题.className = "lvp-预题"; 题.textContent = 名; 题.title = 名;
    const 钮 = document.createElement("button");
    钮.className = "lvp-预关"; 钮.type = "button"; 钮.textContent = "×"; 钮.title = "关闭（Esc）";
    头.append(题, 钮);
    const 体 = document.createElement("div"); 体.className = "lvp-预体";
    框.append(头, 体);
    遮罩.appendChild(框);
    const 键 = (e) => { if (e.key === "Escape") 拆(); };
    钮.onclick = 拆;
    遮罩.onclick = (e) => { if (e.target === 遮罩) 拆(); };   // 点蒙版空白关闭，点内容不关
    document.addEventListener("keydown", 键);
    当前 = { 遮罩, 解绑按键: () => document.removeEventListener("keydown", 键) };

    const 类型 = 素材.类型;
    if (类型 === "视频" || 类型 === "音频") {
        const 媒 = document.createElement(类型 === "视频" ? "video" : "audio");
        媒.className = 类型 === "视频" ? "lvp-预媒" : "lvp-预音";
        媒.src = url;
        媒.controls = true;                     // 交给浏览器原生控件：播放/暂停/进度/音量
        if (类型 === "视频") 媒.playsInline = true;
        体.appendChild(媒);
    } else if (类型 === "图像") {
        const 图 = document.createElement("img");
        图.className = "lvp-预媒"; 图.src = url; 图.alt = 名;
        体.appendChild(图);
    } else {
        const 文 = document.createElement("pre");
        文.className = "lvp-预文"; 文.textContent = "加载中…";
        // 截断说明只有文本用得到，注释放进本分支：图/音/视那一支不留空行。
        const 注 = document.createElement("div"); 注.className = "lvp-预注";
        体.appendChild(文);
        框.appendChild(注);
        读文本(url, 文, 注, 遮罩);
    }

    document.body.appendChild(遮罩);
    钮.focus?.();
}
