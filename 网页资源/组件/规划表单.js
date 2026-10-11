// brief 表单模态：拉 /lvp/plan_meta 填枚举 → POST /lvp/plan → on规划完成(segments)。
// 零构建原生 ES 模块；配色一律 var(--comfy-*/--p-*, 兜底)（主题跟随护栏）。设计：§8.2 + §13。
import { app } from "../../../scripts/app.js";

const 样式已注入 = { v: false };
function 注入样式() {
    if (样式已注入.v) return;
    const s = document.createElement("style");
    s.textContent = `
      .lvp-pf-遮罩{position:fixed;inset:0;z-index:10000;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.5)}
      .lvp-pf-模态{width:min(480px,92vw);max-height:88vh;overflow:auto;display:flex;flex-direction:column;gap:10px;padding:16px;background:var(--comfy-menu-secondary-bg,#232323);border:1px solid var(--border-color,#3a3a3a);border-radius:10px;color:var(--fg-color,#ddd);font:13px system-ui}
      .lvp-pf-题{font-size:15px;font-weight:600;color:var(--fg-color,#eee)}
      .lvp-pf-行{display:flex;flex-direction:column;gap:4px}
      .lvp-pf-标{color:var(--p-text-muted-color,#9aa0a8);font-size:12px}
      .lvp-pf-入,.lvp-pf-选{padding:5px 8px;background:var(--comfy-input-bg,#1c1c1c);color:var(--fg-color,#ddd);border:1px solid var(--border-color,#444);border-radius:5px;font:13px system-ui}
      .lvp-pf-双{display:flex;gap:10px}.lvp-pf-双>.lvp-pf-行{flex:1}
      .lvp-pf-脚{display:flex;justify-content:flex-end;gap:8px;margin-top:4px}
      .lvp-pf-钮{padding:6px 14px;border-radius:6px;border:1px solid var(--border-color,#444);background:var(--comfy-input-bg,#2f2f2f);color:var(--fg-color,#ccc);cursor:pointer}
      .lvp-pf-钮.主{background:var(--p-primary-color,#4a9eff);color:var(--p-primary-contrast-color,#fff);border-color:var(--p-primary-color,#4a9eff)}
      .lvp-pf-钮:disabled{opacity:.5;cursor:not-allowed}
      .lvp-pf-错{color:var(--p-error-color,#ff6b6b);font-size:12px;min-height:16px}`;
    document.head.appendChild(s);
    样式已注入.v = true;
}

function toast(消息, severity = "info") { app?.ui?.toast?.showMessage?.({ message: 消息, severity }); }

async function 取JSON(url, 选项) {
    const resp = await fetch(url, 选项);
    const 数据 = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(数据.error || `请求失败（${resp.status}）`);
    return 数据;
}

