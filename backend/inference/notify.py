"""浏览器告警实时推送：订阅者注册表 + 跨线程广播桥接。

推理在 asyncio.to_thread 的工作线程中产出事件，而浏览器 WS 运行在事件循环，
因此广播通过 loop.call_soon_threadsafe 安全地切回事件循环执行。
"""

from __future__ import annotations

import asyncio
from typing import Any


_subscribers: set[asyncio.Queue] = set()
_loop: asyncio.AbstractEventLoop | None = None


def subscribe() -> asyncio.Queue:
    """注册一个浏览器订阅者，返回其接收队列。"""
    global _loop
    try:
        _loop = asyncio.get_running_loop()
    except RuntimeError:
        _loop = None
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers.add(queue)
    return queue


def unsubscribe(queue: asyncio.Queue) -> None:
    _subscribers.discard(queue)


def _broadcast(payload: dict[str, Any]) -> None:
    """在事件循环内执行：把消息推给所有订阅者（队列满则丢旧帧）。"""
    for queue in list(_subscribers):
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(payload)


def publish_video_alert(payload: dict[str, Any]) -> None:
    """从任意线程广播视频告警；无订阅者或无事件循环时静默跳过。"""
    if not _subscribers:
        return
    loop = _loop
    if loop is not None and loop.is_running():
        loop.call_soon_threadsafe(_broadcast, payload)
