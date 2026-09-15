import { app } from "../../../scripts/app.js";

const 上限 = { 图片: 9, 音频: 3, 视频: 3 };
const 接受 = { 图片: "image/*", 音频: "audio/*", 视频: "video/*" };

function toast(文本) { app?.ui?.toast?.showMessage?.(文本); }

export function 创建参考文件区(容器, { 变更, 共用变更 }) {
    const 盒 = document.createElement("div");
    盒.className = "lvp-参考";
    容器.appendChild(盒);
    let 素材 = { 图片: [], 音频: [], 视频: [] };
    // 「全段共用」开关态（真源在节点 widget「参考共用」，此处仅缓存供渲染）：
    // 共用=是否全段统一用全局池；共用可见=是否 r2v/v2v/rv2v（由状态栏面板 设共用可见 控制）。
    let 共用 = false, 共用可见 = true, 共用组 = null, 共用钮 = null;

    function 渲染() {
        盒.innerHTML = "";
        // 三类型横向排列：图像走九宫格（3 列 66px），视频/音频在各自类型名下竖向排列
        for (const 槽 of ["图片", "视频", "音频"]) {
            const 组 = document.createElement("div");
            组.className = "lvp-参考组";
            const 头 = document.createElement("div");
            头.className = "lvp-参考头";
            const 标题 = document.createElement("span");
            标题.textContent = `${槽 === "图片" ? "图像" : 槽} ${素材[槽].length}/${上限[槽]}`;
            const 加 = document.createElement("button");
            加.className = "lvp-胶囊"; 加.type = "button";
            加.textContent = "＋"; 加.title = "上传" + 槽;
            加.onclick = () => 触发上传(槽);
            头.append(标题, 加);

            const 内容 = document.createElement("div");
            内容.className = 槽 === "图片" ? "lvp-九宫" : "lvp-竖列";
            素材[槽].forEach((名, i) => {
                const 删 = () => { 素材[槽].splice(i, 1); 提交(); };
                const 瓦 = document.createElement("span");
                瓦.className = "lvp-缩略";
                瓦.title = `${i + 1}. ${名}`;
                if (槽 === "音频") {
                    // 音频无可视封面，统一用音符图标封面（与图/视频缩略图同尺寸）
                    const 音 = document.createElement("span");
                    音.className = "lvp-音标";
                    音.textContent = "♪";
                    瓦.appendChild(音);
                } else {
                    // 图片直接 <img>；视频用 #t=0.1 + preload=metadata 取首帧作封面
                    const url = "/lvp/media/file?name=" + encodeURIComponent(名);
                    const 媒 = document.createElement(槽 === "图片" ? "img" : "video");
                    媒.className = "lvp-缩略媒";
                    if (槽 === "图片") { 媒.src = url; 媒.alt = 名; }
                    else { 媒.src = url + "#t=0.1"; 媒.muted = true; 媒.preload = "metadata"; 媒.playsInline = true; }
                    瓦.appendChild(媒);
                }
                const x = document.createElement("b");
                x.textContent = "×";
                x.onclick = 删;
                瓦.appendChild(x);
                内容.appendChild(瓦);
            });

            组.append(头, 内容);
            组.ondragover = (e) => e.preventDefault();
            组.ondrop = (e) => { e.preventDefault(); 上传文件(槽, e.dataTransfer.files); };
            盒.appendChild(组);
        }
        // 「全段共用」开关：置于素材区右侧（图片/视频/音频 三组之后）。开启后 参考生视频
        // (r2v/v2v/rv2v) 所有段统一用左侧全局参考池（执行核心 _应用全局 覆盖段级 refs），
        // 用户只需编辑每段提示词；i2v/fl2v 用段级首尾帧、t2v 无参考 → 由 设共用可见 隐藏。
        共用组 = document.createElement("div");
        共用组.className = "lvp-参考组";
        const 共用头 = document.createElement("div");
        共用头.className = "lvp-参考头";
        const 共用标 = document.createElement("span");
        共用标.textContent = "全段共用";
        共用钮 = document.createElement("button");
        共用钮.className = "lvp-胶囊";
        共用钮.type = "button";
        共用钮.title = "开启：所有段统一使用左侧全局参考素材（覆盖每段自有 refs），只需编辑各段提示词；关闭：段级 refs 优先、全局兜底";
        共用钮.onclick = () => { 共用 = !共用; 更新共用钮(); 共用变更?.(共用); };
        共用头.append(共用标, 共用钮);
        共用组.appendChild(共用头);
        共用组.style.visibility = 共用可见 ? "visible" : "hidden";
        更新共用钮();
        盒.appendChild(共用组);
    }

    // 开关按钮外观随 共用 态刷新（激活=蓝色胶囊 + "开"，否则灰 + "关"）；复用 .lvp-胶囊 样式，无需新增 CSS。
    function 更新共用钮() {
        if (!共用钮) return;
        共用钮.classList.toggle("激活", 共用);
        共用钮.textContent = 共用 ? "开" : "关";
    }

    function 触发上传(槽) {
        const inp = document.createElement("input");
        inp.type = "file"; inp.multiple = true; inp.accept = 接受[槽];
        inp.onchange = () => 上传文件(槽, inp.files);
        inp.click();
    }

    async function 上传文件(槽, 文件列表) {
        for (const 文件 of 文件列表 || []) {
            if (素材[槽].length >= 上限[槽]) { toast(`${槽}已达上限 ${上限[槽]}`); break; }
            const fd = new FormData();
            fd.append("file", 文件, 文件.name);
            try {
                const res = await fetch("/lvp/media/upload", { method: "POST", body: fd });
                const data = await res.json();
                // HTTP 边界（Task 12 §接口约束 3）：4xx/5xx 走 JSON {error}，fetch 不抛，
                // 若不判 res.ok 直接读 data.name → undefined 会污染数组（后续 stringify 落
                // widget 变 null、后端 _规范列表 静默丢 → 序号错位）。
                if (!res.ok) { toast(`上传失败（HTTP ${res.status}）：${data?.error || "服务端错误"}`); continue; }
                if (data.name && !素材[槽].includes(data.name)) 素材[槽].push(data.name);
                if (data.dedup) toast(`已存在，跳过重复：${data.name}`);
            } catch (e) { toast("上传失败：" + e.message); }
        }
        提交();
    }

    function 提交() { 渲染(); 变更?.({ 图片: [...素材.图片], 音频: [...素材.音频], 视频: [...素材.视频] }); }
    function 设值(v) {
        // 归一化：容忍 v 为 null / 缺字段 / 字段为 null（防御 widget 外部手写脏值），
        // 三槽恒定用新数组承接，避免 spread 顶层把 null 直塞进来后 .length / .includes 抛。
        const s = v || {};
        素材 = { 图片: [...(s.图片 || [])], 音频: [...(s.音频 || [])], 视频: [...(s.视频 || [])] };
        渲染();
    }

    渲染();
    return {
        设值, 取值: () => ({ ...素材 }),
        设共用: (v) => { 共用 = !!v; 更新共用钮(); },
        设共用可见: (v) => { 共用可见 = !!v; if (共用组) 共用组.style.visibility = 共用可见 ? "visible" : "hidden"; },
        盒,   // 盒：供状态栏面板按任务类型联动显隐
    };
}
