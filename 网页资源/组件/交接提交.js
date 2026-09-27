export const 交接类型 = "初采交接与清理";

const 终态 = new Set(["SUCCEEDED", "FAILED", "CANCELLED", "PAUSED"]);
const 状态码 = new Set([
    "VALIDATING", "A_QUEUED", "A_RUNNING", "A_WRITING", "ARTIFACT_READY",
    "A_SUCCEEDED", "C_QUEUED", "C_CHECKING", "C_REQUESTED", "B_QUEUED", "B_CHECKING",
    "B_GATE_PASSED", ...终态,
]);
const 敏感字段 = new Set(["capability", "authToken", "apiKey", "auth_token_comfy_org", "api_key_comfy_org"]);

class 交接异常 extends Error {
    constructor(消息, 状态 = 400) {
        super(消息);
        this.status = 状态;
    }
}

function 拒绝(消息 = "交接请求被拒绝：无法确认有效图边界", 状态 = 400) {
    throw new 交接异常(消息, 状态);
}

function 字典(值) {
    return 值 !== null && typeof 值 === "object" && !Array.isArray(值);
}

function 连线(值) {
    return Array.isArray(值) && 值.length === 2 && typeof 值[0] === "string"
        && Number.isSafeInteger(值[1]) && 值[1] >= 0;
}

function 上游链(output, 交接ID) {
    const 上游 = new Map();
    for (const [ID, 节点] of Object.entries(output)) {
        if (!字典(节点?.inputs)) continue;
        for (const 值 of Object.values(节点.inputs)) {
            if (连线(值) && Object.hasOwn(output, 值[0])) {
                if (!上游.has(ID)) 上游.set(ID, []);
                上游.get(ID).push(值[0]);
            }
        }
    }
    const 可达 = new Set(交接ID), 待处理 = [...可达];
    while (待处理.length) {
        for (const 下一个 of 上游.get(待处理.pop()) ?? []) {
            if (!可达.has(下一个)) {
                可达.add(下一个);
                待处理.push(下一个);
            }
        }
    }
    return 可达;
}

export function 判定有效交接(output, 取定义) {
    if (Array.isArray(output)) {
        if (output.some(图 => 字典(图) && Object.values(图).some(节点 => 节点?.class_type === 交接类型))) {
            拒绝("交接不支持批量 output");
        }
        return null;
    }
    if (!字典(output) || !Object.values(output).some(节点 => 节点?.class_type === 交接类型)) return null;
    const 定义 = new Map();
    for (const [ID, 节点] of Object.entries(output)) {
        const 数据 = 取定义(节点?.class_type);
        if (!数据 || typeof 数据.output_node !== "boolean") {
            拒绝(`节点 ${ID}（${节点?.class_type}）缺少宿主定义，无法确认图边界`);
        }
        定义.set(ID, 数据);
    }
    const 交接ID = new Set(Object.keys(output).filter(ID => output[ID].class_type === 交接类型));
    const 链上 = 上游链(output, 交接ID);
    const 访问中 = new Set(), 已访问 = new Set(), 有效交接 = [];
    function 访问(ID) {
        if (!Object.hasOwn(output, ID)) 拒绝(`连线指向不在本次提交中的节点 ${ID}，无法确认图边界`);
        if (访问中.has(ID)) 拒绝(`节点 ${ID}（${output[ID].class_type}）参与循环，交接不支持非 DAG 图`);
        if (已访问.has(ID)) return;
        访问中.add(ID);
        const 节点 = output[ID], 数据 = 定义.get(ID);
        if (!字典(节点.inputs)) 拒绝(`节点 ${ID}（${节点.class_type}）的 inputs 不是静态字典`);
        if (!字典(数据.input)) 拒绝(`节点 ${ID}（${节点.class_type}）的宿主 input 声明不是字典`);
        if (数据.api_node) 拒绝(`节点 ${ID}（${节点.class_type}）是远程 API 节点，交接不支持`);
        // list 只否决决定初采产物的上游链；H 下游由宿主按常规二采执行，显示型 sink 不再一票否决。
        if (链上.has(ID) && (数据.input_is_list || 数据.is_input_list || 数据.output_is_list?.some(Boolean))) {
            拒绝(`交接上游链上的节点 ${ID}（${节点.class_type}）是 list 节点，交接不支持`);
        }
        const 输入 = { ...数据.input.required, ...数据.input.optional };
        const 在链上 = 链上.has(ID);
        for (const [名称, 值] of Object.entries(节点.inputs)) {
            // 宿主前端会把派生控件写成「父名.子名」（如 SaveVideo 的 format.codec），按父声明校验。
            const 点号 = 名称.indexOf(".");
            const 声明 = Object.hasOwn(输入, 名称) || 点号 < 0 ? 名称 : 名称.slice(0, 点号);
            const 已声明 = Object.hasOwn(输入, 声明);
            if (已声明) {
                const 规格 = 输入[声明];
                if (!Array.isArray(规格) || 规格.length < 1 || 规格.length > 2
                    || (typeof 规格[0] !== "string" && !Array.isArray(规格[0]))
                    || (规格[1] !== undefined && !字典(规格[1])) || 规格[1]?.rawLink || 规格[1]?.lazy) {
                    拒绝(`节点 ${ID}（${节点.class_type}）的输入「${名称}」使用了交接不支持的宿主声明`);
                }
            } else if (在链上) {
                // 链外的未声明键由宿主自行处置，按原样透传；初采链上的键必须逐一对上声明。
                拒绝(`节点 ${ID}（${节点.class_type}）的输入「${名称}」不在宿主声明里，无法确认图边界`);
            }
            if (连线(值)) 访问(值[0]);
            else if (值 !== null && typeof 值 === "object") {
                拒绝(`节点 ${ID}（${节点.class_type}）的输入「${名称}」不是标量或顶层连线`);
            }
        }
        访问中.delete(ID);
        已访问.add(ID);
        if (节点.class_type === 交接类型) 有效交接.push(ID);
    }
    for (const [ID, 数据] of 定义) if (数据.output_node) 访问(ID);
    if (有效交接.length > 1) 拒绝("交接仅支持一条有效初采交接链");
    return 有效交接[0] ?? null;
}

