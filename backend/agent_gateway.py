"""Manage outbound vehicle-agent control and media WebSocket sessions."""

import asyncio
import queue
from collections import defaultdict
from dataclasses import dataclass
from time import time
from typing import Any

from fastapi import HTTPException, WebSocket


VALID_MEDIA_VIEWS = {"color", "depth", "lidar"}


@dataclass(frozen=True)
class MediaFrame:
    data: bytes
    timestamp_ms: int
    received_at: float


class AgentGateway:
    """In-memory registry used by the single-process prototype backend."""

    def __init__(self) -> None:
        self._state_lock = asyncio.Lock()
        self._control_sockets: dict[int, WebSocket] = {}
        self._media_sockets: dict[int, WebSocket] = {}
        self._control_send_locks: dict[int, asyncio.Lock] = {}
        self._media_send_locks: dict[int, asyncio.Lock] = {}
        self._next_command_ids: dict[int, int] = defaultdict(int)
        self._pending_commands: dict[tuple[int, int], asyncio.Future] = {}
        self._stream_consumers: dict[tuple[int, str], int] = defaultdict(int)
        self._async_frame_queues: dict[tuple[int, str], set[asyncio.Queue]] = defaultdict(set)
        self._thread_frame_queues: dict[tuple[int, str], set[queue.Queue]] = defaultdict(set)
        self._latest_frames: dict[tuple[int, str], MediaFrame] = {}

    async def register_control(self, device_id: int, websocket: WebSocket) -> None:
        async with self._state_lock:
            previous = self._control_sockets.get(device_id)
            self._control_sockets[device_id] = websocket
            self._control_send_locks.setdefault(device_id, asyncio.Lock())
        if previous and previous is not websocket:
            try:
                await previous.close(code=4000, reason="replaced by a newer agent connection")
            except RuntimeError:
                pass

    async def unregister_control(self, device_id: int, websocket: WebSocket) -> None:
        pending: list[asyncio.Future] = []
        async with self._state_lock:
            if self._control_sockets.get(device_id) is not websocket:
                return
            self._control_sockets.pop(device_id, None)
            for key, future in list(self._pending_commands.items()):
                if key[0] == device_id:
                    pending.append(future)
                    self._pending_commands.pop(key, None)
        for future in pending:
            if not future.done():
                future.set_exception(ConnectionError("车端控制连接已断开"))

    async def register_media(self, device_id: int, websocket: WebSocket) -> None:
        async with self._state_lock:
            previous = self._media_sockets.get(device_id)
            self._media_sockets[device_id] = websocket
            self._media_send_locks.setdefault(device_id, asyncio.Lock())
            active_views = [
                view
                for (current_device_id, view), count in self._stream_consumers.items()
                if current_device_id == device_id and count > 0
            ]
        if previous and previous is not websocket:
            try:
                await previous.close(code=4000, reason="replaced by a newer agent connection")
            except RuntimeError:
                pass
        for view in active_views:
            await self._send_media_message(device_id, {"type": "stream_start", "view": view})

    async def unregister_media(self, device_id: int, websocket: WebSocket) -> None:
        async with self._state_lock:
            if self._media_sockets.get(device_id) is websocket:
                self._media_sockets.pop(device_id, None)

    def is_control_connected(self, device_id: int) -> bool:
        return device_id in self._control_sockets

    def is_media_connected(self, device_id: int) -> bool:
        return device_id in self._media_sockets

    async def send_command(
        self,
        device_id: int,
        command: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        async with self._state_lock:
            websocket = self._control_sockets.get(device_id)
            if websocket is None:
                raise HTTPException(status_code=502, detail="无人车控制通道未连接")
            command_id = self._next_command_ids[device_id] + 1
            if command_id > 2_147_483_647:
                command_id = 1
            self._next_command_ids[device_id] = command_id
            future = asyncio.get_running_loop().create_future()
            self._pending_commands[(device_id, command_id)] = future
            send_lock = self._control_send_locks[device_id]

        try:
            async with send_lock:
                await websocket.send_json({"type": "command", "id": command_id, "command": command})
            result = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise HTTPException(status_code=504, detail="无人车控制指令响应超时") from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc) or "无人车控制连接异常") from exc
        finally:
            async with self._state_lock:
                self._pending_commands.pop((device_id, command_id), None)

        if not result.get("ok"):
            raise HTTPException(status_code=502, detail=result.get("error") or "无人车拒绝执行指令")
        response = result.get("response")
        return response if isinstance(response, dict) else result

    async def resolve_command(self, device_id: int, message: dict[str, Any]) -> None:
        command_id = message.get("id")
        if not isinstance(command_id, int):
            return
        async with self._state_lock:
            future = self._pending_commands.get((device_id, command_id))
        if future and not future.done():
            future.set_result(message)

    async def _send_media_message(self, device_id: int, message: dict[str, Any]) -> None:
        async with self._state_lock:
            websocket = self._media_sockets.get(device_id)
            send_lock = self._media_send_locks.get(device_id)
        if websocket is None or send_lock is None:
            raise HTTPException(status_code=502, detail="无人车媒体通道未连接")
        try:
            async with send_lock:
                await websocket.send_json(message)
        except Exception as exc:
            raise HTTPException(status_code=502, detail="无人车媒体通道已断开") from exc

    async def _acquire_stream(self, device_id: int, view: str) -> None:
        if view not in VALID_MEDIA_VIEWS:
            raise HTTPException(status_code=422, detail="不支持的视频视图")
        async with self._state_lock:
            if device_id not in self._media_sockets:
                raise HTTPException(status_code=502, detail="无人车媒体通道未连接")
            key = (device_id, view)
            should_start = self._stream_consumers[key] == 0
            self._stream_consumers[key] += 1
        if should_start:
            try:
                await self._send_media_message(device_id, {"type": "stream_start", "view": view})
            except Exception:
                async with self._state_lock:
                    self._stream_consumers[key] = max(0, self._stream_consumers[key] - 1)
                raise

    async def _release_stream(self, device_id: int, view: str) -> None:
        key = (device_id, view)
        async with self._state_lock:
            current = self._stream_consumers.get(key, 0)
            if current <= 1:
                self._stream_consumers.pop(key, None)
                should_stop = True
            else:
                self._stream_consumers[key] = current - 1
                should_stop = False
            media_connected = device_id in self._media_sockets
        if should_stop and media_connected:
            try:
                await self._send_media_message(device_id, {"type": "stream_stop", "view": view})
            except HTTPException:
                pass

    async def subscribe_frames(self, device_id: int, view: str) -> asyncio.Queue:
        await self._acquire_stream(device_id, view)
        frame_queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        async with self._state_lock:
            self._async_frame_queues[(device_id, view)].add(frame_queue)
        return frame_queue

    async def unsubscribe_frames(self, device_id: int, view: str, frame_queue: asyncio.Queue) -> None:
        async with self._state_lock:
            queues = self._async_frame_queues.get((device_id, view))
            if queues is not None:
                queues.discard(frame_queue)
                if not queues:
                    self._async_frame_queues.pop((device_id, view), None)
        await self._release_stream(device_id, view)

    async def subscribe_thread_frames(self, device_id: int, view: str) -> queue.Queue:
        await self._acquire_stream(device_id, view)
        frame_queue: queue.Queue = queue.Queue(maxsize=1)
        async with self._state_lock:
            self._thread_frame_queues[(device_id, view)].add(frame_queue)
        return frame_queue

    async def unsubscribe_thread_frames(self, device_id: int, view: str, frame_queue: queue.Queue) -> None:
        async with self._state_lock:
            queues = self._thread_frame_queues.get((device_id, view))
            if queues is not None:
                queues.discard(frame_queue)
                if not queues:
                    self._thread_frame_queues.pop((device_id, view), None)
        await self._release_stream(device_id, view)

    async def publish_frame(self, device_id: int, view: str, data: bytes, timestamp_ms: int) -> None:
        key = (device_id, view)
        frame = MediaFrame(data=data, timestamp_ms=timestamp_ms, received_at=time())
        async with self._state_lock:
            self._latest_frames[key] = frame
            async_queues = list(self._async_frame_queues.get(key, ()))
            thread_queues = list(self._thread_frame_queues.get(key, ()))
        for frame_queue in async_queues:
            if frame_queue.full():
                try:
                    frame_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            frame_queue.put_nowait(frame)
        for frame_queue in thread_queues:
            if frame_queue.full():
                try:
                    frame_queue.get_nowait()
                except queue.Empty:
                    pass
            try:
                frame_queue.put_nowait(frame)
            except queue.Full:
                pass


agent_gateway = AgentGateway()
