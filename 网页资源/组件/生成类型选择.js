// 生成类型（六任务）胶囊开关；选项直接取节点「任务类型」combo 的 options.values，避免中英标签漂移。

export function 创建生成类型选择(容器, { 变更 }) {
    const 盒 = document.createElement("div");
    盒.className = "h3dyt-类型选择";
    容器.appendChild(盒);
    let 按钮组 = [];

    function 设选项(选项数组) {
        盒.innerHTML = "";
        按钮组 = (选项数组 || []).map((标签) => {
            const b = document.createElement("button");
            b.className = "h3dyt-胶囊";
            b.type = "button";
            b.textContent = 标签;
            b.onclick = () => { 高亮(标签); 变更?.(标签); };
            盒.appendChild(b);
            return b;
        });
    }
    function 高亮(标签) {
        按钮组.forEach((b) => b.classList.toggle("激活", b.textContent === 标签));
    }
    return { 设选项, 设值: 高亮 };
}

// 标签→任务码（与后端 节点/节点公用.py 的 任务标签 一致；未知回退 t2v）。
// 供状态栏面板做首尾帧区/参考区的联动显隐（设计 §7《组件值联动显隐方案》）。
const 标签到码 = {
    "文生视频 t2v": "t2v", "图生视频 i2v": "i2v", "首尾帧 fl2v": "fl2v",
    "参考生视频 r2v": "r2v", "视频改视频 v2v": "v2v", "参考+视频 rv2v": "rv2v",
};
// 无绑定节点时的默认任务标签（六项，取 标签到码 的键）：供状态栏面板在未加节点时也渲染六胶囊，
// 使「未加节点展开」与「加节点绑定后（默认 t2v）」界面一致。
export const 默认任务标签 = Object.keys(标签到码);
export function 任务码(标签) {
    return 标签到码[(标签 || "").trim()] || "t2v";
}
