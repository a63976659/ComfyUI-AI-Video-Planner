export const 交接类型 = "初采交接与清理";

const 终态 = new Set(["SUCCEEDED", "FAILED", "CANCELLED", "PAUSED"]);
const 状态码 = new Set([
    "VALIDATING", "VALIDATING_RETRY", "A_QUEUED", "A_RUNNING", "A_WRITING", "ARTIFACT_READY",
    "A_SUCCEEDED", "C_QUEUED", "C_CHECKING", "C_REQUESTED", "B_QUEUED", "B_CHECKING",
    "B_GATE_PASSED", ...终态,
]);
const 敏感字段 = new Set(["capability", "authToken", "apiKey", "auth_token_comfy_org", "api_key_comfy_org"]);
const 影响说明 = "初采交接数据将落盘。本次按 A/C/B 分阶段执行，只有初采及保存成功后才申请全局模型卸载及执行缓存重置，会影响其它任务的缓存与模型加载。请勿从其它窗口或 API 提交任务或操作清理。B门控确认通过后才运行二采；HTTP 200 或 C_REQUESTED 不表示清理完成。最终仍需完整 IMAGE 内存，不能保证不溢出。重试可能重复保存视频。不会删除已保存文件或磁盘缓存。";

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
        if (!数据 || typeof 数据.output_node !== "boolean") 拒绝();
        定义.set(ID, 数据);
    }
    const 访问中 = new Set(), 已访问 = new Set(), 有效交接 = [];
    function 访问(ID) {
        if (!Object.hasOwn(output, ID) || 访问中.has(ID)) 拒绝();
        if (已访问.has(ID)) return;
        访问中.add(ID);
        const 节点 = output[ID], 数据 = 定义.get(ID);
        if (!字典(节点.inputs) || !字典(数据.input)) 拒绝();
        if (数据.input_is_list || 数据.output_is_list?.some(Boolean) || 数据.api_node) 拒绝();
        const 输入 = { ...数据.input.required, ...数据.input.optional };
        for (const [名称, 值] of Object.entries(节点.inputs)) {
            const 规格 = 输入[名称];
            if (!Object.hasOwn(输入, 名称) || !Array.isArray(规格) || 规格.length < 1 || 规格.length > 2
                || (typeof 规格[0] !== "string" && !Array.isArray(规格[0]))
                || (规格[1] !== undefined && !字典(规格[1])) || 规格[1]?.rawLink || 规格[1]?.lazy) 拒绝();
            if (连线(值)) 访问(值[0]);
            else if (值 !== null && typeof 值 === "object") 拒绝();
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
        prompt_id, number: Number.isFinite(数据.number) ? 数据.number : 0, node_errors: {}, can_retry: 数据.can_retry === true };
}

