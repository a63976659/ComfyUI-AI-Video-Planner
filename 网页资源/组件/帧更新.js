export function 创建帧更新(更新) {
    let 帧 = 0, 参数;
    function 取消() {
        if (帧) cancelAnimationFrame(帧);
        帧 = 0;
        参数 = undefined;
    }
    function 刷新() {
        if (!帧) return;
        const 当前 = 参数;
        取消();
        更新(...当前);
    }
    function 请求(...值) {
        参数 = 值;
        if (!帧) 帧 = requestAnimationFrame(刷新);
    }
    return { 请求, 刷新, 取消 };
}