export function 打开规划表单({ on规划完成 }) {
    注入样式();
    const 遮罩 = document.createElement("div"); 遮罩.className = "lvp-pf-遮罩";
    const 模态 = document.createElement("div"); 模态.className = "lvp-pf-模态";
    遮罩.appendChild(模态);
    const 关闭 = () => 遮罩.remove();
    遮罩.onclick = (e) => { if (e.target === 遮罩) 关闭(); };   // 点遮罩空白关闭

    const 题 = document.createElement("div"); 题.className = "lvp-pf-题"; 题.textContent = "AI 规划 · 分镜简报";
    模态.appendChild(题);

    const 字段 = {};
    const 语 = ["中文", "English", "日本語"];
    function 行(父) { const d = document.createElement("div"); d.className = "lvp-pf-行"; (父 || 模态).appendChild(d); return d; }
    function 标(父, 文) { const l = document.createElement("label"); l.className = "lvp-pf-标"; l.textContent = 文; 父.appendChild(l); return l; }
    function 文本(键, 标签, 占位, 值 = "") {
        const d = 行(); 标(d, 标签);
        const el = document.createElement("input"); el.className = "lvp-pf-入"; el.type = "text"; el.placeholder = 占位; el.value = 值;
        d.appendChild(el); 字段[键] = el; return el;
    }
    function 填下拉(el, 选项, 默认) {
        el.innerHTML = "";
        (选项 || []).forEach((o) => { const op = document.createElement("option"); op.value = o; op.textContent = o; el.appendChild(op); });
        if (默认 != null && (选项 || []).includes(默认)) el.value = 默认;
    }
    function 双列(左, 右) { const w = document.createElement("div"); w.className = "lvp-pf-双"; w.append(左, 右); 模态.appendChild(w); }

    // 主题（必填，全宽）
    文本("主题", "主题 *", "例如：3 分钟看懂手冲咖啡");
    // 总时长 + 段数上限（双列；段数上限 0=自动，后端校验归一据总时长推算）
    const 时长行 = 行(); 标(时长行, "总时长（秒）");
    const 时长 = document.createElement("input"); 时长.className = "lvp-pf-入"; 时长.type = "number"; 时长.value = 30; 时长.min = 1; 时长.max = 3600;
    时长行.appendChild(时长); 字段.总时长 = 时长;
    const 限行 = 行(); 标(限行, "段数上限（0=自动）");
    const 限 = document.createElement("input"); 限.className = "lvp-pf-入"; 限.type = "number"; 限.value = 0; 限.min = 0; 限.max = 60;
    限行.appendChild(限); 字段.段数上限 = 限;
    双列(时长行, 限行);
    // 平台 + 默认任务（枚举待 meta 回填）
    const 平台行 = 行(); 标(平台行, "平台");
    const 平台 = document.createElement("select"); 平台.className = "lvp-pf-选"; 平台行.appendChild(平台); 字段.平台 = 平台;
    const 任务行 = 行(); 标(任务行, "默认任务");
    const 任务 = document.createElement("select"); 任务.className = "lvp-pf-选"; 任务行.appendChild(任务); 字段.默认任务 = 任务;
    双列(平台行, 任务行);
    // 钩子 + 语言
    const 钩行 = 行(); 标(钩行, "钩子类型");
    const 钩 = document.createElement("select"); 钩.className = "lvp-pf-选"; 钩行.appendChild(钩); 字段.钩子 = 钩;
    const 言行 = 行(); 标(言行, "语言");
    const 言 = document.createElement("select"); 言.className = "lvp-pf-选"; 填下拉(言, 语言列表(), "中文"); 言行.appendChild(言); 字段.语言 = 言;
    双列(钩行, 言行);
    // 风格 + 受众（选填）
    文本("风格", "风格（选填）", "例如：电影感、快节奏");
    文本("受众", "受众（选填）", "例如：咖啡新手");

    function 语言列表() { return 语; }

    const 错 = document.createElement("div"); 错.className = "lvp-pf-错"; 模态.appendChild(错);
    const 脚 = document.createElement("div"); 脚.className = "lvp-pf-脚"; 模态.appendChild(脚);
    const 取消 = document.createElement("button"); 取消.className = "lvp-pf-钮"; 取消.type = "button"; 取消.textContent = "取消"; 取消.onclick = 关闭;
    const 生成 = document.createElement("button"); 生成.className = "lvp-pf-钮 主"; 生成.type = "button"; 生成.textContent = "生成规划";
    脚.append(取消, 生成);

    function 收brief() {
        return {
            主题: 字段.主题.value.trim(), 平台: 字段.平台.value, 语言: 字段.语言.value,
            总时长: Number(字段.总时长.value) || 30, 段数上限: Number(字段.段数上限.value) || 0,
            钩子: 字段.钩子.value, 默认任务: 字段.默认任务.value || "t2v",
            风格: 字段.风格.value.trim(), 受众: 字段.受众.value.trim(),
        };
    }

    生成.onclick = async () => {
        const brief = 收brief();
        if (!brief.主题) { 错.textContent = "主题不能为空"; return; }
        生成.disabled = true; 生成.textContent = "规划中…"; 错.textContent = "";
        try {
            const 结果 = await 取JSON("/lvp/plan", {
                method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(brief),
            });
            on规划完成?.(结果.segments || []);
            关闭();
        } catch (e) {
            错.textContent = e.message || "规划失败";   // 不关闭，可改参重试
        } finally {
            生成.disabled = false; 生成.textContent = "生成规划";
        }
    };

    // 打开时拉枚举填平台/钩子/任务（语言为 UI 枚举、非方法论常量，前端固定）
    (async () => {
        try {
            const meta = await 取JSON("/lvp/plan_meta");
            填下拉(平台, ["通用", ...(meta.平台 || []).filter(v => v !== "通用")], "通用"); 填下拉(钩, meta.钩子, "悬念钩"); 填下拉(任务, meta.任务, "t2v");
        } catch (e) { toast(`拉取规划枚举失败：${e.message || e}`, "error"); }
    })();

    document.body.appendChild(遮罩);
    字段.主题.focus();
}
