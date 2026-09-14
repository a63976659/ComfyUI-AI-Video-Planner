import { 真源, 取widget } from "./桥接/节点桥.js";
import { 创建状态桥 } from "./桥接/状态桥.js";
import { 创建生成类型选择, 任务码, 默认任务标签 } from "./生成类型选择.js";
import { 创建提示词编辑器, 默认分辨率, 默认百万像素 } from "./提示词编辑器.js";
import { 创建参考文件区 } from "./参考文件区.js";

const 样式已注入 = { v: false };
const 节点显示名 = "H3导演台";
const 编辑后缀 = "（正在编辑）";
const 剥离编辑 = (t) => ((t || "").endsWith(编辑后缀) ? (t || "").slice(0, -编辑后缀.length) : (t || ""));
// 「正在编辑」标题标的加/去（均幂等）：加=剥离后重拼、去=剥离还原；保留用户自定义标题。
const 加编辑标 = (n) => { if (n) n.title = (剥离编辑(n.title) || 节点显示名) + 编辑后缀; };
const 去编辑标 = (n) => { if (n) n.title = 剥离编辑(n.title) || 节点显示名; };
function 注入样式() {
    if (样式已注入.v) return;
    const s = document.createElement("style");
    s.textContent = `
      .h3dyt-状态栏{display:flex;flex-direction:column;font:12px system-ui;color:#ddd}
      .h3dyt-把手{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:4px 12px;cursor:pointer;user-select:none;background:#2b2b2b;border-radius:12px}
      .h3dyt-主体{display:none;gap:10px;padding:8px;background:#232323;border-top:1px solid #3a3a3a;height:240px;overflow:auto}
      .h3dyt-主体.展开{display:flex;flex-wrap:nowrap;align-items:stretch}
      .h3dyt-类型选择{display:flex;flex-direction:column;gap:6px;align-items:stretch}
      .h3dyt-胶囊{padding:3px 10px;border:1px solid #444;border-radius:12px;background:#2f2f2f;color:#ccc;cursor:pointer}
      .h3dyt-胶囊.激活{background:#4a9eff;color:#fff;border-color:#4a9eff}
      .h3dyt-提示词{flex:1 1 200px;min-width:170px;display:flex;flex-direction:column}
      .h3dyt-编辑区{flex:1;min-height:52px;overflow-y:auto;padding:6px 8px;background:#1c1c1c;border:1px solid #3a3a3a;border-radius:6px;white-space:pre-wrap}
      .h3dyt-工具行{display:flex;flex-wrap:wrap;gap:6px;flex:0 0 auto;margin-bottom:4px}
      .h3dyt-说明行{flex:0 0 auto;margin-top:4px;color:#8c8c8c;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .h3dyt-chip{display:inline-block;margin:0 2px;padding:0 6px;background:#3a5f8a;border-radius:8px;color:#cfe6ff}
      .h3dyt-缩略{position:relative;display:inline-flex;width:66px;height:66px;margin:0;border:1px solid #3a3a3a;border-radius:6px;overflow:hidden;background:#1a1a1a;vertical-align:middle}
      .h3dyt-缩略媒{width:100%;height:100%;object-fit:cover;display:block;pointer-events:none}
      .h3dyt-音标{width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:33px;color:#9ec1e8;background:#1f2a33}
      .h3dyt-缩略 b{position:absolute;right:1px;top:1px;padding:0 3px;font-size:10px;line-height:14px;color:#fff;background:rgba(0,0,0,.6);border-radius:4px;cursor:pointer}
      /* 参考区/右列均内容宽、组间 10px 紧凑排布；多余宽度全归中间提示词区（flex:1 独占） */
      .h3dyt-参考{flex:0 0 auto;display:flex;gap:10px;align-items:flex-start;overflow:auto}
      .h3dyt-参考组{display:flex;flex-direction:column;gap:4px}
      .h3dyt-参考头{display:flex;align-items:center;gap:4px;opacity:.9}
      .h3dyt-九宫{display:grid;grid-template-columns:repeat(3,66px);gap:4px}
      .h3dyt-竖列{display:flex;flex-direction:column;gap:4px;align-items:flex-start}
      .h3dyt-右列{display:flex;flex-direction:row;gap:10px;align-items:flex-start;flex:0 0 auto;overflow:auto}
      /* 首尾帧水平双列：文字标在上、下拉在下、选图后预览缩略图垫底 */
      .h3dyt-首尾帧{display:flex;flex-direction:row;gap:10px;flex:0 0 auto;align-items:flex-start}
      .h3dyt-帧框{display:flex;flex-direction:column;gap:4px;flex:0 0 auto}
      .h3dyt-帧标{color:#ccc}
      .h3dyt-帧选{width:170px;background:#1c1c1c;color:#ddd;border:1px solid #444;border-radius:3px;padding:2px 4px;font:12px system-ui}
      .h3dyt-帧预览{width:66px;height:66px;object-fit:cover;display:block;border:1px solid #3a3a3a;border-radius:6px;background:#1a1a1a}
      .h3dyt-帧预览[hidden]{display:none}
      .h3dyt-弹层{position:fixed;z-index:9999;max-height:200px;overflow:auto;background:#262626;border:1px solid #444;border-radius:6px}
      .h3dyt-弹层 div{padding:4px 10px;cursor:pointer}
      .h3dyt-弹层 div:hover{background:#3a5f8a}
      .h3dyt-状态{color:#8c8c8c;flex:0 0 auto}`;
    document.head.appendChild(s);
    样式已注入.v = true;
}

