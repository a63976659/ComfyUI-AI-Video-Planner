// 迁移自旧 store 的轻量响应式：仅缓存 UI 瞬时态（选中段/展开态），持久数据一律走节点桥。

export function 创建状态桥(初始 = {}) {
    const 状态 = { ...初始 };
    const 监听 = new Set();
    return {
        取: (键) => 状态[键],
        设: (键, 值) => {
            状态[键] = 值;
            监听.forEach((fn) => {
                try { fn(键, 值, 状态); } catch (e) { console.error("[状态桥]", e); }
            });
        },
        订阅: (fn) => { 监听.add(fn); return () => 监听.delete(fn); },
        快照: () => ({ ...状态 }),
    };
}