function 转换选项(选项) {
    if (选项 === undefined) return {};
    if (!字典(选项)) 拒绝("交接不支持此提交选项");
    for (const 名称 of Object.keys(选项)) {
        if (名称 === "partialExecutionTargets" && 选项[名称] === undefined) continue;
        if (名称 !== "previewMethod") 拒绝("交接不支持批次、局部执行、敏感或未知提交选项");
    }
    const 预览 = 选项.previewMethod;
    if (预览 === undefined || 预览 === "default") return {};
    if (!["none", "auto", "latent2rgb", "taesd"].includes(预览)) 拒绝("交接不支持此预览方式");
    return { preview_method: 预览 };
}

function 固定快照(提示, 选项) {
    if (!字典(提示?.output) || !字典(提示?.workflow)) 拒绝();
    const 快照 = structuredClone({ output: 提示.output, workflow: 提示.workflow, options: 选项 });
    function 检查(值, 访问中 = new Set()) {
        if (!值 || typeof 值 !== "object") return;
        if (访问中.has(值)) 拒绝("交接快照不支持循环数据");
        访问中.add(值);
        for (const [名称, 内容] of Object.entries(值)) {
            if (敏感字段.has(名称)) 拒绝("交接快照不得包含控制能力或敏感参数");
            检查(内容, 访问中);
        }
        访问中.delete(值);
        Object.freeze(值);
    }
    检查(快照);
    return 快照;
}

function 公开状态(数据) {
    if (!字典(数据) || typeof 数据.job_id !== "string" || !/^[a-zA-Z0-9_-]{1,128}$/.test(数据.job_id)
        || !Number.isSafeInteger(数据.attempt) || 数据.attempt < 1
        || !Number.isSafeInteger(数据.version) || 数据.version < 0 || !状态码.has(数据.state)) {
        拒绝("交接状态响应不合法", 502);
    }
    const prompt_id = typeof 数据.prompt_id === "string" && /^[a-zA-Z0-9_-]{1,128}$/.test(数据.prompt_id)
        ? 数据.prompt_id : null;
    return { job_id: 数据.job_id, attempt: 数据.attempt, version: 数据.version, state: 数据.state,
        prompt_id, number: Number.isFinite(数据.number) ? 数据.number : 0, node_errors: {} };
}

