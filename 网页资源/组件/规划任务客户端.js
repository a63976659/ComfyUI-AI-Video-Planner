// 新规划通道专用，停止先封住本地结果，再请求后端取消；不影响 H3 提示词流。
export function 创建规划任务客户端({ 请求 = fetch, 更新 = () => {}, 选范围 = async () => null, 恢复任务 = null, 保存任务 = () => {}, 等待 = null } = {}) {
    const 控制 = new AbortController();
    let job = null, stopped = false, detached = false, cancel = null;
    async function json(url, body, signal = 控制.signal) {
        const response = await 请求(url, { method: body === undefined ? "GET" : "POST",
            headers: { "Content-Type": "application/json", ...(job ? { "X-LVP-Plan-Token": job.token } : {}) },
            body: body === undefined ? undefined : JSON.stringify(body), signal });
        const data = await response.json();
        if (!response.ok) throw Object.assign(new Error(data.error || `请求失败（${response.status}）`),
            { 终态: [400, 401, 403, 404, 409].includes(response.status) });
        return data;
    }
    function 取消后台() {
        if (!job) return Promise.resolve();
        if (!cancel) {
            const timeout = new AbortController();
            const timer = setTimeout(() => timeout.abort(), 10000);
            cancel = json(`/lvp/plan/jobs/${job.id}/cancel`, {}, timeout.signal).then(data => { if (Array.isArray(data.stages)) 更新(data); return data; }).finally(() => clearTimeout(timer));
        }
        return cancel;
    }
    async function 停止() {
        stopped = true;
        控制.abort();
        return 取消后台();
    }
    function 判终态(data) {
        if (data.status === "completed") return data.result;
        if (data.status === "failed") throw Object.assign(new Error(data.error || "规划失败，原草稿未改变"), { 终态: true });
        if (data.status === "cancelled") throw Object.assign(new DOMException(data.error || "已停止，原草稿未改变", "AbortError"), { 终态: true });
        return null;
    }
    async function 暂等(delay = 1500) {
        if (等待) return 等待();
        await new Promise((resolve, reject) => {
            const abort = () => { clearTimeout(timer); reject(new DOMException("已停止", "AbortError")); };
            const timer = setTimeout(() => { 控制.signal.removeEventListener("abort", abort); resolve(); }, delay);
            控制.signal.addEventListener("abort", abort, { once: true });
            if (控制.signal.aborted) abort();
        });
    }
    async function 自动接回() {
        let failures = 0;
        while (!stopped) {
            try {
                const data = await json(`/lvp/plan/jobs/${job.id}`);
                更新(data);
                const result = 判终态(data);
                if (result) return result;
                if (data.status === "queued") await json(`/lvp/plan/jobs/${job.id}/start`, {});
                failures = 0;
            } catch (e) {
                if (e.终态 || e.name === "AbortError") throw e;
                failures++;
                更新({ status: "running", progress: { 阶段: failures > 10 ? "等待规划服务恢复（检查点已保存）" : "自动恢复连接" } });
            }
            await 暂等(failures > 10 ? 15000 : 1500);
        }
        throw new DOMException("已停止", "AbortError");
    }
    function 附任务引用(result) {
        if (job?.id && job?.token) result.规划任务引用 = { id: job.id, token: job.token };
        return result;
    }
    async function 运行(body) {
        let stream = null;
        try {
            job = 恢复任务 || await json("/lvp/plan/jobs", body);
            保存任务({ id: job.id, token: job.token, preview: job.preview, 请求体: body });
            if (stopped) throw new DOMException("已停止", "AbortError");
            if (恢复任务) return 附任务引用(await 自动接回());
            更新({ status: "queued", progress: { 阶段: "确认范围", 调用上限: job.preview.调用上限 } });
            const ids = !job.preview.自动流程 && job.preview.需选范围 ? await 选范围(job.preview, 控制.signal) : null;
            if (stopped) throw new DOMException("已停止", "AbortError");
            let readyResolve, readyReject;
            const ready = new Promise((resolve, reject) => { readyResolve = resolve; readyReject = reject; });
            stream = (async () => {
                const response = await 请求(`/lvp/plan/jobs/${job.id}/events`, {
                    headers: { "X-LVP-Plan-Token": job.token }, signal: 控制.signal,
                });
                if (!response.ok || !response.body) throw new Error("无法连接规划进度");
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = "", seq = -1;
                try {
                    while (true) {
                        const { value, done } = await reader.read();
                        buffer += decoder.decode(value || new Uint8Array(), { stream: !done }).replace(/\r\n/g, "\n");
                        let boundary;
                        while ((boundary = buffer.indexOf("\n\n")) >= 0) {
                            const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
                            const text = frame.split("\n").filter(s => s.startsWith("data:")).map(s => s.slice(5).trimStart()).join("\n");
                            if (!text) continue;
                            const data = JSON.parse(text);
                            readyResolve();
                            if (stopped || data.seq <= seq) continue;
                            seq = data.seq; 更新(data);
                            const result = 判终态(data);
                            if (result) return result;
                        }
                        if (buffer.length > 4 * 1024 * 1024) throw new Error("规划事件过大");
                        if (done) throw new Error("规划进度连接中断，原草稿未改变");
                    }
                } finally { await reader.cancel().catch(() => {}); }
            })();
            // 开始前必须收到快照，避免尚未建立进度连接就产生付费调用。
            stream.catch(readyReject);
            await ready;
            await json(`/lvp/plan/jobs/${job.id}/start`, ids ? { 范围: ids } : {});
            const result = await stream;
            if (stopped) throw new DOMException("已停止", "AbortError");
            return 附任务引用(result);
        } catch (e) {
            if (detached) throw e;
            if (!stopped && e.name !== "AbortError" && job?.preview?.自动流程) {
                if (e.终态) throw e;
                return 附任务引用(await 自动接回());
            }
            控制.abort();
            let cancelError;
            try { await 取消后台(); } catch (err) { cancelError = err; }
            if (stopped || e.name === "AbortError") {
                const error = new DOMException(cancelError ? "已停止等待，后台取消未确认；原草稿未改变" : stopped ? "已停止，原草稿未改变" : e.message, "AbortError");
                throw error;
            }
            throw e;
        } finally {
            控制.abort();
            if (stream) await stream.catch(() => {});
        }
    }
    return { 运行, 停止, 断开: () => { detached = true; 控制.abort(); } };
}
