import { 真源, 取widget, 捕获节点快照, 提交节点快照, 解析段素材 } from "./桥接/节点桥.js";
import { 创建生成类型选择, 任务码, 默认任务标签 } from "./生成类型选择.js";
import { 创建提示词编辑器, 默认分辨率, 默认百万像素 } from "./提示词编辑器.js";
import { 创建参考文件区 } from "./参考文件区.js";

// 编辑页（Tab「提示词编辑」）专属样式：左=参考区、中=提示词、右列=任务胶囊+首尾帧。
// ⚠️ `.lvp-胶囊` / `.lvp-胶囊.激活` 是**跨页共用基元**（参考区/生成类型选择/提示词工具行/计划数据/
// 规划页生成钮 五处都在用），定义在 状态栏面板.js 的框架样式块里，本文件不重复定义——框架样式
// 必然先于本文件注入（创建状态栏面板 首行即注入），层叠顺序与拆分前一致。
const 样式已注入 = { v: false };
function 注入样式() {
    if (样式已注入.v) return;
    const s = document.createElement("style");
    s.textContent = `
      .lvp-类型选择{display:flex;flex-direction:column;gap:4px;align-items:stretch}
      .lvp-提示词{flex:1 1 200px;min-width:170px;display:flex;flex-direction:column}
      .lvp-编辑区{flex:1;min-height:44px;overflow-y:auto;padding:4px 6px;background:var(--comfy-input-bg,#1c1c1c);border:1px solid var(--border-color,#3a3a3a);border-radius:6px;white-space:pre-wrap}
      .lvp-工具行{display:flex;gap:4px;flex:0 0 auto;min-width:0;overflow-x:auto;margin-bottom:3px}
      /* white-space:nowrap 不可省：标签文字是 label 的匿名 flex 项，默认 flex-shrink:1 且
         min-width:auto＝最小内容宽（中文可逐字断行 → 1 个字），行内被压缩时「百万像素」会断成两排。
         nowrap 让这段文字的最小宽＝整词宽，标签随之压不动，只能走本行的横向滚动。 */
      .lvp-工具行>*{flex-shrink:0;white-space:nowrap}
      .lvp-说明行{flex:0 0 auto;margin-top:3px;color:var(--p-text-muted-color,#8c8c8c);font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .lvp-chip{display:inline-block;margin:0 2px;padding:0 6px;background:#3a5f8a;border-radius:8px;color:#cfe6ff}
      /* 装饰 chip：仅前端可读性标记（subject_definitions:/[Shot N] 等），不引用素材、不可点击；
         换暖色调以与蓝色引用 chip 目视区分。选择器重叠 .lvp-chip 确保覆盖背景/文字色。 */
      .lvp-chip.lvp-chip-deco{background:#5a5145;color:#f0e0c8}
      /* 缩略块整块可点＝打开 媒体预览.js 弹窗（图像放大/视频音频播放），故 cursor:pointer 放在块级而非媒图上
         （.lvp-缩略媒 保持 pointer-events:none，点击落点始终是瓦片本身）。 */
      .lvp-缩略{position:relative;display:inline-flex;width:66px;height:66px;margin:0;border:1px solid var(--border-color,#3a3a3a);border-radius:6px;overflow:hidden;background:var(--comfy-input-bg,#1a1a1a);vertical-align:middle;cursor:pointer}
      .lvp-缩略媒{width:100%;height:100%;object-fit:cover;display:block;pointer-events:none}
      /* 音频占位＝与 规划素材区 同一套观感（用户 2026-09-30 裁定「两墙统一」）：♪ 是文本字形、吃 color，
         取绿色 token；底衬不再自铺蓝调，直接继承 .lvp-缩略 的 --comfy-input-bg，别只改字色留半块蓝底。 */
      .lvp-音标{width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:33px;color:var(--p-green-400,#7ee0a3)}
      .lvp-缩略 b{position:absolute;right:1px;top:1px;padding:0 3px;font-size:10px;line-height:14px;color:#fff;background:rgba(0,0,0,.6);border-radius:4px;cursor:pointer}
      /* 参考区/右列均内容宽、组间 8px 紧凑排布；多余宽度全归中间提示词区（flex:1 独占）。
   素材框左右内距 8px＝原 4px＋约 7px 滚动条预留位对称合并取整（2026-09-24 用户订正「框内间距有问题」：
   原 scrollbar-gutter:stable 只在右侧留位，内容整体偏左、左右内距 5/12px 不对称）；
   滚动条隐藏但 overflow:auto 保留，滚轮/触控板仍可框内滚动，框宽 83/223 不变、左右列 493/492 齐平不受影响 */
      .lvp-参考{flex:0 0 auto;display:flex;gap:8px;align-items:flex-start;overflow:auto}
      .lvp-参考组{display:flex;flex-direction:column;gap:4px}
      .lvp-参考头{display:flex;align-items:center;gap:4px;opacity:.9}
      .lvp-素材组{flex:0 0 auto}
      .lvp-素材组>.lvp-参考头{justify-content:center;min-height:20px;white-space:nowrap}
      .lvp-素材框{display:grid;grid-template-columns:66px;grid-template-rows:repeat(3,66px);grid-auto-rows:66px;box-sizing:content-box;width:max-content;height:206px;overflow:auto;scrollbar-width:none;gap:4px;padding:4px 8px;border:1px solid var(--border-color,#3a3a3a);border-radius:6px;background:var(--comfy-menu-bg,#2b2b2b);flex:0 0 auto}
      .lvp-素材框::-webkit-scrollbar{width:0;height:0}
      .lvp-素材框.lvp-九宫{grid-template-columns:repeat(3,66px)}
      .lvp-素材框>.lvp-缩略{box-sizing:border-box}
      .lvp-素材框>.lvp-素材添加{align-items:center;justify-content:center;padding:0;appearance:none;color:var(--p-primary-color,#4a9eff);font:32px/1 system-ui;cursor:pointer}
      .lvp-素材框>.lvp-素材添加:hover{border-color:var(--p-primary-color,#4a9eff)}
      .lvp-素材框>.lvp-素材添加:focus-visible{outline:2px solid var(--p-primary-color,#4a9eff);outline-offset:1px}
      .lvp-右列{display:flex;flex-direction:row;gap:8px;align-items:flex-start;flex:0 0 auto;overflow:auto}
      /* 首尾帧水平双列：文字标在上、下拉在下、选图后预览缩略图垫底。
         框宽 120px＝右列总宽与左列参考区（493px）齐平的口径：类型选择108＋间隙8＋3框×120＋框间2×8＝492，
         改动帧框宽度会破坏左右对齐（浏览器实测，2026-09-24）。 */
      .lvp-首尾帧{display:flex;flex-direction:row;gap:8px;flex:0 0 auto;align-items:flex-start}
      .lvp-帧框{display:flex;flex-direction:column;gap:3px;flex:0 0 auto}
      .lvp-帧标{color:var(--fg-color,#ccc)}
      .lvp-帧选,.lvp-比例选{width:120px;background:var(--comfy-input-bg,#1c1c1c);color:var(--fg-color,#ddd);border:1px solid var(--border-color,#444);border-radius:3px;padding:2px 4px;font:11px system-ui}
      .lvp-帧预览{width:120px;height:120px;box-sizing:border-box;object-fit:cover;display:block;border:1px solid var(--border-color,#3a3a3a);border-radius:6px;background:var(--comfy-input-bg,#1a1a1a)}
      .lvp-帧预览[hidden]{display:none}
      .lvp-中间帧位置{display:block;box-sizing:border-box;width:120px;margin-top:3px;background:var(--comfy-input-bg,#1c1c1c);color:var(--fg-color,#ddd);border:1px solid var(--border-color,#444);border-radius:3px;padding:2px 4px;font:11px system-ui}
      .lvp-中间帧位置:invalid{border-color:var(--p-red-400,#e07070)}
      .lvp-弹层{position:fixed;z-index:9999;max-height:200px;overflow:auto;background:var(--comfy-menu-secondary-bg,#262626);border:1px solid var(--border-color,#444);border-radius:6px}
      .lvp-弹层 div{padding:4px 10px;cursor:pointer}
      .lvp-弹层 div:hover{background:#3a5f8a}`;
    document.head.appendChild(s);
    样式已注入.v = true;
}