export function 创建状态栏面板(底栏) {
    注入样式();
    const 根 = document.createElement("div");
    根.className = "h3dyt-状态栏";

    const 把手 = document.createElement("div");
    把手.className = "h3dyt-把手";
    const 标题 = document.createElement("span");
    标题.className = "h3dyt-标题";
    标题.textContent = "🎬 导演台（展开）";
    const 状态条 = document.createElement("span");
    状态条.className = "h3dyt-状态";
    状态条.textContent = "";
    把手.append(标题, 状态条);

    const 主体 = document.createElement("div");
    主体.className = "h3dyt-主体";

    根.append(把手, 主体);
    底栏.appendChild(根);

    const 状态 = 创建状态桥({ 展开: false, 选中段: 0 });
    let 当前节点 = null;
    let 时间轴刷卡 = null;   // 时间轴挂载时注册；状态栏编辑段内容后回调它，局部刷新对应段卡

    // 布局：左=参考文件区（四组按宽度分配铺满），中=提示词编辑区（撑满状态栏高度），
    // 右列=任务类型竖排+首尾帧（水平双列、选图后带预览）。
    const 参考区 = 创建参考文件区(主体, {
        变更: (素材) => { if (当前节点) 真源.写参考素材(当前节点, 素材); 提示词.刷新弹层?.(); 刷新首尾帧选项(); },
        // 「全段共用」开关 → 节点隐藏 widget「参考共用」（布尔）；执行核心 _应用全局 据此覆盖段级 refs
        共用变更: (v) => { if (当前节点) 真源.写参考共用(当前节点, v); },
    });
    const 提示词 = 创建提示词编辑器(主体, {
        变更: (文本) => 写当前段提示词(文本),
        取参考列表: () => (当前节点 ? 真源.读参考素材(当前节点) : { 图片: [], 音频: [], 视频: [] }),
        分辨率变更: (v) => { if (当前节点) 真源.写输出分辨率(当前节点, v); },
        百万像素变更: (v) => { if (当前节点 && Number.isFinite(v)) 真源.写百万像素(当前节点, v); },
        // 画风/预设 两个下拉拼出的全局前缀 → 写回节点「全局提示词」（节点上已隐藏）
        全局提示词变更: (文本) => { if (当前节点) 真源.写全局提示词(当前节点, 文本); },
    });
    const 右列 = document.createElement("div");
    右列.className = "h3dyt-右列";
    主体.appendChild(右列);
    const 类型选择 = 创建生成类型选择(右列, {
        变更: (标签) => { if (当前节点) 真源.写任务类型(当前节点, 标签); 刷新显隐(标签); },
    });

    // 首尾帧区（即梦式）：从全局参考图片中为「当前选中段」挑首/尾帧，写入段 refs.首帧/尾帧。
    // i2v/fl2v 显示首帧下拉，fl2v 加显尾帧下拉（执行核心 _生成段 读 refs.首帧/尾帧）。
    const 首尾帧区 = document.createElement("div");
    首尾帧区.className = "h3dyt-首尾帧";
    右列.appendChild(首尾帧区);
    const 首帧框 = 建帧下拉("首帧", (名) => 写当前段帧("首帧", 名));
    const 尾帧框 = 建帧下拉("尾帧", (名) => 写当前段帧("尾帧", 名));
    首尾帧区.append(首帧框.盒, 尾帧框.盒);

    function 建帧下拉(名, 变更) {
        // 竖向三段：文字标在上、下拉在其下、选图后预览缩略图垫底（与参考缩略图同 66px）。
        const 盒 = document.createElement("div");
        盒.className = "h3dyt-帧框";
        const 标 = document.createElement("span");
        标.className = "h3dyt-帧标";
        标.textContent = 名;
        const sel = document.createElement("select");
        sel.className = "h3dyt-帧选";
        const 预览 = document.createElement("img");
        预览.className = "h3dyt-帧预览";
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
            框.预览.src = "/h3dyt/media/file?name=" + encodeURIComponent(名);
            框.预览.title = 名;
            框.预览.hidden = false;
        } else {
            框.预览.hidden = true;
            框.预览.removeAttribute("src");
            框.预览.title = "";
        }
    }

    function 刷新首尾帧选项() {
        const 图片 = 当前节点 ? (真源.读参考素材(当前节点).图片 || []) : [];
        for (const 框 of [首帧框, 尾帧框]) {
            const 旧 = 框.sel.value;
            框.sel.innerHTML = "";
            const 空 = document.createElement("option");
            空.value = ""; 空.textContent = "（无）";
            框.sel.appendChild(空);
            图片.forEach((名) => {
                const o = document.createElement("option");
                o.value = 名; o.textContent = 名;
                框.sel.appendChild(o);
            });
            框.sel.value = 图片.includes(旧) ? 旧 : "";
            刷新帧预览(框);
        }
    }

    function 写当前段帧(键, 名) {
        if (!当前节点) return;
        const tl = 真源.读时间轴(当前节点);
        const 段组 = tl.segments || [];
        const i = 状态.取("选中段");
        if (!段组[i]) return;
        const refs = { ...(段组[i].refs || {}) };
        if (名) refs[键] = 名; else delete refs[键];
        段组[i].refs = refs;
        真源.写时间轴(当前节点, { segments: 段组 });
        时间轴刷卡?.(i);   // 通知时间轴局部刷新该段卡的首帧缩略图
    }

    function 刷新显隐(标签) {
        const 码 = 任务码(标签 ?? (当前节点 ? 真源.读任务类型(当前节点) : ""));
        // 用 visibility 占位隐藏（而非 display:none 移除布局）：切换任务类型时左区/右列
        // 始终占位，提示词输入框宽度与任务类型按钮位置恒定不动。
        首尾帧区.style.visibility = (码 === "i2v" || 码 === "fl2v") ? "visible" : "hidden";
        尾帧框.盒.style.visibility = (码 === "fl2v") ? "visible" : "hidden";
        // 参考区仅 t2v 隐藏（纯文生无需参考）；i2v/fl2v 也要显示——上传首/尾帧候选图
        参考区.盒.style.visibility = (码 === "t2v") ? "hidden" : "visible";
        // 「全段共用」开关只在 参考生视频家族(r2v/v2v/rv2v) 显示：这几类每段吃全局参考池，
        // 开启即全段统一用左侧素材、只编辑提示词；i2v/fl2v 走段级首尾帧、t2v 无参考，均无需。
        参考区.设共用可见(码 === "r2v" || 码 === "v2v" || 码 === "rv2v");
    }

    function 写当前段提示词(文本) {
        if (!当前节点) return;
        const tl = 真源.读时间轴(当前节点);
        const 段组 = tl.segments || [];
        const i = 状态.取("选中段");
        if (!段组[i]) 段组[i] = { task: 任务码(真源.读任务类型(当前节点)), prompt: "", start: i * 5, end: i * 5 + 5, run: true };
        段组[i].prompt = 文本;
        真源.写时间轴(当前节点, { segments: 段组 });
        时间轴刷卡?.(i);   // 通知时间轴局部刷新该段卡的提示词预览
    }

    function 绑定节点(node) {
        if (当前节点 && 当前节点 !== node) 去编辑标(当前节点);
        当前节点 = node;
        // 「正在编辑」跟随展开态、且只标当前所选节点：展开才加标，折叠不加；
        // 多节点时其余节点一律无标（切换时已剥旧标），保证同时最多一个「正在编辑」。
        if (状态.取("展开")) 加编辑标(node); else 去编辑标(node);
        回填();
    }

    function 回填() {
        // 无绑定节点时也渲染默认（t2v）界面，使「未加节点展开」与「加节点并绑定后」外观一致：
        // 六个任务胶囊（t2v 高亮）+ 空素材/空提示词 + 按 t2v 联动显隐（参考区/首尾帧隐藏）。
        const 选项 = 当前节点 ? (取widget(当前节点, "任务类型")?.options?.values || []) : 默认任务标签;
        类型选择.设选项(选项);
        类型选择.设值(当前节点 ? 真源.读任务类型(当前节点) : 默认任务标签[0]);
        const tl = 当前节点 ? 真源.读时间轴(当前节点) : { segments: [] };
        const seg = (tl.segments || [])[状态.取("选中段")] || {};
        提示词.设值(seg.prompt || "");
        提示词.设分辨率(当前节点 ? 真源.读输出分辨率(当前节点) : 默认分辨率);
        提示词.设百万像素(当前节点 ? 真源.读百万像素(当前节点) : 默认百万像素);
        提示词.设全局提示词(当前节点 ? 真源.读全局提示词(当前节点) : "");
        参考区.设值(当前节点 ? 真源.读参考素材(当前节点) : { 图片: [], 音频: [], 视频: [] });
        参考区.设共用(当前节点 ? 真源.读参考共用(当前节点) : false);
        刷新首尾帧选项();
        首帧框.sel.value = seg.refs?.首帧 || "";
        尾帧框.sel.value = seg.refs?.尾帧 || "";
        刷新帧预览(首帧框); 刷新帧预览(尾帧框);
        刷新显隐();
    }

    function 展开() {
        状态.设("展开", true); 主体.classList.add("展开"); 标题.textContent = "🎬 导演台（收起）";
        加编辑标(当前节点);   // 展开 → 当前所选节点标题显示「正在编辑」（无绑定节点时 no-op）
        // 重拉画风/预设清单：用户可能在上次展开后往 预设/ 里新增了 txt。
        // 异步响应回来时会按回填设好的上次文本重新反解析，不会错选。
        提示词.刷新画风预设();
        回填();
    }
    function 收起() { 状态.设("展开", false); 主体.classList.remove("展开"); 标题.textContent = "🎬 导演台（展开）"; 去编辑标(当前节点); }
    把手.onclick = () => (状态.取("展开") ? 收起() : 展开());

    function 设进度(v, m) { if (v != null && m) 状态条.textContent = `生成中 ${v}/${m}`; }
    function 设状态(文本) { 状态条.textContent = 文本; }

    // 供时间轴面板联动选中段
    状态.订阅((键) => { if (键 === "选中段") 回填(); });

    return {
        绑定节点, 展开, 收起, 设进度, 设状态, 回填, 状态, 取节点: () => 当前节点,
        设时间轴刷卡: (fn) => { 时间轴刷卡 = fn; },
    };
}
