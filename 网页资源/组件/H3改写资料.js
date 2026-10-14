// 只传改写需要的资料，不传制作任务、凭据和工作流。
export function 取H3改写资料(草, 节点) {
    const p = 草?.制作 || {}, planning = 草?.规划资料 || {};
    const take = (v, keys) => Object.fromEntries(keys.filter(k => v?.[k] !== undefined).map(k => [k, v[k]]));
    return {
        素材: 草?.素材 || 草?.brief?.素材 || [], 素材理解: 草?.素材理解 || 草?.brief?.素材理解 || {},
        制作: {
            实体: (p.实体 || []).map(e => take(e, ["id", "名称", "类型", "描述", "参考图", "锁定", "修订"])),
            镜头: Object.fromEntries(Object.entries(p.镜头 || {}).map(([id, v]) => [id, take(v, ["实体引用", "起始状态", "结束状态", "声音"])])),
        },
        规划资料: { ...take(planning, ["全剧资料", "集号", "集名", "集数"]), 内容计划: take(planning.内容计划, ["人物场景", "保真说明"]) },
        // 填充节点会清空旧全局素材池；实际段级槽位由同一份取填充段映射上传。
        执行参考: {},
        执行提示词: String((节点?.widgets || []).find(w => w.name === "全局提示词")?.value || ""),
    };
}

export function 写入提示词生成结果(段, 新段) {
    if (!新段?.提示词生成 || typeof 新段.提示词生成.完成 !== "boolean") return false;
    段.提示词生成 = 新段.提示词生成;
    delete 段.提示词验收;
    if (typeof 新段.分镜原稿 === "string") 段.分镜原稿 = 新段.分镜原稿;
    if (新段.提示词生成.完成) {
        段.prompt = 新段.prompt;
        delete 段.台词时长提示;
    }
    return true;
}
