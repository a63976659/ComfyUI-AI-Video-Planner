import asyncio
from contextvars import ContextVar

from .配置 import _LLM限流器, _限流器, _整数配置


规划请求 = ContextVar("规划请求", default=False)
_文本限流器 = _LLM限流器()
_图像限流器 = _LLM限流器()


def 请求限流器(cfg, 图像=False):
    if not 规划请求.get():
        limiter = _限流器
        active = _整数配置(cfg, "llm_max_active", 2, 下限=1)
        queued = _整数配置(cfg, "llm_max_queued", 4, 下限=0)
    else:
        limiter = _图像限流器 if 图像 else _文本限流器
        active = _整数配置(cfg, "planning_image_max_active" if 图像 else "planning_max_active", 0, 下限=0) or 600
        queued = 600
    limiter.设置上限(active, queued)
    return limiter


class 并发任务失败(ValueError):
    def __init__(self, results, errors):
        self.结果, self.错误 = results, errors
        first = min(errors)
        super().__init__(f"第{first + 1}/{len(results)}项未完成：{errors[first]}")


async def 并发收集(items, worker, 完成=None):
    items = list(items)
    if len(items) == 1:
        result = await worker(0, items[0])
        if 完成 is not None:
            完成(0, result)
        return [result]
    results, errors = [None] * len(items), {}

    async def run(index, item):
        try:
            return index, await worker(index, item), None
        except Exception as error:
            return index, None, error

    tasks = [asyncio.create_task(run(index, item)) for index, item in enumerate(items)]
    try:
        for future in asyncio.as_completed(tasks):
            index, result, error = await future
            if error is not None:
                errors[index] = error
            else:
                results[index] = result
                if 完成 is not None:
                    完成(index, result)
        if errors:
            raise 并发任务失败(results, errors)
        return results
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
