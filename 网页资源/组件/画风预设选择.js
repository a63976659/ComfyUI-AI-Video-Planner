// 画风 + 预设 两个下拉 → 拼成「画风名 \n 预设正文」写回节点「全局提示词」widget。
// 「全局提示词」在节点上已隐藏（后端 extra_dict.hidden + 状态栏入口.js 的 widget.hidden 双路径），
// 真源仍是该 widget，执行链（执行核心._应用全局 把它作段 prompt 前缀）不变。
//
// 选项来自 GET /lvp/preset/options：{画风:[名], 预设:[{显示名,路径,内容}]}。
// 单一真源在后端 后端路由/预设路由.py，前端不镜像硬编码画风表。
//
// 回填靠反解析（widget 里只有拼接后的纯文本，没有选中项元数据）：
//   1) 整段正文命中某预设 → 只选预设；
//   2) 否则首行命中画风名 → 选画风，余下再整体匹配预设正文；
//   3) 都匹配不上的残余存进 余量，拼接时原样带回。
// 余量 这一路是为了不吞掉旧工作流里手写的全局提示词：反解析失败时两个下拉都显示（无），
// 但用户之后任选一项，原文本仍会跟在后面写回，不会静默丢失。

const 选项接口 = "/lvp/preset/options";
const 无 = "（无）";
const 控件样式 = "background:#1c1c1c;color:#ddd;border:1px solid #444;border-radius:3px;max-width:132px";
// 预设正文来自磁盘文件，可能是 CRLF；widget 里存的与前端比对用的统一按 LF 归一，
// 否则「写回 → 回填」这一圈会因为行尾差异匹配不上、选中项莫名跳回（无）。
const 归一 = (t) => (t ?? "").replace(/\r\n/g, "\n");

export function 创建画风预设选择(容器, { 变更 }) {
    function 建组(名, 提示) {
        const 组 = document.createElement("label");
        组.style.cssText = "display:flex;align-items:center;gap:4px";
        组.textContent = 名;
        组.title = 提示;
        const sel = document.createElement("select");
        sel.style.cssText = 控件样式;
        组.appendChild(sel);
        return { 组, sel };
    }

    const 画风框 = 建组("画风", "全局风格，写入「全局提示词」首行");
    const 预设框 = 建组("预设", "插件根 预设/ 下最高两层的 .txt，正文接在画风之后");
    容器.append(画风框.组, 预设框.组);

    let 画风列表 = [];
    let 预设列表 = [];
    let 当前画风 = "";
    let 当前预设 = "";
    let 余量 = "";
    let 上次文本 = "";

    function 预设正文(路径) {
        const p = 预设列表.find((x) => x.路径 === 路径);
        return p ? 归一(p.内容) : "";
    }

    function 拼接() {
        return [当前画风, 预设正文(当前预设), 余量]
            .filter((s) => s && s.trim())
            .join("\n");
    }

    // 只有用户主动改动下拉才写回 widget；刷新选项/回填只更新 UI，不触发写入。
    function 应用() { 上次文本 = 拼接(); 变更?.(上次文本); }

    function 命中预设(文本) {
        if (!文本 || !文本.trim()) return "";
        return 预设列表.find((p) => 归一(p.内容) === 文本)?.路径 || "";
    }

    function 解析(文本) {
        const s = 归一(文本);
        const 整段 = 命中预设(s);
        if (整段) return { 画风: "", 预设: 整段, 余量: "" };

        const i = s.indexOf("\n");
        const 首行 = i < 0 ? s : s.slice(0, i);
        const 尾 = i < 0 ? "" : s.slice(i + 1);
        if (!画风列表.includes(首行)) return { 画风: "", 预设: "", 余量: s };

        const 尾预设 = 命中预设(尾);
        if (尾预设) return { 画风: 首行, 预设: 尾预设, 余量: "" };
        return { 画风: 首行, 预设: "", 余量: 尾 };
    }

    function 建空项() {
        const o = document.createElement("option");
        o.value = ""; o.textContent = 无;
        return o;
    }

    function 建项(值, 标签) {
        const o = document.createElement("option");
        o.value = 值; o.textContent = 标签;
        return o;
    }

    // 用 replaceChildren + textContent 重建选项（不走 innerHTML）：预设显示名来自磁盘文件名，
    // 当作纯文本插入，不给文件名里出现 < > 时变成标记的机会。
    function 刷新选项UI() {
        画风框.sel.replaceChildren(建空项(), ...画风列表.map((名) => 建项(名, 名)));
        画风框.sel.value = 画风列表.includes(当前画风) ? 当前画风 : "";
        当前画风 = 画风框.sel.value;

        预设框.sel.replaceChildren(建空项(), ...预设列表.map((p) => 建项(p.路径, p.显示名)));
        预设框.sel.value = 预设列表.some((p) => p.路径 === 当前预设) ? 当前预设 : "";
        当前预设 = 预设框.sel.value;
    }

    function 设值(文本) {
        上次文本 = 归一(文本);
        const r = 解析(上次文本);
        当前画风 = r.画风; 当前预设 = r.预设; 余量 = r.余量;
        刷新选项UI();
    }

    async function 刷新选项() {
        let data;
        try {
            const res = await fetch(选项接口);
            data = await res.json();
            if (!res.ok) throw new Error(data?.error || `HTTP ${res.status}`);
        } catch (e) {
            // 拉取失败保留已有清单（不清空），只留控制台痕迹：画风/预设缺失不该淹没整个状态栏
            console.warn("[长视频规划师] 画风/预设选项拉取失败：", e);
            return;
        }
        画风列表 = Array.isArray(data?.画风) ? data.画风 : [];
        预设列表 = Array.isArray(data?.预设) ? data.预设 : [];
        设值(上次文本);   // 清单到位后按上次文本重新反解析（首次回填可能早于本次响应）
    }

    画风框.sel.onchange = () => { 当前画风 = 画风框.sel.value; 应用(); };
    预设框.sel.onchange = () => { 当前预设 = 预设框.sel.value; 应用(); };

    刷新选项UI();   // 先渲染出两个只有「（无）」的下拉，避免清单响应前是空白控件
    刷新选项();

    return { 设值, 刷新选项, 取值: () => 上次文本 };
}
