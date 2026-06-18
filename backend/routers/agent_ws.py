"""WebSocket endpoints used by outbound vehicle agents."""

import json
import struct
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from agent_gateway import agent_gateway
from database import SessionLocal
from models import Device, DeviceToken


router = APIRouter(prefix="/api/agent/ws", tags=["车端 Agent"])
MEDIA_HEADER = struct.Struct("!BQ")
MEDIA_VIEW_BY_CODE = {1: "color", 2: "depth", 3: "lidar"}
MAX_MEDIA_FRAME_BYTES = 5 * 1024 * 1024


def _authenticate_agent(token: str | None) -> int | None:
    if not token:
        return None
    db = SessionLocal()
    try:
        device_token = db.query(DeviceToken).filter(
            DeviceToken.token == token,
            DeviceToken.is_active == True,
        ).first()
        if not device_token:
            return None
        device = db.query(Device).filter(Device.id == device_token.device_id).first()
        if not device:
            return None
        device.status = "online"
        device.last_seen = datetime.now()
        db.commit()
        return device.id
    finally:
        db.close()


async def _resolve_device_id(websocket: WebSocket) -> int | None:
    token = websocket.headers.get("x-device-token") or websocket.query_params.get("token")
    return await run_in_threadpool(_authenticate_agent, token)


@router.websocket("/control")
async def agent_control_socket(websocket: WebSocket) -> None:
    device_id = await _resolve_device_id(websocket)
    if device_id is None:
        await websocket.close(code=4401, reason="invalid device token")
        return
    await websocket.accept()
    await agent_gateway.register_control(device_id, websocket)
    try:
        while True:
            message = await websocket.receive_json()
            message_type = message.get("type")
            if message_type == "result":
                await agent_gateway.resolve_command(device_id, message)
    except (WebSocketDisconnect, RuntimeError, json.JSONDecodeError):
        pass
    finally:
        await agent_gateway.unregister_control(device_id, websocket)


@router.websocket("/media")
async def agent_media_socket(websocket: WebSocket) -> None:
    device_id = await _resolve_device_id(websocket)
    if device_id is None:
        await websocket.close(code=4401, reason="invalid device token")
        return
    await websocket.accept()
    await agent_gateway.register_media(device_id, websocket)
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            data = message.get("bytes")
            if data is None:
                continue
            if len(data) <= MEDIA_HEADER.size or len(data) > MAX_MEDIA_FRAME_BYTES + MEDIA_HEADER.size:
                continue
            view_code, timestamp_ms = MEDIA_HEADER.unpack_from(data)
            view = MEDIA_VIEW_BY_CODE.get(view_code)
            frame = data[MEDIA_HEADER.size:]
            if view and frame.startswith(b"\xff\xd8") and frame.endswith(b"\xff\xd9"):
                await agent_gateway.publish_frame(device_id, view, frame, timestamp_ms)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await agent_gateway.unregister_media(device_id, websocket)