// 上下文（由 状态栏面板.js 注入，均为延迟求值的 getter/回调，避免与框架层形成循环依赖）：
//   取节点()      → 当前绑定节点（未绑定为 null；⚠️ 每次用都要重新取，不得缓存）
//   状态          → 状态桥（读「选中段」）
//   刷卡(i)       → 时间轴局部刷新第 i 段卡
//   渲染时间轴()  → 时间轴整树重建
//   计划已加载/取规划编辑状态 → 透传计划组件的恢复与覆盖保护
//   应用规划(segments) → 框架层公共动作（覆盖确认 → 写时间轴 → 全刷）
export function 创建编辑页面板(编辑页, 上下文) {
    注入样式();
    const { 取节点, 状态, 刷卡, 渲染时间轴, 计划已加载, 取规划编辑状态, 应用规划 } = 上下文;

    // ---- 段级素材读写辅助 ----
    // 编辑本段的图片/音频/视频候选：缺键逐槽补全局，不套用其他段的共用覆盖。
    // 共用后的生效素材只用于时间轴显示；此处保持本段编辑所有权。
    // 段组 可选：回填路径由框架层把已读的 segments 传下来复用（省一次 读时间轴）；
    // 交互路径（参考区变更 / @ 弹层取参考列表）**必须**无参调用 → 自己重读，才能拿到刚写入的新值。
    function 读当前段素材(段组) {
        const 节点 = 取节点();
        if (!节点) return { 图片: [], 音频: [], 视频: [] };
        const seg = (段组 || 真源.读时间轴(节点).segments || [])[状态.取("选中段")];
        return 解析段素材(seg?.refs, 真源.读参考素材(节点));
    }
    function 写段素材(节点, 素材) {
        if (!节点) return;
        const tl = 真源.读时间轴(节点);
        const 段组 = tl.segments || [];
        const i = 状态.取("选中段");
        if (!段组[i]) 段组[i] = { task: 任务码(真源.读任务类型(节点)), prompt: "", start: i * 5, end: i * 5 + 5, run: true };
        const 原refs = 段组[i].refs || {};
        // 改写**前**先留一份本段的首尾帧候选列表：复用 读当前段素材（同一口径，含段级/全局回退与
        // 素材名列表 显示转换），不在此重写判断——写回后原列表已被覆盖，无从得知这次删掉了哪张。
        const 旧候选 = 读当前段素材(段组).图片;
        const refs = { ...原refs };
        refs.图片 = 素材.图片 || [];
        refs.音频 = 素材.音频 || [];
        refs.视频 = 素材.视频 || [];
        // 参考区点 ×「取消引用图」只改候选列表、不经 写当前段帧 → 若这张图正被 refs.首帧/尾帧 引用，引用就与列表脱节：
        // 下拉被 刷新首尾帧选项 显示成「（无）」，数据却仍指着这张已不属于本段的图，段卡（图名Of 只认 refs.首帧）
        // 照旧把它画出来。⚠️ 危害不止“显示不一致”：媒体路由无删除接口，× 只把名字移出列表、**文件仍在盘上**，
        // 故后端 _采样段 仍会把 refs.首帧 那张图当首帧用——用户的“取消”对实际生成完全无效。故按「本次真正被
        // 移除的名字」同步清引用（见踩坑手册 B8）。另：判据是差集而非「不在新列表里就清」——后端消费 refs.首帧
        // 并不要求它在候选列表内（计划数据预设可只给首帧、不给图片列表），盲裁会删掉后端真正会用的图。
        const 被移除 = 旧候选.filter(名 => 名 && !refs.图片.includes(名));
        if (被移除.includes(refs.首帧)) delete refs.首帧;
        if (被移除.includes(refs.尾帧)) delete refs.尾帧;
        if (被移除.includes(refs.中间帧)) { delete refs.中间帧; delete refs.中间帧位置; }
        段组[i].refs = refs;
        真源.写时间轴(节点, { segments: 段组 });
        // 同步全局素材池，供缺键段回退及显式计划保存读取。
        真源.写参考素材(节点, 素材);
    }
    // 已有段组 可选，同 读当前段素材：回填时复用框架层已读的 segments。
    function 读当前段共用(已有段组) {
        const 节点 = 取节点();
        if (!节点) return false;
        const 段组 = 已有段组 || 真源.读时间轴(节点).segments || [];
        const seg = 段组[状态.取("选中段")];
        // 段级有明确值用段级
        if (seg?.refs?.共用 !== undefined) return !!seg.refs.共用;
        // 任一段有段级共用标记 → 新架构模式，未标记的段默认 false（不回退全局）
        if (段组.some(s => s?.refs?.共用 !== undefined)) return false;
        // 旧计划：无任何段级标记，回退全局 widget
        return 真源.读参考共用(节点);
    }
    function 写当前段共用(v) {
        const 节点 = 取节点();
        if (!节点) return;
        const tl = 真源.读时间轴(节点);
        const 段组 = tl.segments || [];
        const i = 状态.取("选中段");
        if (!段组[i]) return;
        // 互斥单选：开启某段共用时，把其他「也开启共用」的段清为 false，避免多段同时开启
        // 导致后端「第一个胜出」（执行核心._查找共用素材）与前端各段独立显示不一致。
        // 只动 refs.共用 已为 truthy 的段：未标记的段保持 undefined（最小副作用），
        // 让 读当前段共用 的中间判断（段组.some(...共用 !== undefined)）继续走「新架构模式」分支。
        if (v) {
            段组.forEach((段, j) => {
                if (j === i || !段?.refs?.共用) return;
                段.refs = { ...段.refs, 共用: false };
            });
        }
        const refs = { ...(段组[i].refs || {}) };
        refs.共用 = !!v;
        段组[i].refs = refs;
        真源.写时间轴(节点, { segments: 段组 });
        // 同步节点全局开关。
        真源.写参考共用(节点, !!v);
    }

    // 布局：左=参考文件区，中=提示词编辑区，右=任务类型及首尾帧/中间帧。
    const 参考区 = 创建参考文件区(编辑页, {
        // 上传跨 await 回写守卫：宿主提供发起时快照捕获器（删/拖 等同步动作无快照→本函数内即时捕获）；
        // 异步上传传入发起时快照 → 用 提交节点快照 复核「节点身份+时间轴版本+节点代数」，不过 → 拒绝。
        捕获快照: () => 捕获节点快照(取节点(), ["时间轴数据"]),
        变更: (素材, 快照) => {
            const 提交快照 = 快照 ?? 捕获节点快照(取节点(), ["时间轴数据"]);
            const 已提交 = 提交节点快照(提交快照, 取节点(), (目标) => 写段素材(目标, 素材));
            if (!已提交) return false;
            提示词.刷新弹层?.(); 刷新首尾帧选项(); 渲染时间轴();
            return true;
        },
        // 「全段共用」开关 → 段级 refs.共用（布尔）；执行核心据此决定是否用该段素材覆盖所有段
        共用变更: (v) => { 写当前段共用(v); 渲染时间轴(); },
    });
    const 提示词 = 创建提示词编辑器(编辑页, {
        变更: (文本) => 写当前段提示词(文本),
        取参考列表: () => 读当前段素材(),
        分辨率变更: (v) => { const 节点 = 取节点(); if (节点) 真源.写输出分辨率(节点, v); },
        百万像素变更: (v) => { const 节点 = 取节点(); if (节点 && Number.isFinite(v)) 真源.写百万像素(节点, v); },
        // 画风/预设 两个下拉拼出的全局前缀 → 写回节点「全局提示词」（节点上已隐藏）
        全局提示词变更: (文本) => { const 节点 = 取节点(); if (节点) 真源.写全局提示词(节点, 文本); },
        取节点: () => 取节点(),
        计划已加载,
        取规划编辑状态,
        应用规划: (segments) => 应用规划(segments),   // 新增（D7）
        取在途: () => !!状态.取("LLM请求在途"),   // B3：加载计划与流式生成互斥
    });
    const 右列 = document.createElement("div");
    右列.className = "lvp-右列";
    编辑页.appendChild(右列);
    const 类型选择 = 创建生成类型选择(右列, {
        变更: (标签) => { const 节点 = 取节点(); if (节点) { 真源.写任务类型(节点, 标签); 写当前段任务(标签); } 刷新显隐(标签); },
    });

    // 首尾帧区（即梦式）：从当前段参考图片中为「当前选中段」挑首/尾帧，写入段 refs.首帧/尾帧。
    // i2v/fl2v 显示首帧下拉，fl2v 加显尾帧下拉（执行核心 _生成段 读 refs.首帧/尾帧）。
    const 首尾帧区 = document.createElement("div");
    首尾帧区.className = "lvp-首尾帧";
    右列.appendChild(首尾帧区);
    const 首帧框 = 建帧下拉("首帧", (名) => 写当前段帧("首帧", 名));
    const 尾帧框 = 建帧下拉("尾帧", (名) => 写当前段帧("尾帧", 名));
    const 中间帧框 = 建帧下拉("中间帧（可选）", (名) => {
        写当前段帧("中间帧", 名);
        刷新首尾帧选项();
    });
    中间帧框.sel.setAttribute("aria-label", "中间帧（可选）");
    中间帧框.预览.alt = "中间帧预览";
    const 位置标 = document.createElement("label");
    位置标.className = "lvp-帧标";
    位置标.textContent = "段内位置（%）";
    const 位置入 = document.createElement("input");
    位置入.className = "lvp-中间帧位置";
    位置入.type = "number"; 位置入.min = "0"; 位置入.max = "100"; 位置入.step = "any";
    位置入.setAttribute("aria-label", "中间帧段内位置（%）");
    位置入.title = "大于0%且小于100%；随段长变化，实际生成取最近内部帧";
    位置标.appendChild(位置入);
    中间帧框.盒.appendChild(位置标);
    位置入.onchange = () => {
        const 百分比 = Number(位置入.value);
        const 合法 = 位置入.value.trim() !== "" && Number.isFinite(百分比) && 百分比 > 0 && 百分比 < 100;
        位置入.setCustomValidity(合法 ? "" : "中间帧位置须大于0%且小于100%");
        if (!合法) { 位置入.reportValidity?.(); return; }
        const 节点 = 取节点();
        if (!节点) return;
        const 段组 = 真源.读时间轴(节点).segments || [];
        const 段 = 段组[状态.取("选中段")];
        if (!段?.refs?.中间帧) return;
        段.refs = { ...段.refs, 中间帧位置: 百分比 / 100 };
        真源.写时间轴(节点, { segments: 段组 });
    };
    // i2v 比例模式选择（仅 i2v 可见）：原图比例 / 裁剪到设定比例。排在首帧之后、尾帧之前，
    // 紧邻首帧；隐藏态用 visibility 占位，切换任务类型时不引起横向跳动。
    const 比例模式盒 = document.createElement("div");
    比例模式盒.className = "lvp-帧框";
    const 比例模式标 = document.createElement("span");
    比例模式标.className = "lvp-帧标";
    比例模式标.textContent = "比例模式";
    const 比例模式sel = document.createElement("select");
    比例模式sel.className = "lvp-比例选";
    [["裁剪", "按设置尺寸比例裁剪生成"], ["原图", "按图像原尺寸比例生成"]].forEach(([v, t]) => {
        const o = document.createElement("option"); o.value = v; o.textContent = t;
        比例模式sel.appendChild(o);
    });
    比例模式盒.append(比例模式标, 比例模式sel);
    首尾帧区.append(首帧框.盒, 比例模式盒, 尾帧框.盒, 中间帧框.盒);
    比例模式sel.onchange = () => {
        const 节点 = 取节点();
        if (!节点) return;
        const 段组 = 真源.读时间轴(节点).segments || [];
        const i = 状态.取("选中段");
        if (!段组[i]) return;
        段组[i].i2v比例模式 = 比例模式sel.value;
        真源.写时间轴(节点, { segments: 段组 });
    };

    function 建帧下拉(名, 变更) {
        // 竖向三段：文字标在上、下拉在其下、选图后带等宽正方形预览。
        const 盒 = document.createElement("div");
        盒.className = "lvp-帧框";
        const 标 = document.createElement("span");
        标.className = "lvp-帧标";
        标.textContent = 名;
        const sel = document.createElement("select");
        sel.className = "lvp-帧选";
        const 预览 = document.createElement("img");
        预览.className = "lvp-帧预览";
        预览.hidden = true;
        盒.append(标, sel, 预览);
        const 框 = { 盒, sel, 预览 };
        sel.onchange = () => { 变更(sel.value || null); 刷新帧预览(框); };
        return 框;
    }

    // 预览图跟随下拉当前值：空值隐藏并清 src，避免残留旧图请求。
    function 刷新帧预览(框) {
        const 名 = 框.sel.value;
        if (名) {
            框.预览.src = "/lvp/media/file?name=" + encodeURIComponent(名);
            框.预览.title = 名;
            框.预览.hidden = false;
        } else {
            框.预览.hidden = true;
            框.预览.removeAttribute("src");
            框.预览.title = "";
        }
    }

    function 刷新首尾帧选项(已有段组) {
        const 段组 = 已有段组 || 真源.读时间轴(取节点()).segments || [];
        const 图片 = 读当前段素材(段组).图片;
        const refs = 段组[状态.取("选中段")]?.refs || {};
        位置入.disabled = !refs.中间帧;
        const 比例 = refs.中间帧位置 === undefined ? 0.5 : refs.中间帧位置;
        const 百分比 = 比例 * 100;
        const 简值 = Number(百分比.toFixed(9));
        位置入.value = Number.isFinite(比例) ? String(简值 > 0 && 简值 < 100 ? 简值 : 百分比) : "";
        位置入.setCustomValidity(refs.中间帧 && (!Number.isFinite(比例) || 比例 <= 0 || 比例 >= 1) ? "中间帧位置须大于0%且小于100%" : "");
        for (const [键, 框] of [["首帧", 首帧框], ["尾帧", 尾帧框], ["中间帧", 中间帧框]]) {
            const 当前 = refs[键] || "";
            // 独立预设帧不必属于图片槽：仅给对应下拉补选项，不修改候选池或节点数据。
            const 候选 = 当前 && !图片.includes(当前) ? [...图片, 当前] : 图片;
            框.sel.innerHTML = "";
            const 空 = document.createElement("option");
            空.value = ""; 空.textContent = "（无）";
            框.sel.appendChild(空);
            候选.forEach((名) => {
                const o = document.createElement("option");
                o.value = 名; o.textContent = 名;
                框.sel.appendChild(o);
            });
            框.sel.value = 当前;
            刷新帧预览(框);
        }
        const 段 = 段组[状态.取("选中段")];
        比例模式sel.value = 段?.i2v比例模式 || "裁剪";
    }

    function 写当前段帧(键, 名) {
        const 节点 = 取节点();
        if (!节点) return;
        const tl = 真源.读时间轴(节点);
        const 段组 = tl.segments || [];
        const i = 状态.取("选中段");
        if (!段组[i]) return;
        const refs = { ...(段组[i].refs || {}) };
        if (名) refs[键] = 名; else delete refs[键];
        if (键 === "中间帧") {
            if (!名) delete refs.中间帧位置;
            else if (refs.中间帧位置 === undefined) refs.中间帧位置 = 0.5;
        }
        段组[i].refs = refs;
        真源.写时间轴(节点, { segments: 段组 });
        刷卡(i);   // 通知时间轴局部刷新该段卡的首帧缩略图
    }

    function 刷新显隐(标签) {
        const 节点 = 取节点();
        const 码 = 任务码(标签 ?? (节点 ? 真源.读任务类型(节点) : ""));
        // 用 visibility 占位隐藏（而非 display:none 移除布局）：切换任务类型时左区/右列
        // 始终占位，提示词输入框宽度与任务类型按钮位置恒定不动。
        首尾帧区.style.visibility = (码 === "i2v" || 码 === "fl2v") ? "visible" : "hidden";
        尾帧框.盒.style.visibility = (码 === "fl2v") ? "visible" : "hidden";
        中间帧框.盒.style.visibility = (码 === "fl2v") ? "visible" : "hidden";
        比例模式盒.style.visibility = (码 === "i2v") ? "visible" : "hidden";
        // 参考区仅 t2v 隐藏（纯文生无需参考）；i2v/fl2v 也要显示——上传首/尾帧候选图
        参考区.盒.style.visibility = (码 === "t2v") ? "hidden" : "visible";
        // 「全段共用」开关只在 参考生视频家族(r2v/v2v/rv2v) 显示：这几类每段吃参考素材，
        // 开启即本段素材覆盖所有段、只编辑提示词；i2v/fl2v 走段级首尾帧、t2v 无参考，均无需。
        参考区.设共用可见(码 === "r2v" || 码 === "v2v" || 码 === "rv2v");
    }

    function 写当前段提示词(文本) {
        const 节点 = 取节点();
        if (!节点) return;
        const tl = 真源.读时间轴(节点);
        const 段组 = tl.segments || [];
        const i = 状态.取("选中段");
        if (!段组[i]) 段组[i] = { task: 任务码(真源.读任务类型(节点)), prompt: "", start: i * 5, end: i * 5 + 5, run: true };
        段组[i].prompt = 文本;
        真源.写时间轴(节点, { segments: 段组 });
        刷卡(i);   // 通知时间轴局部刷新该段卡的提示词预览
    }

    // 全局任务类型切换 → 同步到「当前选中段」的 task（其它段不动，避免误改
    // 用户故意保留的混合任务时间轴）。后端 _应用全局 优先用 seg.task，不同步会造成
    // 前端全局显示新任务、实际执行仍走旧 task 的难察觉的不一致。无选中段时直接返回（
    // 新增段会从全局 widget 拉当前任务码，无需预造段）。
    function 写当前段任务(标签) {
        const 节点 = 取节点();
        if (!节点) return;
        const tl = 真源.读时间轴(节点);
        const 段组 = tl.segments || [];
        const i = 状态.取("选中段");
        if (!段组[i]) return;
        const 码 = 任务码(标签);
        if (段组[i].task === 码) return;   // 同码不重写，免无谓的 widget 写入与刷卡
        段组[i].task = 码;
        真源.写时间轴(节点, { segments: 段组 });
        刷卡(i);   // 局部刷新段卡的任务徽标/title/缩略图（刷卡 已含任务字段同步）
    }

    // 回填由框架层统一驱动：节点、当前段快照 seg 与整份 段组 都由 状态栏面板.回填() 读一次后传下来，
    // 两页共用同一份快照；本函数内的素材/共用/首尾帧候选均由 段组 派生，不重复 读时间轴。
    function 回填(节点, seg, 段组) {
        // 无绑定节点时也渲染默认（t2v）界面，使「未加节点展开」与「加节点并绑定后」外观一致：
        // 六个任务胶囊（t2v 高亮）+ 空素材/空提示词 + 按 t2v 联动显隐（参考区/首尾帧隐藏）。
        const 选项 = 节点 ? (取widget(节点, "任务类型")?.options?.values || []) : 默认任务标签;
        // 切段只回填段级任务；全局默认仅在用户主动切换任务时写入。
        const 段任务 = String(seg.task ?? "").trim().toLowerCase();
        const 任务 = 节点 ? (选项.find(标签 => 任务码(标签) === 段任务) || 真源.读任务类型(节点)) : 默认任务标签[0];
        类型选择.设选项(选项);
        类型选择.设值(任务);
        提示词.设值(seg.prompt || "");
        提示词.设分辨率(节点 ? 真源.读输出分辨率(节点) : 默认分辨率);
        提示词.设百万像素(节点 ? 真源.读百万像素(节点) : 默认百万像素);
        提示词.设全局提示词(节点 ? 真源.读全局提示词(节点) : "");
        参考区.设值(读当前段素材(段组));
        参考区.设共用(读当前段共用(段组));
        刷新首尾帧选项(段组);
        刷新显隐(任务);
    }

    return {
        回填,
        // 展开时重拉：用户可能在上次展开后往 预设/ 里新增了 txt、或往 计划数据/ 里放了 JSON
        刷新画风预设: () => 提示词.刷新画风预设(),
        刷新计划列表: () => 提示词.刷新计划列表?.(),
    };
}
