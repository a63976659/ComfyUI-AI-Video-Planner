// 跨页面共享互斥：AI 沿用在途状态，非 AI 操作持有独立令牌。
// 不排队、不延时；只允许当前持有者释放，取消和异常也必须在 finally 释放。
export function 取操作忙(状态) {
    return !!(状态?.取("统一操作锁") || 状态?.取("LLM请求在途"));
}
export function 开始操作(状态, 名称) {
    if (取操作忙(状态)) return null;
    const 令牌 = { 名称 };
    状态?.设("统一操作锁", 令牌);
    return 令牌;
}
export function 结束操作(状态, 令牌) {
    if (令牌 && 状态?.取("统一操作锁") === 令牌) 状态.设("统一操作锁", null);
}

// 同一素材区已有的多批上传/清理沿用序号与快照保护；整组结束前阻止跨页操作。
export function 创建操作组(状态) {
    let 令牌 = null, 在途数 = 0;
    const 可操作 = () => !状态?.取("LLM请求在途") && (!取操作忙(状态) || (令牌 && 状态?.取("统一操作锁") === 令牌));
    return {
        可操作,
        async 运行(名称, 执行) {
            if (!可操作()) return false;
            if (!在途数) {
                令牌 = 开始操作(状态, 名称);
                if (!令牌) return false;
            }
            在途数++;
            try { return await 执行(); }
            finally {
                if (!--在途数) { 结束操作(状态, 令牌); 令牌 = null; }
            }
        },
    };
}
