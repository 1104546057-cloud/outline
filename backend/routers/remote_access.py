"""无人设备 SSH、文件管理与 VNC 的浏览器访问接口。"""

from __future__ import annotations

import asyncio
import json
from urllib.parse import quote

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import get_current_user
from config import JWT_ALGORITHM, JWT_SECRET_KEY
from database import SessionLocal, get_db
from models import Device, User
from remote_gateway import RemoteStream, remote_access_gateway


router = APIRouter(prefix="/api/remote-access", tags=["无人设备远程访问"])


class FilePathPayload(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


class FileRenamePayload(BaseModel):
    source: str = Field(min_length=1, max_length=4096)
    destination: str = Field(min_length=1, max_length=4096)


def _require_device(device_id: int, db: Session) -> Device:
    device = db.query(Device).filter(Device.id == device_id).first()
    if device is None:
        raise HTTPException(status_code=404, detail="设备不存在")
    return device


def _authorize_websocket(token: str | None, device_id: int) -> bool:
    if not token:
        return False
    db = SessionLocal()
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        username = payload.get("sub")
        if not username:
            return False
        user_exists = db.query(User.id).filter(User.username == username).first() is not None
        device_exists = db.query(Device.id).filter(Device.id == device_id).first() is not None
        return user_exists and device_exists
    except jwt.PyJWTError:
        return False
    finally:
        db.close()


async def _accept_authorized_websocket(websocket: WebSocket, device_id: int) -> bool:
    authorized = await run_in_threadpool(
        _authorize_websocket,
        websocket.cookies.get("access_token"),
        device_id,
    )
    if not authorized:
        await websocket.close(code=4401, reason="authentication required")
        return False
    return True


@router.get("/devices/{device_id}/status")
async def remote_access_status(
    device_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = _require_device(device_id, db)
    return {
        "device": {"id": device.id, "name": device.name},
        **remote_access_gateway.status(device_id),
    }


@router.get("/devices/{device_id}/files")
async def list_remote_files(
    device_id: int,
    path: str = Query("/", min_length=1, max_length=4096),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_device(device_id, db)
    return await remote_access_gateway.request(device_id, "file_list", {"path": path})


@router.post("/devices/{device_id}/files/mkdir")
async def create_remote_directory(
    device_id: int,
    payload: FilePathPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_device(device_id, db)
    return await remote_access_gateway.request(device_id, "file_mkdir", payload.model_dump())


@router.post("/devices/{device_id}/files/rename")
async def rename_remote_file(
    device_id: int,
    payload: FileRenamePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_device(device_id, db)
    return await remote_access_gateway.request(device_id, "file_rename", payload.model_dump())


@router.post("/devices/{device_id}/files/delete")
async def delete_remote_file(
    device_id: int,
    payload: FilePathPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_device(device_id, db)
    return await remote_access_gateway.request(device_id, "file_delete", payload.model_dump())


@router.put("/devices/{device_id}/files/upload")
async def upload_remote_file(
    device_id: int,
    request: Request,
    path: str = Query(..., min_length=1, max_length=4096),
    overwrite: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_device(device_id, db)
    declared_size = request.headers.get("content-length")
    size = int(declared_size) if declared_size and declared_size.isdigit() else None
    stream = await remote_access_gateway.open_stream(
        device_id,
        "file_write",
        {"path": path, "overwrite": overwrite, "size": size},
        timeout=15,
    )
    try:
        async for chunk in request.stream():
            if chunk:
                await stream.send(chunk)
        result = await stream.finish(commit=True, timeout=30)
        return {"ok": True, **result}
    except BaseException:
        await stream.abort()
        raise


@router.get("/devices/{device_id}/files/download")
async def download_remote_file(
    device_id: int,
    path: str = Query(..., min_length=1, max_length=4096),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_device(device_id, db)
    stream = await remote_access_gateway.open_stream(
        device_id,
        "file_read",
        {"path": path},
        timeout=15,
    )

    async def body():
        try:
            while True:
                chunk = await stream.receive()
                if chunk is None:
                    break
                yield chunk
        finally:
            await stream.abort()

    filename = str(stream.metadata.get("name") or "download.bin")
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
        "Cache-Control": "no-store",
    }
    size = stream.metadata.get("size")
    if isinstance(size, int) and size >= 0:
        headers["Content-Length"] = str(size)
    return StreamingResponse(body(), media_type="application/octet-stream", headers=headers)


async def _browser_to_agent(websocket: WebSocket, stream: RemoteStream, *, terminal: bool) -> None:
    while True:
        message = await websocket.receive()
        message_type = message.get("type")
        if message_type == "websocket.disconnect":
            return
        data = message.get("bytes")
        if data is not None:
            await stream.send(data)
            continue
        text = message.get("text")
        if text is None:
            continue
        if not terminal:
            await stream.send(text.encode("utf-8"))
            continue
        try:
            control = json.loads(text)
        except json.JSONDecodeError:
            await stream.send(text.encode("utf-8"))
            continue
        if control.get("type") == "resize":
            cols = max(20, min(500, int(control.get("cols") or 80)))
            rows = max(5, min(300, int(control.get("rows") or 24)))
            await stream.control("resize", cols=cols, rows=rows)


async def _agent_to_browser(websocket: WebSocket, stream: RemoteStream) -> None:
    while True:
        data = await stream.receive()
        if data is None:
            return
        await websocket.send_bytes(data)


async def _proxy_stream(
    websocket: WebSocket,
    device_id: int,
    kind: str,
    params: dict,
    *,
    terminal: bool,
) -> None:
    if not await _accept_authorized_websocket(websocket, device_id):
        return

    stream: RemoteStream | None = None
    accepted = False
    try:
        stream = await remote_access_gateway.open_stream(device_id, kind, params, timeout=12)
        await websocket.accept()
        accepted = True
        upstream = asyncio.create_task(_browser_to_agent(websocket, stream, terminal=terminal))
        downstream = asyncio.create_task(_agent_to_browser(websocket, stream))
        done, pending = await asyncio.wait(
            {upstream, downstream},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()
    except HTTPException as exc:
        if accepted:
            await websocket.close(code=4502, reason=str(exc.detail)[:120])
        else:
            await websocket.close(code=4502, reason=str(exc.detail)[:120])
    except Exception:
        if accepted:
            try:
                await websocket.close(code=1011, reason="remote stream failed")
            except RuntimeError:
                pass
    finally:
        if stream is not None:
            await stream.abort()


@router.websocket("/devices/{device_id}/terminal")
async def remote_terminal_socket(
    websocket: WebSocket,
    device_id: int,
    username: str = Query("wheeltec", min_length=1, max_length=64),
    cols: int = Query(120, ge=20, le=500),
    rows: int = Query(32, ge=5, le=300),
):
    await _proxy_stream(
        websocket,
        device_id,
        "ssh",
        {"username": username, "cols": cols, "rows": rows},
        terminal=True,
    )


@router.websocket("/devices/{device_id}/vnc")
async def remote_vnc_socket(websocket: WebSocket, device_id: int):
    await _proxy_stream(websocket, device_id, "vnc", {}, terminal=False)
