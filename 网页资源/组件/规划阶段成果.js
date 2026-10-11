// 阶段成果只读：任务引用只保存在闭包和节点属性中，鉴权凭据不进入 DOM 或图片地址。
export const 规划阶段 = Object.freeze([
    { id: "analysis", 名称: "分析素材", 说明: "来源与内容理解" },
    { id: "episodes", 名称: "规划剧集", 说明: "主线与分集安排" },
    { id: "references", 名称: "生成参考", 说明: "人物、场景与道具参考图" },
    { id: "storyboards", 名称: "生成分镜", 说明: "已生成镜头与对白" },
]);
const 状态名 = { pending: "待开始", running: "进行中", completed: "已完成", skipped: "已跳过", partial: "部分完成" };
const 列 = v => Array.isArray(v) ? v : [];
const 文 = v => typeof v === "string" || typeof v === "number" ? String(v) : Array.isArray(v) ? v.filter(x => typeof x === "string" || typeof x === "number").join("、") : "";
const 对象 = v => v && typeof v === "object" && !Array.isArray(v) ? v : {};
const 秒 = v => Number.isFinite(Number(v)) ? `${Number(Number(v).toFixed(2))} 秒` : "";
export function 归一阶段快照(stages) {
    return 规划阶段.map(c => {
        const s = 列(stages).find(s => s?.id === c.id) || {};
        const status = Object.hasOwn(状态名, s.status) ? s.status : "pending";
        return { ...s, id: c.id, label: c.名称, status, available: Boolean(s.available) && ["completed", "partial"].includes(status) };
    });
}
export function 阶段图片地址(名) {
    if (typeof 名 !== "string" || !名.trim() || /[\x00-\x1f\\/<>:"|?*]/.test(名) || 名 === "." || 名 === ".." || !/\.(png|jpe?g|webp|gif|bmp|avif)$/i.test(名)) return "";
    return "/lvp/media/file?name=" + encodeURIComponent(名);
}
let 已注入 = false;
function 注入() {
    if (已注入) return; 已注入 = true;
    const s = document.createElement("style");
    s.textContent = `
      .lvp-规划阶段页{container-type:inline-size;container-name:lvp-规划设置}
      .lvp-规划阶段页 .lvp-规划进度{display:none}
      .lvp-阶段导航{position:relative;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:3px;flex:0 0 auto;align-self:center;width:88%;box-sizing:border-box;padding:2px 0 0;min-height:50px;margin-top:auto}
      .lvp-阶段导航::before{content:"";position:absolute;left:10%;right:10%;top:14px;height:2px;background:var(--p-primary-color,#4a9eff);opacity:.65}
      .lvp-阶段按钮{position:relative;display:grid;grid-template-columns:minmax(0,1fr);gap:1px;justify-items:center;align-content:center;min-width:0;min-height:48px;box-sizing:border-box;padding:2px;border:1px solid var(--border-color,#444);border-radius:4px;background:var(--comfy-menu-bg,#2b2b2b);color:var(--fg-color,#ddd);text-align:center;cursor:pointer}
      .lvp-阶段序号{display:grid;place-items:center;font:600 10px system-ui;width:16px;height:16px;border-radius:3px;background:var(--comfy-input-bg,#1c1c1c)}
      .lvp-阶段名称{font:600 10px system-ui;white-space:nowrap;line-height:12px}
      .lvp-阶段状态{font:9px system-ui;line-height:11px;max-width:100%;color:var(--p-text-muted-color,#9aa0a8);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .lvp-阶段按钮[data-status="completed"],.lvp-阶段按钮[data-status="partial"]{border-color:var(--p-primary-color,#4a9eff)}
      .lvp-阶段按钮[data-status="completed"] .lvp-阶段序号,.lvp-阶段按钮[data-status="partial"] .lvp-阶段序号{background:var(--p-primary-color,#4a9eff);color:var(--p-primary-contrast-color,#fff)}
      .lvp-阶段按钮[data-status="running"]{border-color:var(--p-primary-color,#4a9eff)}
      .lvp-阶段按钮[data-status="running"] .lvp-阶段序号{color:var(--p-primary-color,#4a9eff)}
      .lvp-阶段按钮:disabled{cursor:default}
      .lvp-阶段按钮[data-status="pending"],.lvp-阶段按钮[data-status="skipped"]{opacity:.72}
      .lvp-阶段按钮:not(:disabled):hover{background:var(--comfy-input-bg,#1c1c1c)}
      .lvp-阶段按钮:focus-visible{outline:2px solid var(--p-primary-color,#4a9eff);outline-offset:2px}
      .lvp-阶段成果弹窗{width:min(1000px,94vw);max-width:94vw;max-height:90vh;box-sizing:border-box;padding:0;overflow:hidden;border:1px solid var(--border-color,#444);border-radius:10px;background:var(--comfy-menu-bg,#2b2b2b);color:var(--fg-color,#ddd);font:13px/1.6 system-ui}
      .lvp-阶段成果弹窗::backdrop{background:rgba(0,0,0,.6)}
      .lvp-成果头{display:flex;align-items:flex-start;gap:16px;height:auto;min-height:0;padding:20px 24px 14px;border-bottom:1px solid var(--border-color,#444)}
      .lvp-成果标题区{flex:1;min-width:0}.lvp-成果眉题{margin:0 0 3px;font-size:11px;color:var(--p-primary-color,#4a9eff)}
      .lvp-成果标题{font:600 22px/1.3 system-ui;margin:0}.lvp-成果副标题{margin:7px 0 0;color:var(--p-text-muted-color,#9aa0a8);font-size:12px}
      .lvp-成果关闭{width:30px;height:30px;border:1px solid var(--border-color,#444);border-radius:5px;color:var(--fg-color,#ddd);background:var(--comfy-input-bg,#1c1c1c);font:20px system-ui;cursor:pointer}
      .lvp-成果关闭:focus-visible,.lvp-成果操作:focus-visible{outline:2px solid var(--p-primary-color,#4a9eff);outline-offset:2px}
      .lvp-成果正文{max-height:calc(90vh - 112px);overflow-y:auto;padding:18px 24px 24px;overflow-wrap:anywhere}
      .lvp-成果指标{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-bottom:18px}
      .lvp-成果指标项{padding:10px 14px;border:1px solid var(--border-color,#444);border-radius:6px;background:var(--comfy-input-bg,#1c1c1c)}
      .lvp-成果数字{display:block;font:600 23px/1.3 system-ui}.lvp-成果指标名{font-size:11px;color:var(--p-text-muted-color,#9aa0a8)}
      .lvp-成果节{margin:0 0 20px}.lvp-成果节标题{margin:0 0 10px;font:600 14px system-ui}
      .lvp-成果说明{white-space:pre-wrap;margin:0 0 8px}.lvp-成果次要{color:var(--p-text-muted-color,#9aa0a8);font-size:11px}
      .lvp-成果卡组{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
      .lvp-成果卡{border:1px solid var(--border-color,#444);border-radius:6px;background:var(--comfy-input-bg,#1c1c1c);padding:12px;min-width:0}
      .lvp-成果卡 h4{margin:0 0 7px;font:600 13px system-ui}.lvp-成果卡 p{margin:5px 0;white-space:pre-wrap}
      .lvp-成果标签组{display:flex;flex-wrap:wrap;gap:5px;margin:7px 0}.lvp-成果标签{padding:2px 7px;font-size:11px;line-height:1.5;border:1px solid var(--border-color,#444);border-radius:4px}
      .lvp-成果引文{margin:10px 0 0;padding:7px 10px;border-left:2px solid var(--p-primary-color,#4a9eff);color:var(--p-text-muted-color,#9aa0a8);font-size:12px;white-space:pre-wrap}
      .lvp-成果明细{display:grid;grid-template-columns:80px minmax(0,1fr);gap:5px 10px;margin:0}.lvp-成果明细 dt{color:var(--p-text-muted-color,#9aa0a8);font-size:11px}.lvp-成果明细 dd{margin:0;white-space:pre-wrap}
      .lvp-成果来源{display:flex;gap:10px;align-items:center;padding:8px 10px;border-bottom:1px solid var(--border-color,#444);min-width:0}
      .lvp-成果来源 span:first-child{flex:1;min-width:0}.lvp-成果来源 span:last-child{font-size:11px;color:var(--p-text-muted-color,#9aa0a8)}
      .lvp-成果操作区{display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin:0 0 12px}
      .lvp-成果操作,.lvp-成果分集选{border:1px solid var(--border-color,#444);border-radius:4px;padding:5px 10px;font:12px system-ui;background:var(--comfy-input-bg,#1c1c1c);color:var(--fg-color,#ddd);cursor:pointer}
      .lvp-成果操作[aria-pressed="true"]{border-color:var(--p-primary-color,#4a9eff);color:var(--p-primary-color,#4a9eff)}
      .lvp-成果图{width:100%;max-height:240px;object-fit:contain;display:block;border-radius:4px;margin:0 0 10px;background:var(--comfy-menu-bg,#2b2b2b)}
      .lvp-成果镜头{margin-bottom:10px}.lvp-成果镜头头{display:flex;gap:10px;align-items:center;margin-bottom:8px}.lvp-成果镜头号{font:600 20px system-ui;color:var(--p-primary-color,#4a9eff)}
      .lvp-成果镜头头 h4{flex:1;margin:0}.lvp-成果镜头头 small{color:var(--p-text-muted-color,#9aa0a8)}
      .lvp-成果状态面{padding:32px 16px;text-align:center;border:1px dashed var(--border-color,#444);border-radius:6px;color:var(--p-text-muted-color,#9aa0a8)}
      @media(max-width:600px){.lvp-成果头{padding:15px}.lvp-成果正文{padding:14px}.lvp-成果标题{font-size:19px}.lvp-成果卡组{grid-template-columns:minmax(0,1fr)}.lvp-成果指标{gap:5px}.lvp-成果指标项{padding:8px}.lvp-成果数字{font-size:20px}}
      @container lvp-规划设置 (max-width:260px){.lvp-阶段导航{grid-template-columns:repeat(2,minmax(0,1fr))}.lvp-阶段导航::before{display:none}}
    `;
    document.head.appendChild(s);
}

export function 创建规划阶段成果(父, { 取节点, 请求 = fetch } = {}) {
    注入(); 父.classList.add("lvp-规划阶段页");
    const nav = document.createElement("nav"); nav.className = "lvp-阶段导航"; nav.setAttribute("aria-label", "规划阶段成果"); 父.appendChild(nav);
    let 节点 = null, 引用 = null, 快照 = 归一阶段快照(), 代 = 0, 快照序 = 0, 读取代 = 0, 读取控制 = null, 弹窗 = null, 来源按钮 = null, 销毁了 = false;
    const 预存 = new Map(), 按钮表 = new Map();
    const 建 = (tag, cls, text, parent) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; parent?.appendChild(e); return e; };
    function 关闭() { 读取代++; 读取控制?.abort(); 读取控制 = null; if (弹窗) { const d = 弹窗; 弹窗 = null; if (d.open) d.close(); d.remove(); } if (来源按钮 && 来源按钮.ownerDocument?.contains?.(来源按钮)) 来源按钮.focus(); 来源按钮 = null; }
    function 绘导航() {
        for (const c of 规划阶段) {
            const s = 快照.find(s => s.id === c.id), b = 按钮表.get(c.id);
            b.disabled = !引用?.id || !引用?.token || !s.available; b.dataset.status = s.status;
            b.title = s.available ? `${c.说明} · 点击查看成果` : s.reason || c.说明;
            b.querySelector(".lvp-阶段序号").textContent = s.status === "completed" ? "✓" : String(规划阶段.indexOf(c) + 1);
            b.querySelector(".lvp-阶段状态").textContent = 状态名[s.status] + (s.total > 1 && s.completed != null ? ` ${s.completed}/${s.total}` : "");
        }
    }
    for (const [i, c] of 规划阶段.entries()) {
        const b = 建("button", "lvp-阶段按钮", null, nav); b.type = "button"; b.dataset.stage = c.id;
        建("span", "lvp-阶段序号", i + 1, b); 建("span", "lvp-阶段名称", c.名称, b); 建("span", "lvp-阶段状态", "待开始", b);
        b.onclick = () => 打开(c.id); 按钮表.set(c.id, b);
    }
    function 有效(轮, 当前节点, ref) { return !销毁了 && 代 === 轮 && 节点 === 当前节点 && 取节点() === 当前节点 && 引用?.id === ref.id && 引用?.token === ref.token; }
    async function 读阶段(stage, params, signal, ref = 引用) {
        const query = params ? "?" + new URLSearchParams(params).toString() : "";
        const r = await 请求(`/lvp/plan/jobs/${encodeURIComponent(ref.id)}/stages/${stage}${query}`, { headers: { "X-LVP-Plan-Token": ref.token }, signal });
        const d = await r.json(); if (!r.ok) throw new Error(d.error || "成果读取失败，请重试"); return d;
    }
    function 绑定(n, ref = null, stages = null) {
        关闭(); 代++; 预存.clear(); 节点 = n; 引用 = ref?.id && ref?.token ? { id: ref.id, token: ref.token } : null;
        快照序++; 快照 = 归一阶段快照(stages || ref?.stages); 绘导航();
        // 先绘制缓存，再只读刷新后台的真实状态；关闭页面期间后台可能已经完成。
        if (引用) 刷新();
    }
    async function 刷新() {
        if (!引用 || !节点) return;
        const 轮=代, current=节点, reference=引用, 序=快照序;
        try {
            const r=await 请求(`/lvp/plan/jobs/${encodeURIComponent(reference.id)}/stages`, {headers:{"X-LVP-Plan-Token":reference.token}});
            const d=await r.json(); if(!r.ok || !有效(轮,current,reference) || 快照序!==序) return;
            if(Array.isArray(d.stages)){快照序++;快照=归一阶段快照(d.stages);绘导航();}
        } catch {}
    }
    function 更新(data, ref = null) {
        if (ref?.id && ref?.token && (!引用 || 引用.id !== ref.id || 引用.token !== ref.token)) { 关闭(); 代++; 预存.clear(); 引用 = { id: ref.id, token: ref.token }; }
        if (Array.isArray(data?.stages)) { 快照序++; 快照 = 归一阶段快照(data.stages); 预存.clear(); 绘导航(); }
    }
    const 节 = (parent, title) => { const e = 建("section", "lvp-成果节", null, parent); 建("h3", "lvp-成果节标题", title, e); return e; };
    const 标签 = (parent, vals) => { const group = 建("div", "lvp-成果标签组", null, parent); for (const value of vals.filter(Boolean)) 建("span", "lvp-成果标签", 文(value), group); return group; };
    const 明细 = (parent, fields) => { const dl = 建("dl", "lvp-成果明细", null, parent); for (const [k,v] of fields) if (文(v)) { 建("dt", "", k, dl); 建("dd", "", 文(v), dl); } };
    const 指标 = (parent, values) => { const group = 建("div", "lvp-成果指标", null, parent); for (const [n,v] of values) { const x = 建("div", "lvp-成果指标项", null, group); 建("strong", "lvp-成果数字", v, x); 建("span", "lvp-成果指标名", n, x); } };
    function 实体卡(parent, entities) {
        if (!entities.length) return;
        const group = 建("div", "lvp-成果卡组", null, parent);
        for (const [i, e] of entities.entries()) {
            const card = 建("article", "lvp-成果卡", null, group);
            建("h4", "", 文(e.名称 || e.名 || e.姓名 || e.name) || `资料 ${i + 1}`, card);
            标签(card, [e.类型 || e.type]); 明细(card, [["外观", e.外观 || e.描述], ["身份与关系", e.身份 || e.关系], ["原文依据", e.原文依据 || e.依据]]);
        }
    }
    function 分析(parent, data, 加载更多) {
        const contents = 列(data.contents), scopes = 列(data.scopes);
        const reads = contents.map(e => 对象(e.理解 || e.内容理解 || e.data || e));
        const units = reads.flatMap(e => 列(e.内容单元)); const entities = reads.flatMap(e => 列(e.人物场景));
        指标(parent, [["来源范围", scopes.length || data.totalScopes || 0], ["本页内容单元", units.length], ["人物与场景", entities.length]]);
        if (data.classification) { const c = 对象(data.classification); const section = 节(parent, "需求识别"); 标签(section, [c.输入类型, c.目标体裁, c.改写方式]); if (文(c.说明 || c.理由)) 建("p", "lvp-成果说明", 文(c.说明 || c.理由), section); }
        if (列(data.materials).length) {
            const section=节(parent,"已提供素材与已有观察");
            建("p","lvp-成果次要",文(data.materialNote)||"仅展示已有记录，无观察资料不代表已分析音视频内容。",section);
            const group=建("div","lvp-成果卡组",null,section);
            for(const material of data.materials){const card=建("article","lvp-成果卡",null,group);建("h4","",文(material.名称||material.名),card);标签(card,[material.类型]);const observation=对象(data.materialUnderstanding?.[material.名]);明细(card,[["已有描述",observation.描述||material.描述||"未提供观察记录"],["取样说明",observation.取样说明]]);}
        }
        if (scopes.length) { const section = 节(parent, "来源范围"); for (const s of scopes) { const row = 建("div", "lvp-成果来源", null, section); 建("span", "", 文(s.来源 || s.名称 || s.id), row); 建("span", "", [s.id, Number.isFinite(s.起) && Number.isFinite(s.止) ? `${s.起}–${s.止} 字符` : s.范围].filter(Boolean).join(" · "), row); } }
        if (units.length) {
            const section = 节(parent, "内容理解与原文依据"), group = 建("div", "lvp-成果卡组", null, section);
            for (const [i,u] of units.entries()) {
                const card = 建("article", "lvp-成果卡", null, group); 建("h4", "", `内容 ${u.id || i + 1}`, card); 建("p", "lvp-成果说明", 文(u.内容 || u.概要), card);
                for (const src of 列(u.来源)) { const q = 建("blockquote", "lvp-成果引文", 文(src.引文), card); if (src.范围) 建("footer", "lvp-成果次要", 文(src.范围), q); }
                if (列(u.必留台词).length) 明细(card, [["必留台词", u.必留台词]]);
            }
        }
        if (entities.length) 实体卡(节(parent, "人物、场景与道具"), entities);
        for (const e of reads) if (文(e.保真说明)) 建("p", "lvp-成果次要", `保真说明：${文(e.保真说明)}`, parent);
        if (data.nextOffset != null) { const b = 建("button", "lvp-成果操作", `加载更多内容（已显示 ${Number(data.offset || 0) + contents.length}/${data.totalContents || "…"}）`, parent); b.type = "button"; b.onclick = () => 加载更多(data.nextOffset, data); }
        if (!scopes.length && !units.length && !entities.length) 建("p", "lvp-成果状态面", "当前阶段尚未保存可展示的内容理解。", parent);
    }
    function 剧集(parent, data) {
        const episodes = 列(data.episodes), entities = 列(data.entities);
        指标(parent, [["规划剧集", episodes.length || (data.mode === "single" ? 1 : 0)], ["人物与场景", entities.length], ["规划方式", data.mode === "single" ? "单集" : "分集"]]);
        if (data.mainline) 建("p", "lvp-成果说明", 文(data.mainline), 节(parent, "故事主线"));
        if (episodes.length) {
            const group = 建("div", "lvp-成果卡组", null, 节(parent, "分集安排"));
            for (const [i,e] of episodes.entries()) { const card = 建("article", "lvp-成果卡", null, group); 建("h4", "", `第 ${e.集号 || i + 1} 集 · ${文(e.名称) || "未命名"}`, card); 标签(card, 列(e.范围)); 明细(card, [["剧情衔接", e.衔接], ["本集要点", e.概要 || e.说明]]); }
        } else if (data.mode === "single") 建("p", "lvp-成果说明", "本次按一个完整视频规划，内容与镜头在同一集内组织。", parent);
        if (entities.length) 实体卡(节(parent, "人物与场景资料"), entities);
    }
    function 参考(parent, data) {
        const materials = 列(data.素材), entities = 列(data.实体), notes = 对象(data.素材理解);
        指标(parent, [["参考图", materials.filter(m => 阶段图片地址(m.名)).length], ["实体", entities.length], ["画风", 文(data.画风) || "未指定"]]);
        const tools = 建("div", "lvp-成果操作区", null, parent), gallery = 建("div", "lvp-成果卡组", null, parent); let active = "全部";
        const filters = ["全部", ...new Set(entities.map(e => 文(e.类型)).filter(Boolean))];
        const draw = () => {
            gallery.replaceChildren(); for (const b of tools.children) b.setAttribute("aria-pressed", String(b.textContent === active));
            for (const [i,m] of materials.entries()) {
                const entity = entities.find(e => e.id === m.实体id || e.参考图 === m.名 || e.文件名 === m.名 || e.名 === m.名 || e.名称 === m.实体名称) || entities[i] || {};
                if (active !== "全部" && entity.类型 !== active) continue;
                const card = 建("article", "lvp-成果卡", null, gallery), url = 阶段图片地址(m.名);
                if (url) { const image = 建("img", "lvp-成果图", null, card); image.src = url; image.alt = 文(entity.名称 || m.名); image.loading = "lazy"; image.onerror = () => { image.remove(); 建("p", "lvp-成果次要", "参考图片暂时无法读取", card); }; }
                建("h4", "", 文(entity.名称 || m.名称 || m.实体名称 || m.名), card); 标签(card, [entity.类型 || m.实体类型]);
                const observation = 对象(notes[m.名]); 明细(card, [["外观", entity.外观 || entity.描述], ["观察描述", observation.描述], ["素材文件", m.名]]);
            }
            if (!gallery.children.length) 建("p", "lvp-成果状态面", "此分类尚未保存参考图。", gallery);
        };
        for (const filter of filters) { const b = 建("button", "lvp-成果操作", filter, tools); b.type = "button"; b.onclick = () => { active = filter; draw(); }; } draw();
    }
    function 分镜(parent, data, 换集, status) {
        const episodes = 列(data.episodes), result = 对象(data.result), segments = 列(result.segments);
        指标(parent, [["已生成剧集", episodes.length || (segments.length ? 1 : 0)], ["本集镜头", segments.length], ["本集时长", 秒(Math.max(0, ...segments.map(s => Number(s.end) || 0)))]]);
        if (status === "partial") 建("p", "lvp-成果说明 lvp-成果次要", "已有分镜已保存，规划尚未全部生成；具体原因见下方提醒。", parent);
        for (const w of 列(result.规划资料?.警告)) 建("p", "lvp-成果说明", [w.阶段, w.说明, w.建议].filter(Boolean).join("："), parent);
        if (result.规划资料?.自动验收?.通过 === false) 建("p", "lvp-成果说明 lvp-成果次要", `本集尚未通过自动验收：${文(result.规划资料.自动验收.说明)}`, parent);
        if (episodes.length) {
            const controls = 建("div", "lvp-成果操作区", null, parent); 建("label", "", "查看已生成分集", controls);
            const sel = 建("select", "lvp-成果分集选", null, controls); sel.setAttribute("aria-label", "查看已生成分集");
            for (const [i,e] of episodes.entries()) { const op = 建("option", "", `第 ${e.集号 || i+1} 集 · ${文(e.名称)} · ${e.镜头数 || 0} 镜头`, sel); op.value = e.集号 || i+1; }
            sel.value = String(data.episode || episodes[0].集号 || 1); sel.onchange = () => 换集(sel.value);
        }
        if (!segments.length) { 建("p", "lvp-成果状态面", "该分集暂时没有已生成镜头。", parent); return; }
        const references = 列(result.生成参考图资料?.素材);
        for (const [i,s] of segments.entries()) {
            const d = 对象(s.镜头资料), card = 建("article", "lvp-成果卡 lvp-成果镜头", null, parent), header = 建("div", "lvp-成果镜头头", null, card);
            建("span", "lvp-成果镜头号", String(i+1).padStart(2,"0"), header); 建("h4", "", 文(s.标题 || d.标题) || "镜头", header); 建("small", "", `${秒(s.start)} — ${秒(s.end)}`, header);
            标签(card, [d.景别 || s.景别, d.机位 || s.机位, s.职能, s.情绪]);
            const 对白 = d.对白 ?? s.对白, 旁白 = d.旁白 ?? s.旁白;
            // 空对白是有效分类，合并台词不能回填为对白；旧数据仅有台词时单独展示。
            明细(card, [["主体", d.主体 || s.主体], ["动作", d.动作 || s.动作], ["画面", s.画面 || s.prompt], ["对白", 对白], ["旁白", 旁白],
                ["台词／旁白", 对白 == null && 旁白 == null ? s.台词 : ""]]);
            const refs=对象(s.refs), names=[...列(s.使用素材),...列(refs.图片),refs.首帧,refs.尾帧].filter(n=>typeof n==="string");
            const matched = [...new Set(names)].map(n=>references.find(m=>m.名===n)).filter(Boolean);
            for (const m of matched) { const url = 阶段图片地址(m.名); if (url) { const img = 建("img", "lvp-成果图", null, card); img.src = url; img.alt = m.名; img.loading = "lazy"; } }
        }
    }
    async function 打开(id) {
        const s = 快照.find(s => s.id === id); if (!s?.available || !引用 || !节点 || 取节点() !== 节点) return;
        关闭(); 来源按钮 = 按钮表.get(id); const c = 规划阶段.find(c=>c.id===id);
        const d = 弹窗 = 建("dialog", "lvp-阶段成果弹窗", null, document.body); d.setAttribute("aria-label", `${c.名称}成果`);
        const head = 建("header", "lvp-成果头", null, d), title = 建("div", "lvp-成果标题区", null, head);
        建("p", "lvp-成果眉题", `阶段 ${规划阶段.indexOf(c)+1} · ${状态名[s.status]}`, title); 建("h2", "lvp-成果标题", c.名称, title); 建("p", "lvp-成果副标题", c.说明 + " · 已保存成果，只读查看", title);
        const close = 建("button", "lvp-成果关闭", "×", head); close.type = "button"; close.setAttribute("aria-label", "关闭阶段成果"); close.onclick = 关闭;
        const body = 建("div", "lvp-成果正文", null, d); d.addEventListener("cancel", e => { e.preventDefault(); 关闭(); }); d.addEventListener("close", () => { if (弹窗 === d) 关闭(); }); d.showModal(); close.focus();
        const 轮 = 代, current = 节点, reference = 引用;
        const load = async (params = null, old = null) => {
            const read = ++读取代; 读取控制?.abort(); 读取控制 = new AbortController();
            body.replaceChildren(); 建("p", "lvp-成果状态面", "正在读取已保存成果…", body);
            try {
                const data = !params && 预存.has(id) ? 预存.get(id) : await 读阶段(id, params, 读取控制.signal, reference);
                if (!有效(轮,current,reference) || 读取代 !== read || 弹窗 !== d) return;
                let payload = 对象(data.data);
                if (old) payload = { ...payload, contents: [...列(old.contents), ...列(payload.contents)], offset: old.offset || 0 };
                body.replaceChildren();
                if (id === "analysis") 分析(body,payload,(offset,prior)=>load({offset},prior));
                else if (id === "episodes") 剧集(body,payload);
                else if (id === "references") 参考(body,payload);
                else 分镜(body,payload,episode=>load({episode}),data.status || s.status);
            } catch(e) {
                if (!有效(轮,current,reference) || 读取代 !== read || 弹窗 !== d || e.name === "AbortError") return;
                body.replaceChildren(); 建("p", "lvp-成果状态面", e.message || "成果读取失败", body); const b = 建("button", "lvp-成果操作", "重试读取", body); b.type="button"; b.onclick=()=>load(params,old);
            }
        }; await load();
    }
    绘导航();
    return { 绑定, 更新, 刷新, 关闭, 取阶段:()=>快照.map(s=>({...s})), 销毁:()=>{关闭();销毁了=true;代++;nav.remove();} };
}
