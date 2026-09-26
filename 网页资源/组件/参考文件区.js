import { app } from "../../../scripts/app.js";

const 上限 = { 图片: 9, 音频: 3, 视频: 3 };
const 接受 = { 图片: "image/*", 音频: "audio/*", 视频: "video/*" };
// 拖入不受 input accept 约束（drop 任何组都收得到全部文件），按 MIME 前缀分类、
// type 为空（如 mkv/系统拖入常见）时按扩展名回退；判定不了即拒收。
const MIME槽 = { image: "图片", audio: "音频", video: "视频" };
const 扩展槽 = {
    png: "图片", jpg: "图片", jpeg: "图片", gif: "图片", webp: "图片", bmp: "图片",
    mp4: "视频", mov: "视频", webm: "视频", avi: "视频", mkv: "视频",
    mp3: "音频", wav: "音频", aac: "音频", ogg: "音频", m4a: "音频", flac: "音频",
};

function 推断槽(文件) {
    const 类 = String(文件.type || "").split("/")[0];
    if (MIME槽[类]) return MIME槽[类];
    const 名 = String(文件.name || "");
    const 点 = 名.lastIndexOf(".");
    return 点 > 0 ? 扩展槽[名.slice(点 + 1).toLowerCase()] ?? null : null;
}

function toast(文本) { app?.ui?.toast?.showMessage?.(文本); }

// 二次确认：优先用 ComfyUI 原生确认框（extensionManager.dialog.confirm，返回 Promise<bool>），
// 宿主未提供时退回同步 window.confirm——与 提示词编辑器.js / 计划数据.js 的 弹确认() 同款结构。
async function 弹确认(标题, 消息) {
    const 框 = app?.extensionManager?.dialog;
    if (框?.confirm) {
        // 确认→true、取消/关闭→false；异常一律按「取消」处理，绝不再弹 window.confirm 造成双框。
        try { return !!(await 框.confirm({ title: 标题, message: 消息 })); }
        catch { return false; }
    }
    return window.confirm(`${标题}\n\n${消息}`);
}