export function 创建交接控制器({ app, api, 取定义, 挂载节点, 显示, 创建错误 }) {
    let 运行态 = new WeakMap(), 生命周期 = 0, 已安装 = false;
    const 定时器 = new Set(), 批次上下文 = new Set(), 延后批次 = new Map(), 排队序号 = [];

    function 停止计时(运行) {
        if (运行.timer != null) {
            clearTimeout(运行.timer);
            定时器.delete(运行.timer);
            运行.timer = null;
        }
    }

    function 有效(节点, 运行) {
        const 成立 = 运行态.get(节点) === 运行 && 运行.周期 === 生命周期 && app.graph === 运行.图
            && String(节点.id) === 运行.ID && 节点.comfyClass === 交接类型
            && (!节点.graph || 节点.graph === 运行.图) && 运行.图.getNodeById(运行.ID) === 节点;
        if (!成立) 停止计时(运行);
        return 成立;
    }

    function 取得运行(节点) {
        let 运行 = 运行态.get(节点);
        if (运行 && 有效(节点, 运行)) return 运行;
        运行 = { 图: app.graph, ID: String(节点.id), 周期: 生命周期, 代数: 0, timer: null,
            polling: false, 操作中: false, 禁止: false, job: null, capability: null, 待提交: null, options: {} };
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

    function 展示(节点, 运行, 消息 = "") {
        if (!有效(节点, 运行)) return;
        const 状态 = 运行.job?.state;
        const 说明 = 状态 === "C_REQUESTED" ? "（清理请求已提交，等待B门控确认）" : "";
        显示(节点, [状态 ? `${状态}${说明}` : "", 消息].filter(Boolean).join(" · ") || "未运行");
    }

    function 安全异常(错误) {
        return 错误 instanceof 交接异常 ? 错误 : new 交接异常("交接连接离线或响应失败；未自动取消后端任务", 0);
    }

    function 显示错误(凭据, 错误) {
        const 安全 = 安全异常(错误);
        if (仍归属(凭据)) {
            if ([401, 403].includes(安全.status)) {
                凭据.运行.禁止 = true;
                凭据.运行.capability = null;
                停止计时(凭据.运行);
            }
            展示(凭据.节点, 凭据.运行, 安全.message);
        }
        return 安全;
    }

    function 确认(重试 = false, 取消 = false) {
        const 消息 = 取消
            ? "确认取消本次交接链？只操作本次任务，不会删除落盘文件。已申请的全局清理可能无法撤销；已有保存结果会保留。"
            : `${重试 ? "仅重跑本节点已绑定任务的二采，使用当前图参数，不重跑 A，不自动寻找最近产物。将重新执行 C/B，可能重复保存。" : "确认启用本次初采交接？"}${影响说明}`;
        const 对话框 = app.extensionManager?.dialog;
        if (typeof 对话框?.confirm === "function") return 对话框.confirm({ title: "初采交接与清理", message: 消息 });
        if (typeof globalThis.window?.confirm === "function") return window.confirm(消息);
        拒绝("当前宿主没有可用确认对话框");
    }

    async function 请求(凭据, 路径, 请求体, 需要能力 = true, 回执要求指纹 = true) {
        核验(凭据);
        const headers = { "X-LVP-Handoff": "1" };
        if (需要能力) {
            if (!凭据.运行.capability || 凭据.运行.禁止) 拒绝("当前交接控制权限不可用", 403);
            headers["X-LVP-Capability"] = 凭据.运行.capability;
        }
        const init = { method: 请求体 === undefined ? "GET" : "POST", headers, cache: "no-store" };
        if (请求体 !== undefined) {
            headers["Content-Type"] = "application/json";
            init.body = JSON.stringify(请求体);
        }
        const 响应 = await api.fetchApi(路径, init);
        核验(凭据, 回执要求指纹);
        if (!响应.ok) {
            const 状态 = Number.isInteger(响应.status) && 响应.status >= 400 && 响应.status <= 599 ? 响应.status : 502;
            拒绝([401, 403].includes(状态) ? `交接权限被拒绝（HTTP ${状态}），已停止状态查询` : `交接请求失败（HTTP ${状态}）`, 状态);
        }
        const 数据 = await 响应.json();
        核验(凭据, 回执要求指纹);
        return 数据;
    }

    function 接受状态(运行, 数据, 操作 = "status") {
        const 原 = 运行.job;
        if (原 && (!字典(数据) || 数据.job_id !== 原.job_id || 数据.attempt !== 原.attempt + (操作 === "retry" ? 1 : 0)
            || 数据.version < 原.version || (数据.version === 原.version && (数据.state !== 原.state || 操作 === "retry")))) return false;
        const 下一 = 公开状态(数据);
        if (!原 || 下一.version > 原.version) 运行.job = 下一;
        return true;
    }

    function 安排轮询(节点, 运行) {
        if (!有效(节点, 运行) || !运行.job || 终态.has(运行.job.state) || 运行.禁止
            || 运行.timer != null || 运行.polling || 运行.操作中) return;
        const timer = setTimeout(async () => {
            定时器.delete(timer);
            运行.timer = null;
            if (!有效(节点, 运行)) return;
            运行.polling = true;
            const 凭据 = 守卫(节点, 运行);
            try {
                const 数据 = await 请求(凭据, `/lvp/handoff/status/${运行.job.job_id}`);
                核验(凭据);
                if (接受状态(运行, 数据)) 展示(节点, 运行);
            } catch (错误) {
                显示错误(凭据, 错误);
            } finally {
                运行.polling = false;
                安排轮询(节点, 运行);
            }
        }, 1000);
        运行.timer = timer;
        定时器.add(timer);
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
            挂载节点(节点);
            const 运行 = 取得运行(节点);
            if (运行.操作中 || (运行.job && !终态.has(运行.job.state))) 拒绝("本节点已有交接任务，请先处理当前任务", 409);
            运行.代数++;
            凭据 = 守卫(节点, 运行, true);
            运行.操作中 = true;
            停止计时(运行);
            const 同意 = await 确认();
            核验(凭据);
            if (同意 !== true) return { prompt_id: null, node_errors: {} };
            const 内容 = JSON.stringify({ ...快照, client_id: api.clientId });
            if (运行.待提交?.内容 !== 内容) 运行.待提交 = { 内容, ID: crypto.randomUUID() };
            展示(节点, 运行, "正在提交交接");
            const 数据 = await 请求(凭据, "/lvp/handoff/submit", { ...快照,
                client_id: api.clientId, request_id: 运行.待提交.ID }, false, false);
            核验(凭据, false);
            const 公开 = 公开状态(数据);
            if (typeof 数据.capability !== "string" || !数据.capability || 数据.capability.length > 256) {
                拒绝("交接响应缺少有效控制能力", 502);
            }
            运行.job = 公开;
            运行.capability = 数据.capability;
            运行.options = 快照.options;
            运行.禁止 = false;
            运行.待提交 = null;
            展示(节点, 运行);
            return { ...公开 };
        } catch (错误) {
            const 安全 = 凭据 ? 显示错误(凭据, 错误) : 安全异常(错误);
            throw 创建错误(安全.message, 安全.status, ID);
        } finally {
            if (凭据 && 仍归属(凭据)) {
                凭据.运行.操作中 = false;
                安排轮询(凭据.节点, 凭据.运行);
            }
        }
    }

    async function 操作任务(节点, 重试) {
        let 凭据;
        try {
            const 运行 = 运行态.get(节点);
            if (!运行 || !有效(节点, 运行) || !运行.job || !运行.capability || 运行.禁止 || 运行.操作中) return;
            if (重试 && (!运行.job.can_retry || !终态.has(运行.job.state))) return;
            运行.代数++;
            凭据 = 守卫(节点, 运行, true);
            运行.操作中 = true;
            停止计时(运行);
            const { job_id, attempt, version } = 运行.job;
            let 请求体 = { job_id, attempt, version };
            if (重试) {
                const 当前图 = await app.graphToPrompt();
                核验(凭据);
                const 快照 = 固定快照(当前图, 当前图.options === undefined ? 运行.options : 转换选项(当前图.options));
                if (判定有效交接(快照.output, 取定义) !== 运行.ID) 拒绝("当前图不再对应本次交接任务");
                请求体 = { ...请求体, ...快照 };
            }
            const 同意 = await 确认(重试, !重试);
            核验(凭据);
            if (同意 !== true) return;
            const 数据 = await 请求(凭据, 重试 ? "/lvp/handoff/retry" : "/lvp/handoff/cancel", 请求体);
            核验(凭据);
            if (!接受状态(运行, 数据, 重试 ? "retry" : "cancel")) 拒绝("任务轮次或状态版本已改变，请核对本次交接状态", 409);
            if (重试) 运行.options = 请求体.options;
            展示(节点, 运行);
        } catch (错误) {
            if (凭据) 显示错误(凭据, 错误);
        } finally {
            if (凭据 && 仍归属(凭据)) {
                凭据.运行.操作中 = false;
                安排轮询(节点, 凭据.运行);
            }
        }
    }

    return {
        取消: 节点 => 操作任务(节点, false),
        重试: 节点 => 操作任务(节点, true),
        失效节点(节点) {
            const 运行 = 运行态.get(节点);
            if (运行) 停止计时(运行);
            运行态.delete(节点);
        },
        失效全部() {
            生命周期++;
            for (const timer of 定时器) clearTimeout(timer);
            定时器.clear();
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
