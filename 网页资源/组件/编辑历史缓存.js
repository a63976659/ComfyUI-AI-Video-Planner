const 状态表 = new WeakMap();
const 字段组 = ["草稿编辑历史", "草稿前进历史"];
const 空草稿 = '{"brief":{},"segments":[]}';
const 拷贝 = 值 => JSON.parse(JSON.stringify(值));
const 有效历史 = 值 => Array.isArray(值) ? 值.filter(项 => 项?.草稿 && Array.isArray(项.草稿.segments)).slice(-20) : [];

function 取状态(node) {
    const props = node.properties ||= {};
    let state = 状态表.get(node);
    if (!state) {
        state = { 版本: 0, 服务: false, 待写: false, 写入中: null, 加载中: null };
        状态表.set(node, state);
    }
    if (state.props !== props) {
        state.版本++;
        state.props = props;
        state.待写 = false;
    }
    for (const 字段 of 字段组) {
        const 描述 = Object.getOwnPropertyDescriptor(props, 字段);
        if (描述?.get) continue;
        state[字段] = 有效历史(props[字段]);
        Object.defineProperty(props, 字段, {
            configurable: true, enumerable: false,
            get: () => state[字段],
            set: 值 => { state[字段] = 有效历史(值); state.版本++; },
        });
    }
    return state;
}

function 缓存ID(node) {
    const props = node.properties;
    if (!/^[a-f0-9]{32}$/.test(props.编辑历史缓存ID || "")) {
        props.编辑历史缓存ID = globalThis.crypto?.randomUUID?.().replaceAll("-", "")
            || Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join("");
    }
    return props.编辑历史缓存ID;
}

function 取快照(node, state) {
    const 后退 = 有效历史(state.草稿编辑历史);
    const 前进 = 有效历史(state.草稿前进历史).slice(-(20 - 后退.length));
    return {
        当前草稿: node.properties.剪辑草稿 ?? 空草稿,
        草稿编辑历史: 后退,
        草稿前进历史: 后退.length === 20 ? [] : 前进,
    };
}

export function 准备编辑历史(node) {
    const state = 取状态(node);
    state.服务 = true;
    缓存ID(node);
}

export function 取编辑历史(node, 字段) {
    if (!node) return [];
    const state = 取状态(node);
    return state.加载中 ? [] : state[字段];
}

export function 安排编辑历史保存(node) {
    const state = 取状态(node);
    if (!state.服务) return;
    state.待写 = true;
    if (!state.写入中) {
        state.写入中 = Promise.resolve().then(async () => {
            if (state.加载中) await state.加载中;
            while (state.待写) {
                state.待写 = false;
                const id = 缓存ID(node), body = 拷贝(取快照(node, state));
                try {
                    const res = await (state.请求 || fetch)("/lvp/cache/edit-history/" + id, {
                        method: "POST", headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(body),
                    });
                    if (!res.ok) throw new Error("本地撤销缓存保存失败（" + res.status + "）");
                } catch (e) {
                    console.warn("[长视频规划师] 撤销历史未保存到本地缓存", e);
                }
            }
        }).finally(() => { state.写入中 = null; });
    }
}

export async function 等待编辑历史保存(node) {
    const state = 取状态(node);
    await state.写入中;
}

export function 加载编辑历史(node, { 请求 = fetch, 刷新 = () => {} } = {}) {
    const state = 取状态(node);
    state.服务 = true;
    state.请求 = 请求;
    state.版本++;
    state.草稿编辑历史 = [];
    state.草稿前进历史 = [];
    const props = node.properties, 版本 = state.版本, 当前草稿 = props.剪辑草稿 ?? 空草稿;
    state.已载入属性 = props;
    const id = 缓存ID(node);
    const 加载 = Promise.resolve().then(async () => {
        try {
            const res = await 请求("/lvp/cache/edit-history/" + id, { cache: "no-store" });
            if (!res.ok) throw new Error("本地撤销缓存读取失败（" + res.status + "）");
            const data = (await res.json()).历史;
            if (node.properties !== props || state.版本 !== 版本 || (props.剪辑草稿 ?? 空草稿) !== 当前草稿) return;
            if (data?.当前草稿 !== 当前草稿) return;
            state.草稿编辑历史 = 有效历史(data.草稿编辑历史);
            const 剩余 = 20 - state.草稿编辑历史.length;
            state.草稿前进历史 = 剩余 ? 有效历史(data.草稿前进历史).slice(-剩余) : [];
        } catch (e) {
            console.warn("[长视频规划师] 本地撤销缓存不可用", e);
        } finally {
            if (state.加载中 === 加载) {
                state.加载中 = null;
                刷新();
            }
        }
    });
    state.加载中 = 加载;
    return 加载;
}

export function 确保加载编辑历史(node, options) {
    const state = 取状态(node);
    return state.已载入属性 === node.properties
        ? state.加载中 || Promise.resolve()
        : 加载编辑历史(node, options);
}
