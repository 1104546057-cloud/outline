"""管理浏览器与车端 Remote Access Agent 之间的反向复用通道。"""

from __future__ import annotations

import asyncio
import struct
from dataclasses import dataclass, field
from time import time
from typing import Any

from fastapi import HTTPException, WebSocket


_BINARY_HEADER = struct.Struct("!I")
_STREAM_EOF = object()


@dataclass
class _StreamState:
    device_id: int
    stream_id: int
    kind: str
    open_future: asyncio.Future
    close_future: asyncio.Future
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=128))
    metadata: dict[str, Any] = field(default_factory=dict)


class RemoteStream:
    """一个经车端反向 WebSocket 复用的双向字节流。"""

    def __init__(self, gateway: "RemoteAccessGateway", state: _StreamState) -> None:
        self._gateway = gateway
        self._state = state
        self.metadata = state.metadata
        self._finished = False

    @property
    def device_id(self) -> int:
        return self._state.device_id

    @property
    def stream_id(self) -> int:
        return self._state.stream_id

    async def receive(self) -> bytes | None:
        item = await self._state.queue.get()
        if item is _STREAM_EOF:
            return None
        if isinstance(item, BaseException):
            raise item
        return item

    async def send(self, data: bytes) -> None:
        if not data:
            return
        await self._gateway.send_stream_data(self._state, data)

    async def control(self, action: str, **payload: Any) -> None:
        await self._gateway.send_stream_control(self._state, action, payload)

    async def finish(self, *, commit: bool = False, timeout: float = 15.0) -> dict[str, Any]:
        if self._finished:
            return {}
        try:
            result = await self._gateway.finish_stream(self._state, commit=commit, timeout=timeout)
        except BaseException:
            await self._gateway.abort_stream(self._state)
            self._finished = True
            raise
        self._finished = True
        return result

    async def abort(self) -> None:
        if self._finished:
            return
        self._finished = True
        await self._gateway.abort_stream(self._state)