export function 创建交接控制器({ app, api, 取定义, 创建错误 }) {
    let 运行态 = new WeakMap(), 生命周期 = 0, 已安装 = false;
    const 批次上下文 = new Set(), 延后批次 = new Map(), 排队序号 = [];

    function 有效(节点, 运行) {
        return 运行态.get(节点) === 运行 && 运行.周期 === 生命周期 && app.graph === 运行.图
            && String(节点.id) === 运行.ID && 节点.comfyClass === 交接类型
            && (!节点.graph || 节点.graph === 运行.图) && 运行.图.getNodeById(运行.ID) === 节点;
    }

    function 取得运行(节点) {
        let 运行 = 运行态.get(节点);
        if (运行 && 有效(节点, 运行)) return 运行;
        运行 = { 图: app.graph, ID: String(节点.id), 周期: 生命周期, 代数: 0, 操作中: false, 待提交: null };
        运行态.set(节点, 运行);
        return 运行;
    }

    function 图指纹(图) {
        if (typeof 图.serialize !== "function") 拒绝("无法验证当前图快照");
        return JSON.stringify([图._version, 图.serialize()]);
    }

    function 守卫(节点, 运行, 检查编辑 = false) {
        return { 节点, 运行, 代数: 运行.代数, 指纹: 检查编辑 ? 图指纹(运行.图) : null };
    }

    function 仍归属(凭据) {
        return 有效(凭据.节点, 凭据.运行) && 凭据.代数 === 凭据.运行.代数;
    }

    function 核验(凭据, 要求指纹 = true) {
        if (!仍归属(凭据) || (要求指纹 && 凭据.指纹 !== null && 凭据.指纹 !== 图指纹(凭据.运行.图))) {
            拒绝("交接操作已失效：图或节点已改变，请重新明确提交", 409);
        }
    }

    function 安全异常(错误) {
        return 错误 instanceof 交接异常 ? 错误 : new 交接异常("交接连接离线或响应失败，未确认本次交接是否已受理", 0);
    }

    async function 请求(凭据, 路径, 请求体) {
        核验(凭据);
        const 响应 = await api.fetchApi(路径, {
            method: "POST", cache: "no-store",
            headers: { "X-LVP-Handoff": "1", "Content-Type": "application/json" },
            body: JSON.stringify(请求体),
        });
        核验(凭据, false);
        if (!响应.ok) {
            const 状态 = Number.isInteger(响应.status) && 响应.status >= 400 && 响应.status <= 599 ? 响应.status : 502;
            拒绝([401, 403].includes(状态) ? `交接权限被拒绝（HTTP ${状态}）` : `交接请求失败（HTTP ${状态}）`, 状态);
        }
        const 数据 = await 响应.json();
        核验(凭据, false);
        return 数据;
    }

    async function 提交(ID, 参数) {
        let 凭据;
        try {
            if (参数[0] !== 0 || 参数.length > 3 || [...批次上下文].some(上下文 => 上下文.数量 !== 1)) {
                拒绝("交接不支持 front、自定义 number 或批量自动连发");
            }
            const 快照 = 固定快照(参数[1], 转换选项(参数[2]));
            const 节点 = app.graph?.getNodeById(ID);
            if (!节点 || 节点.comfyClass !== 交接类型) 拒绝("无法定位当前交接节点实例");
            const 运行 = 取得运行(节点);
            if (运行.操作中) 拒绝("本节点正在提交交接，请等待本次提交完成", 409);
            运行.代数++;
            凭据 = 守卫(节点, 运行, true);
            运行.操作中 = true;
            const 内容 = JSON.stringify({ ...快照, client_id: api.clientId });
            if (运行.待提交?.内容 !== 内容) 运行.待提交 = { 内容, ID: crypto.randomUUID() };
            const 数据 = await 请求(凭据, "/lvp/handoff/submit", { ...快照,
                client_id: api.clientId, request_id: 运行.待提交.ID });
            核验(凭据, false);
            const 公开 = 公开状态(数据);
            if (typeof 数据.capability !== "string" || !数据.capability || 数据.capability.length > 256) {
                拒绝("交接响应缺少有效控制能力", 502);
            }
            运行.待提交 = null;
            if (终态.has(公开.state)) 拒绝(`上一次交接已结束（${公开.state}），同一请求不会重跑；排除原因后请重新排队`, 409);
            return { ...公开 };
        } catch (错误) {
            const 安全 = 安全异常(错误);
            throw 创建错误(安全.message, 安全.status, ID);
        } finally {
            if (凭据 && 仍归属(凭据)) 凭据.运行.操作中 = false;
        }
    }

    return {
        失效全部() {
            生命周期++;
            批次上下文.clear();
            延后批次.clear();
            排队序号.length = 0;
            运行态 = new WeakMap();
        },
        安装() {
            if (已安装) return;
            已安装 = true;
            const 原提交 = api.queuePrompt;
            api.queuePrompt = function (...参数) {
                let ID;
                try { ID = 判定有效交接(参数[1]?.output, 取定义); }
                catch (错误) {
                    const 安全 = 安全异常(错误);
                    throw 创建错误(安全.message, 安全.status);
                }
                if (ID === null) return 原提交.apply(this, 参数);
                return 提交(ID, 参数);
            };
            if (typeof app.queuePrompt !== "function") return;
            api.addEventListener("promptQueueing", ({ detail }) => { 排队序号.push(detail?.requestId); });
            api.addEventListener("promptQueued", ({ detail }) => {
                const 上下文 = 延后批次.get(detail?.requestId);
                if (上下文) { 批次上下文.delete(上下文); 延后批次.delete(detail.requestId); }
            });
            const 原批次 = app.queuePrompt;
            app.queuePrompt = function (...参数) {
                const 上下文 = { 数量: 参数[1] === undefined ? 1 : 参数[1] };
                批次上下文.add(上下文);
                const 完成 = () => { 批次上下文.delete(上下文); };
                // 宿主忙时只把本次请求留在 queueItems 里由在途循环排空，本次 promise 立刻结束；
                // 所以延后路径要按 requestId 活到对应的 promptQueued，否则批量会被拆成多次已获准交接。
                const 忙时 = app.processingQueue === true;
                let 结果;
                try {
                    结果 = 原批次.apply(this, 参数);
                } catch (错误) {
                    完成();
                    throw 错误;
                }
                const ID = 排队序号.shift();
                if (忙时) {
                    if (ID === undefined) return 结果;   // 宿主不再派发 promptQueueing 时保持原语境，宁可延后回收
                    延后批次.set(ID, 上下文);
                    return 结果;
                }
                if (结果 && typeof 结果.then === "function") 结果.then(完成, 完成);
                else 完成();
                return 结果;
            };
        },
    };
}
