"""浏览器告警实时推送 WebSocket。

供前端订阅 video_alert 等实时消息（鉴权复用登录 JWT，从 Cookie 读取）。
与车端 Agent 使用的 /api/agent/ws/* 相互独立。
"""

from __future__ import annotations

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from config import JWT_ALGORITHM, JWT_SECRET_KEY
from inference.notify import subscribe, unsubscribe

router = APIRouter(tags=["实时推送"])


def _authenticate_cookie(token: str | None) -> bool:
    if not token:
        return False
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload.get("sub") is not None
    except jwt.InvalidTokenError:
        return False


@router.websocket("/api/ws/alerts")
async def alerts_websocket(websocket: WebSocket) -> None:
    """浏览器告警推送通道：登录后订阅，实时接收 video_alert 等消息。"""
    if not _authenticate_cookie(websocket.cookies.get("access_token")):
        await websocket.close(code=4401, reason="unauthorized")
        return

    await websocket.accept()
    queue = subscribe()
    try:
        while True:
            message = await queue.get()
            await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    finally:
        unsubscribe(queue)
