export function 新提示词任务(请求体, 原稿签名) {
    const random = () => [...crypto.getRandomValues(new Uint8Array(16))].map(n => n.toString(16).padStart(2, "0")).join("");
    return { id: random(), token: random() + random(), 请求体, 原稿签名, seq: 0, 已完成: [] };
}

export function 创建提示词任务客户端({ 任务, 更新, 请求 = fetch, 等待 = null, 页面 = globalThis.document, 窗口 = globalThis.window }) {
    let 控制 = null, reader = null, detached = false, stopped = false, cancel = null, 唤醒 = null;
    const 中断 = () => Object.assign(new Error(detached ? "已断开界面，任务继续在后台运行" : "已停止"), { 断开: detached });
    function 断开() {
        detached = true;
        唤醒?.();
        控制?.abort();
        reader?.cancel().catch(() => {});
    }
    function 停止() {
        stopped = true;
        唤醒?.();
        控制?.abort();
        reader?.cancel().catch(() => {});
        cancel ||= 请求(`/lvp/plan/prompts/jobs/${任务.id}/cancel`, {
            method: "POST", headers: { "X-LVP-Prompt-Token": 任务.token },
            signal: AbortSignal.timeout(10000),
        }).then(async response => {
            if (!response.ok && response.status !== 404) throw new Error("后台停止未确认，请重新连接后停止");
        });
        return cancel;
    }
    async function 运行() {
        let 接回 = 任务.seq > 0, failures = 0;
        let timer = null, 后台 = 页面?.hidden === true, 失焦 = false, 冻结 = false, 需重连 = false;
        const 续期 = () => {
            clearTimeout(timer);
            if (后台 || 失焦 || 冻结) return;
            timer = setTimeout(() => {
                if (页面?.hidden || 后台 || 失焦 || 冻结) return;
                控制?.abort(); reader?.cancel().catch(() => {});
            }, 95000);
        };
        const 接回结果 = () => {
            if (detached || stopped || 需重连) return;
            需重连 = true; 接回 = true;
            clearTimeout(timer);
            控制?.abort(); reader?.cancel().catch(() => {});
            唤醒?.();
        };
        const 可见变化 = () => {
            const 原后台 = 后台;
            后台 = 页面?.hidden === true;
            if (后台) clearTimeout(timer);
            else if (原后台) { 失焦 = false; 接回结果(); }
        };
        const 离开窗口 = () => { 失焦 = true; clearTimeout(timer); };
        const 返回窗口 = () => {
            if (!失焦) return;
            失焦 = false;
            if (!页面?.hidden) 接回结果();
        };
        const 冻结页面 = () => { 冻结 = true; clearTimeout(timer); };
        const 恢复页面 = () => { 冻结 = false; if (!页面?.hidden) 接回结果(); };
        const 监听 = [[页面, "visibilitychange", 可见变化], [页面, "freeze", 冻结页面], [页面, "resume", 恢复页面],
            [窗口, "blur", 离开窗口], [窗口, "focus", 返回窗口]];
        for (const [目标, 名, fn] of 监听) 目标?.addEventListener?.(名, fn);
        try {
            while (!detached && !stopped) {
                需重连 = false;
                控制 = new AbortController();
                续期();
                try {
                    const response = await 请求(接回 ? `/lvp/plan/prompts/jobs/${任务.id}/events?after=${任务.seq}` : "/lvp/plan/prompts/stream", {
                        method: 接回 ? "GET" : "POST", signal: 控制.signal,
                        headers: { "Content-Type": "application/json", "X-LVP-Prompt-Token": 任务.token },
                        ...(接回 ? {} : { body: JSON.stringify({ ...任务.请求体, 提示词任务: { id: 任务.id, token: 任务.token } }) }),
                    });
                    if (!response.ok) {
                        if (接回 && response.status === 404) { 接回 = false; continue; }
                        const data = await response.json().catch(() => ({}));
                        throw Object.assign(new Error(data.error || `提示词任务请求失败（${response.status}）`), { 终态: response.status <= 500 });
                    }
                    reader = response.body?.getReader?.();
                    if (!reader) throw Object.assign(new Error("本环境不支持流式响应"), { 终态: true });
                    接回 = true;
                    const decoder = new TextDecoder();
                    let buffer = "";
                    while (!detached && !stopped) {
                        const { done, value } = await reader.read();
                        续期();
                        buffer += decoder.decode(value || new Uint8Array(), { stream: !done }).replace(/\r\n/g, "\n");
                        let boundary;
                        while ((boundary = buffer.indexOf("\n\n")) >= 0) {
                            const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
                            const lines = frame.split("\n");
                            const name = lines.find(s => s.startsWith("event:"))?.slice(6).trim() || "message";
                            const text = lines.filter(s => s.startsWith("data:")).map(s => s.slice(5).trimStart()).join("\n");
                            if (!text) continue;
                            const data = JSON.parse(text);
                            if (detached || stopped) throw 中断();
                            if (Number.isFinite(data.seq) && data.seq <= 任务.seq) continue;
                            更新(name, data);
                            if (Number.isFinite(data.seq)) 任务.seq = data.seq;
                            failures = 0;
                            if (name === "done" || name === "fatal") return;
                        }
                        if (buffer.length > 8 * 1024 * 1024) throw Object.assign(new Error("提示词事件过大"), { 终态: true });
                        if (done) break;
                    }
                } catch (e) {
                    if (detached || stopped) throw 中断();
                    if (e.终态 || e.内容变化 || e.断开) throw e;
                } finally {
                    clearTimeout(timer);
                    await reader?.cancel().catch(() => {});
                    reader = null;
                    控制.abort();
                }
                if (detached || stopped) throw 中断();
                更新("reconnecting", { 阶段: "后台继续生成，正在重新连接" });
                if (需重连) continue;
                failures++;
                if (等待) await 等待();
                else await new Promise(resolve => {
                    const timer = setTimeout(done, Math.min(15000, failures * 1500));
                    function done() { clearTimeout(timer); 唤醒 = null; resolve(); }
                    唤醒 = done;
                });
            }
            throw 中断();
        } finally {
            clearTimeout(timer);
            for (const [目标, 名, fn] of 监听) 目标?.removeEventListener?.(名, fn);
        }
    }
    return { 运行, 停止, 断开 };
}