class RemoteAccessGateway:
    """单进程后端使用的 Remote Access Agent 会话注册表。"""

    def __init__(self) -> None:
        self._state_lock = asyncio.Lock()
        self._sockets: dict[int, WebSocket] = {}
        self._send_locks: dict[int, asyncio.Lock] = {}
        self._next_ids: dict[int, int] = {}
        self._pending_requests: dict[tuple[int, int], asyncio.Future] = {}
        self._streams: dict[tuple[int, int], _StreamState] = {}
        self._capabilities: dict[int, dict[str, Any]] = {}
        self._last_seen: dict[int, float] = {}

    def is_connected(self, device_id: int) -> bool:
        return device_id in self._sockets

    def status(self, device_id: int) -> dict[str, Any]:
        capabilities = self._capabilities.get(device_id, {})
        return {
            "connected": self.is_connected(device_id),
            "capabilities": capabilities,
            "last_seen": self._last_seen.get(device_id),
        }

    async def register(self, device_id: int, websocket: WebSocket) -> None:
        pending: list[asyncio.Future] = []
        streams: list[_StreamState] = []
        async with self._state_lock:
            previous = self._sockets.get(device_id)
            self._sockets[device_id] = websocket
            self._send_locks[device_id] = asyncio.Lock()
            self._capabilities.pop(device_id, None)
            self._last_seen[device_id] = time()
            for key, future in list(self._pending_requests.items()):
                if key[0] == device_id:
                    pending.append(future)
                    self._pending_requests.pop(key, None)
            for key, state in list(self._streams.items()):
                if key[0] == device_id:
                    streams.append(state)
                    self._streams.pop(key, None)
        error = ConnectionError("车端远程访问连接已被新连接替换")
        self._fail_pending(pending, streams, error)
        if previous and previous is not websocket:
            try:
                await previous.close(code=4000, reason="replaced by a newer remote access agent")
            except RuntimeError:
                pass

    async def unregister(self, device_id: int, websocket: WebSocket) -> None:
        pending: list[asyncio.Future] = []
        streams: list[_StreamState] = []
        async with self._state_lock:
            if self._sockets.get(device_id) is not websocket:
                return
            self._sockets.pop(device_id, None)
            self._send_locks.pop(device_id, None)
            self._capabilities.pop(device_id, None)
            for key, future in list(self._pending_requests.items()):
                if key[0] == device_id:
                    pending.append(future)
                    self._pending_requests.pop(key, None)
            for key, state in list(self._streams.items()):
                if key[0] == device_id:
                    streams.append(state)
                    self._streams.pop(key, None)
        self._fail_pending(pending, streams, ConnectionError("车端远程访问连接已断开"))

    @staticmethod
    def _fail_pending(
        pending: list[asyncio.Future],
        streams: list[_StreamState],
        error: BaseException,
    ) -> None:
        for future in pending:
            if not future.done():
                future.set_exception(error)
        for state in streams:
            if not state.open_future.done():
                state.open_future.set_exception(error)
            if not state.close_future.done():
                state.close_future.set_exception(error)
            try:
                state.queue.put_nowait(error)
            except asyncio.QueueFull:
                pass

    async def _allocate_id(self, device_id: int) -> int:
        async with self._state_lock:
            value = self._next_ids.get(device_id, 0) + 1
            if value > 2_147_483_647:
                value = 1
            self._next_ids[device_id] = value
            return value

    async def _connection(self, device_id: int) -> tuple[WebSocket, asyncio.Lock]:
        async with self._state_lock:
            websocket = self._sockets.get(device_id)
            send_lock = self._send_locks.get(device_id)
        if websocket is None or send_lock is None:
            raise HTTPException(status_code=502, detail="无人设备远程访问 Agent 未连接")
        return websocket, send_lock

    async def _send_json(self, device_id: int, message: dict[str, Any]) -> None:
        websocket, send_lock = await self._connection(device_id)
        try:
            async with send_lock:
                await websocket.send_json(message)
        except Exception as exc:
            raise HTTPException(status_code=502, detail="车端远程访问连接发送失败") from exc

    async def request(
        self,
        device_id: int,
        action: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        request_id = await self._allocate_id(device_id)
        future = asyncio.get_running_loop().create_future()
        key = (device_id, request_id)
        async with self._state_lock:
            self._pending_requests[key] = future
        try:
            await self._send_json(device_id, {
                "type": "request",
                "id": request_id,
                "action": action,
                "payload": payload or {},
            })
            message = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise HTTPException(status_code=504, detail="车端文件操作响应超时") from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc) or "车端文件操作失败") from exc
        finally:
            async with self._state_lock:
                self._pending_requests.pop(key, None)

        if not message.get("ok"):
            status_code = int(message.get("status") or 502)
            if status_code < 400 or status_code > 599:
                status_code = 502
            raise HTTPException(status_code=status_code, detail=message.get("error") or "车端文件操作失败")
        result = message.get("result")
        return result if isinstance(result, dict) else {"value": result}

    async def open_stream(
        self,
        device_id: int,
        kind: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 10.0,
    ) -> RemoteStream:
        stream_id = await self._allocate_id(device_id)
        loop = asyncio.get_running_loop()
        state = _StreamState(
            device_id=device_id,
            stream_id=stream_id,
            kind=kind,
            open_future=loop.create_future(),
            close_future=loop.create_future(),
        )
        key = (device_id, stream_id)
        async with self._state_lock:
            self._streams[key] = state
        try:
            await self._send_json(device_id, {
                "type": "stream_open",
                "id": stream_id,
                "kind": kind,
                "params": params or {},
            })
            metadata = await asyncio.wait_for(state.open_future, timeout=timeout)
            if isinstance(metadata, dict):
                state.metadata.update(metadata)
            return RemoteStream(self, state)
        except asyncio.TimeoutError as exc:
            await self.abort_stream(state)
            raise HTTPException(status_code=504, detail="车端远程流建立超时") from exc
        except HTTPException:
            await self.abort_stream(state)
            raise
        except Exception as exc:
            await self.abort_stream(state)
            raise HTTPException(status_code=502, detail=str(exc) or "车端远程流建立失败") from exc

    async def send_stream_data(self, state: _StreamState, data: bytes) -> None:
        websocket, send_lock = await self._connection(state.device_id)
        packet = _BINARY_HEADER.pack(state.stream_id) + data
        try:
            async with send_lock:
                await websocket.send_bytes(packet)
        except Exception as exc:
            raise ConnectionError("车端远程流发送失败") from exc

    async def send_stream_control(
        self,
        state: _StreamState,
        action: str,
        payload: dict[str, Any],
    ) -> None:
        await self._send_json(state.device_id, {
            "type": "stream_control",
            "id": state.stream_id,
            "action": action,
            "payload": payload,
        })

    async def finish_stream(
        self,
        state: _StreamState,
        *,
        commit: bool,
        timeout: float,
    ) -> dict[str, Any]:
        key = (state.device_id, state.stream_id)
        async with self._state_lock:
            active = self._streams.get(key) is state
        if not active:
            if state.close_future.done() and not state.close_future.cancelled():
                try:
                    result = state.close_future.result()
                    return result if isinstance(result, dict) else {}
                except Exception as exc:
                    raise HTTPException(status_code=502, detail=str(exc)) from exc
            return {}

        try:
            await self._send_json(state.device_id, {
                "type": "stream_close",
                "id": state.stream_id,
                "commit": commit,
            })
            result = await asyncio.wait_for(state.close_future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise HTTPException(status_code=504, detail="车端远程流关闭确认超时") from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc) or "车端远程流关闭失败") from exc
        finally:
            async with self._state_lock:
                self._streams.pop(key, None)
        return result if isinstance(result, dict) else {}

    async def abort_stream(self, state: _StreamState) -> None:
        key = (state.device_id, state.stream_id)
        async with self._state_lock:
            active = self._streams.pop(key, None) is state
        if not active:
            return
        try:
            await self._send_json(state.device_id, {
                "type": "stream_close",
                "id": state.stream_id,
                "commit": False,
            })
        except Exception:
            pass

    async def handle_json(self, device_id: int, message: dict[str, Any]) -> None:
        self._last_seen[device_id] = time()
        message_type = message.get("type")
        if message_type == "hello":
            capabilities = message.get("capabilities")
            if isinstance(capabilities, dict):
                self._capabilities[device_id] = capabilities
            return
        if message_type == "heartbeat":
            return
        if message_type == "response":
            request_id = message.get("id")
            if not isinstance(request_id, int):
                return
            async with self._state_lock:
                future = self._pending_requests.get((device_id, request_id))
            if future is not None and not future.done():
                future.set_result(message)
            return

        stream_id = message.get("id")
        if not isinstance(stream_id, int):
            return
        key = (device_id, stream_id)
        async with self._state_lock:
            state = self._streams.get(key)
        if state is None:
            return

        if message_type == "stream_opened":
            metadata = message.get("meta")
            if not state.open_future.done():
                state.open_future.set_result(metadata if isinstance(metadata, dict) else {})
            return
        if message_type == "stream_error":
            status_code = int(message.get("status") or 502)
            if status_code < 400 or status_code > 599:
                status_code = 502
            error = HTTPException(
                status_code=status_code,
                detail=message.get("error") or "车端远程流异常",
            )
            if not state.open_future.done():
                state.open_future.set_exception(error)
            else:
                await state.queue.put(error)
            if not state.close_future.done():
                state.close_future.set_exception(error)
            async with self._state_lock:
                self._streams.pop(key, None)
            return
        if message_type == "stream_closed":
            ok = message.get("ok", True)
            result = message.get("result")
            if ok:
                if not state.close_future.done():
                    state.close_future.set_result(result if isinstance(result, dict) else {})
            else:
                status_code = int(message.get("status") or 502)
                if status_code < 400 or status_code > 599:
                    status_code = 502
                error = HTTPException(
                    status_code=status_code,
                    detail=message.get("error") or "车端远程流关闭失败",
                )
                if not state.close_future.done():
                    state.close_future.set_exception(error)
                await state.queue.put(error)
            await state.queue.put(_STREAM_EOF)
            async with self._state_lock:
                self._streams.pop(key, None)

    async def handle_binary(self, device_id: int, packet: bytes) -> None:
        self._last_seen[device_id] = time()
        if len(packet) < _BINARY_HEADER.size:
            return
        stream_id = _BINARY_HEADER.unpack_from(packet)[0]
        async with self._state_lock:
            state = self._streams.get((device_id, stream_id))
        if state is not None:
            await state.queue.put(packet[_BINARY_HEADER.size:])


remote_access_gateway = RemoteAccessGateway()
