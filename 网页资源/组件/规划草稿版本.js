export function 建立规划版本(旧, brief, segments, 资料, 分集编辑) {
    const { 规划历史, ...previous } = 旧;
    const history = Array.isArray(规划历史) ? [...规划历史] : [];
    if (Array.isArray(previous.segments) && previous.segments.length) {
        if (JSON.stringify(previous).length > 500000) throw new Error("当前草稿超过版本备份上限，请先保存计划，未覆盖原稿");
        const backup = { 时间: new Date().toISOString(), 草稿: previous };
        if (分集编辑?.项目 === previous.规划资料?.项目 && 分集编辑?.分集) {
            backup.分集编辑 = JSON.parse(JSON.stringify(分集编辑));
            if (JSON.stringify(backup.分集编辑).length > 2000000) throw new Error("分集编辑备份超过上限，请先保存计划，未覆盖原稿");
        }
        history.push(backup);
    }
    // 保留最近两版；单版超限不继续叠加，避免工作流体积无界增长。
    const kept = history.slice(-2).filter(v => JSON.stringify(v.草稿 || {}).length <= 500000
        && JSON.stringify(v.分集编辑 || {}).length <= 2000000);
    const write = { brief, segments, 规划资料: 资料 };
    if (旧.禁用字幕 === true) write.禁用字幕 = true;
    if (Array.isArray(旧.素材) && 旧.素材.length) write.素材 = 旧.素材;
    if (kept.length) write.规划历史 = kept;
    return write;
}

export function 恢复规划版本(草稿) {
    const history = 草稿.规划历史;
    if (!Array.isArray(history) || !history.length) return null;
    const previous = history.at(-1)?.草稿;
    if (!previous || !Array.isArray(previous.segments)) return null;
    return { ...previous, 规划历史: history.slice(0, -1) };
}

const 分集制作字段 = ["镜头", "音轨", "字幕", "文字", "最近任务", "任务历史"];
const 复制 = value => JSON.parse(JSON.stringify(value));

export function 保存分集编辑(草稿) {
    const result = { segments: 草稿.segments, 规划资料: 草稿.规划资料 };
    if (草稿.制作) result.制作 = Object.fromEntries(分集制作字段.filter(key => key in 草稿.制作).map(key => [key, 草稿.制作[key]]));
    return 复制(result);
}

export function 切换分集草稿(当前, 分集) {
    const result = { ...当前, segments: 分集.segments, 规划资料: 分集.规划资料 };
    if (当前.制作 || 分集.制作) {
        // 画布、实体、工作流等沿用全剧配置；镜头绑定和声音字幕按集隔离。
        const shared = { ...当前.制作 };
        for (const key of 分集制作字段) delete shared[key];
        result.制作 = 复制({ ...shared, 镜头: {}, 音轨: [], 文字: [],
            字幕: { ...当前.制作?.字幕, 条目: [] }, ...分集.制作 });
    }
    return result;
}
