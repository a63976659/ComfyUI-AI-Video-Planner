export function 分配中间帧(原段, 子段组) {
    const 名 = 原段.refs?.中间帧;
    if (名 == null || 名 === "" || 子段组.length < 2) return 子段组;
    const 比例 = 原段.refs.中间帧位置 === undefined ? 0.5 : 原段.refs.中间帧位置;
    if (typeof 名 !== "string") throw new Error("中间帧必须是图片文件名");
    if (!Number.isFinite(比例) || 比例 <= 0 || 比例 >= 1) throw new Error("中间帧位置须大于0%且小于100%，请先调整位置");
    const 时长 = 子段组.map(s => s.end - s.start);
    if (时长.some(d => !Number.isFinite(d) || d <= 0)) throw new Error("中间帧所在段时长无效，请先修正时长");
    const 位置 = 时长.reduce((a, b) => a + b, 0) * 比例;
    let 起 = 0;
    return 子段组.map((s, i) => {
        const 末 = 起 + 时长[i];
        if (i < 子段组.length - 1 && Math.abs(位置 - 末) <= 1e-9) {
            throw new Error("中间帧恰好落在分割点，请先调整中间帧位置后再拆段；原段未修改");
        }
        const refs = { ...s.refs };
        if (位置 > 起 && 位置 < 末) {
            refs.中间帧 = 名;
            refs.中间帧位置 = (位置 - 起) / 时长[i];
        } else {
            delete refs.中间帧;
            delete refs.中间帧位置;
        }
        起 = 末;
        return { ...s, refs };
    });
}