export function 创建参考文件区(容器, { 变更, 共用变更, 捕获快照 }) {
    const 盒 = document.createElement("div");
    盒.className = "lvp-参考";
    容器.appendChild(盒);
    let 素材 = { 图片: [], 音频: [], 视频: [] };
    // 上传跨 await fetch 的回写作废追踪（spec 上传换绑）：
    //   ·切段代数：设值() 由 回填 在换节点/换选中段/全刷/重绑 时调用 → 每次目标重绑 ++。
    //     节点快照对「同节点换选中段」无效（选中段不入时间轴数据），靠此拦。
    //   ·请求序号：并发多批上传只认最新，旧批后到也不得覆盖新批（响应倒序）。
    let 切段代数 = 0, 请求序号 = 0;
    // 「全段共用」开关态（真源在当前段 refs.共用，此处仅缓存供渲染）：
    // 共用=是否本段素材覆盖所有段；共用可见=是否 r2v/v2v/rv2v（由状态栏面板 设共用可见 控制）。
    let 共用 = false, 共用可见 = true, 共用头 = null, 共用钮 = null;

    function 渲染() {
        盒.innerHTML = "";
        // 三类型横向排列：图像走九宫格（3 列 66px），视频/音频在各自类型名下竖向排列
        for (const 槽 of ["图片", "视频", "音频"]) {
            const 组 = document.createElement("div");
            组.className = "lvp-参考组 lvp-素材组";
            const 头 = document.createElement("div");
            头.className = "lvp-参考头";
            const 标题 = document.createElement("span");
            标题.textContent = `${槽 === "图片" ? "图像" : 槽} ${素材[槽].length}/${上限[槽]}`;
            头.appendChild(标题);

            const 内容 = document.createElement("div");
            内容.className = 槽 === "图片" ? "lvp-素材框 lvp-九宫" : "lvp-素材框";
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
            if (素材[槽].length < 上限[槽]) {
                const 加 = document.createElement("button");
                加.className = "lvp-缩略 lvp-素材添加"; 加.type = "button";
                加.textContent = "＋"; 加.title = "上传" + 槽;
                加.setAttribute("aria-label", 加.title);
                加.onclick = () => 触发上传(槽);
                内容.appendChild(加);
            }

            组.append(头, 内容);
            组.ondragover = (e) => e.preventDefault();
            组.ondrop = (e) => { e.preventDefault(); 拖入分流(e.dataTransfer.files); };
            盒.appendChild(组);
        }
        // 「全段共用」开关＋「清理素材」：置于素材区右侧（图片/视频/音频 三组之后），同一列组上下两排
        // （横向各占一排太吃宽度）。开启共用后本段素材将覆盖所有段
        // （执行核心 _查找共用素材 找到第一个 refs.共用=True 的段，用其素材统一覆盖），
        // 用户只需编辑每段提示词；i2v/fl2v 用段级首尾帧、t2v 无参考 → 由 设共用可见 隐藏（只隐藏共用这一排）。
        const 共用组 = document.createElement("div");
        共用组.className = "lvp-参考组";
        共用头 = document.createElement("div");
        共用头.className = "lvp-参考头";
        const 共用标 = document.createElement("span");
        共用标.textContent = "全段共用";
        共用钮 = document.createElement("button");
        共用钮.className = "lvp-胶囊";
        共用钮.type = "button";
        共用钮.title = "开启：本段素材将覆盖所有段（全段统一使用本段上传的参考素材），只需编辑各段提示词；关闭：每段使用各自的素材";
        共用钮.onclick = () => { 共用 = !共用; 更新共用钮(); 共用变更?.(共用); };
        共用头.append(共用标, 共用钮);
        共用头.style.visibility = 共用可见 ? "visible" : "hidden";
        更新共用钮();
        // 清理确认同时锁定切段代数和节点快照，重配不回填参考区时也必须作废。
        const 清理头 = document.createElement("div");
        清理头.className = "lvp-参考头";
        const 钮 = document.createElement("button");
        钮.className = "lvp-胶囊";
        钮.type = "button";
        钮.textContent = "清理素材";
        钮.title = "一键清除本段已添加的全部图像/视频/音频素材（弹窗确认后生效，不删除磁盘文件）";
        钮.onclick = async () => {
            if (!素材.图片.length && !素材.视频.length && !素材.音频.length) { toast("没有可清理的素材"); return; }
            const 发起切段 = 切段代数, 快照 = 捕获快照?.();
            const 确认 = await 弹确认("清理素材",
                "将清空本段全部图像/视频/音频素材及其首尾帧引用（不删除磁盘文件）。确认清理？");
            if (!确认) return;
            if (发起切段 !== 切段代数) { toast("节点或选中段已变化，未执行清理"); return; }
            if (提交(快照, { 图片: [], 音频: [], 视频: [] })) 请求序号++;
        };
        清理头.appendChild(钮);
        共用组.append(共用头, 清理头);
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

    // 拖入落点组不参与决策：按 推断槽 分流，图像拖到视频组也只进图像区；判定不了的当场拒收。
    function 拖入分流(文件列表) {
        const 分组 = {}, 未知 = [];
        for (const 文件 of 文件列表 || []) {
            const 槽 = 推断槽(文件);
            if (!槽) { 未知.push(文件.name); continue; }
            (分组[槽] ||= []).push(文件);
        }
        for (const 名 of 未知) toast(`不支持的素材类型：${名}（只接受图像/视频/音频）`);
        上传分组(分组);
    }

    function 上传文件(槽, 文件列表) { 上传分组({ [槽]: [...(文件列表 || [])] }); }

    async function 上传分组(分组) {
        // 发起时锁定目标三元组：换节点/换段/删段/重配/新一批上传 均会使本批作废。
        //   ·快照 拦 “节点身份+时间轴版本+节点代数”（换节点/删段改时间轴/工作流重配）；
        //   ·切段代数 拦 “选中段变化”（同节点换段，时间轴数据未变）；
        //   ·请求序号 拦 “后发先至/旧批后到”（并发多批只认最新）。
        //   一次拖入跨多槽也只 ++ 一次：整批同进同退，槽间不互相作废。
        const 槽序 = ["图片", "视频", "音频"].filter(槽 => 分组[槽]?.length);
        if (!槽序.length) return;
        const 快照 = 捕获快照?.();
        const 发起切段 = 切段代数, 本次序号 = ++请求序号;
        const 新增 = { 图片: [], 视频: [], 音频: [] };   // 只收集，不落 素材；await 期间目标一旦变化整批作废，不污染当前视图
        for (const 槽 of 槽序) {
            for (const 文件 of 分组[槽]) {
                if (素材[槽].length + 新增[槽].length >= 上限[槽]) { toast(`${槽}已达上限 ${上限[槽]}`); break; }
                const fd = new FormData();
                fd.append("file", 文件, 文件.name);
                try {
                    const res = await fetch("/lvp/media/upload", { method: "POST", body: fd });
                    const data = await res.json();
                    // HTTP 边界（Task 12 §接口约束 3）：4xx/5xx 走 JSON {error}，fetch 不抛，
                    // 若不判 res.ok 直接读 data.name → undefined 会污染数组（后续 stringify 落
                    // widget 变 null、后端 _规范列表 静默丢 → 序号错位）。
                    if (!res.ok) { toast(`上传失败（HTTP ${res.status}）：${data?.error || "服务端错误"}`); continue; }
                    if (data.name && !素材[槽].includes(data.name) && !新增[槽].includes(data.name)) 新增[槽].push(data.name);
                    if (data.dedup) toast(`已存在，跳过重复：${data.name}`);
                } catch (e) { toast("上传失败：" + e.message); }
            }
        }
        if (本次序号 !== 请求序号 || 发起切段 !== 切段代数) {
            if (槽序.some(槽 => 新增[槽].length)) toast("节点、当前段或更新的任务已变化，上传结果未应用，请重新上传");
            return;
        }
        提交(快照, {
            图片: [...素材.图片, ...新增.图片],
            音频: [...素材.音频, ...新增.音频],
            视频: [...素材.视频, ...新增.视频],
        });
    }

    function 提交(快照, 候选 = 素材) {
        const 副本 = { 图片: [...候选.图片], 音频: [...候选.音频], 视频: [...候选.视频] };
        // 异步上传和清理确认均携带发起快照；拒绝时不得把候选写入显示缓存。
        if (变更?.(副本, 快照) === false) {
            toast("节点或时间轴已变化，本次修改未应用，请重试");
            return false;
        }
        素材 = 副本;
        渲染();
        return true;
    }

    function 设值(v) {
        // 归一化：容忍 v 为 null / 缺字段 / 字段为 null（防御 widget 外部手写脏值），
        // 三槽恒定用新数组承接，避免 spread 顶层把 null 直塞进来后 .length / .includes 抛。
        // 切段代数 先 ++ 后重写 素材：任何在 await 期间发生的 回填（换节点/换段/全刷/重绑）都会作废在飞上传。
        切段代数++;
        const s = v || {};
        素材 = { 图片: [...(s.图片 || [])], 音频: [...(s.音频 || [])], 视频: [...(s.视频 || [])] };
        渲染();
    }

    渲染();
    return {
        设值, 取值: () => ({ ...素材 }),
        设共用: (v) => { 共用 = !!v; 更新共用钮(); },
        设共用可见: (v) => { 共用可见 = !!v; if (共用头) 共用头.style.visibility = 共用可见 ? "visible" : "hidden"; },
        盒,   // 盒：供状态栏面板按任务类型联动显隐
    };
}
