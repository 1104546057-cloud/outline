#!/usr/bin/env python3
"""Outbound WebSocket agent for serial motor control and USB camera relay."""

import argparse
import asyncio
import inspect
import json
import logging
import signal
import struct
import threading
import time
import urllib.parse
import urllib.request
from configparser import ConfigParser
from pathlib import Path
from typing import Tuple

import serial
import websockets

# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "iot_client.conf"
CMD_TIMEOUT_SEC = 0.5
SERIAL_PORT = "/dev/ttyACM0"
BAUDRATE = 115200
MAX_LINEAR = 3.0
MAX_ANGULAR = 2.0
RECONNECT_DELAY_MAX_SEC = 2
WEBSOCKET_OPEN_TIMEOUT_SEC = 5
WEBSOCKET_PING_INTERVAL_SEC = 5
WEBSOCKET_PING_TIMEOUT_SEC = 5
MEDIA_SEND_TIMEOUT_SEC = 3
LOCAL_CAMERA_URL = "http://127.0.0.1:8080/?action=stream"
MEDIA_HEADER = struct.Struct("!BQ")
MEDIA_VIEW_CODE = 1

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("robot_agent")

# ---------------------------------------------------------------------------
# 全局状态
# ---------------------------------------------------------------------------
state_lock = threading.Lock()
last_cmd_time = 0.0
current_v = 0.0
current_w = 0.0
ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=1)


def load_config(config_path: Path) -> Tuple[str, str]:
    parser = ConfigParser()
    parser.read(str(config_path), encoding="utf-8")
    server = parser.get("client", "server", fallback="").strip().rstrip("/")
    token = parser.get("client", "token", fallback="").strip()
    if not server:
        raise RuntimeError(f"未在 {config_path} 中配置 server")
    if not token or token == "YOUR_DEVICE_TOKEN_HERE":
        raise RuntimeError(f"未在 {config_path} 中配置有效 token")
    return server, token


def websocket_url(server: str, channel: str) -> str:
    parsed = urllib.parse.urlsplit(server)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise RuntimeError(f"无效的服务器地址: {server}")
    scheme = "wss" if parsed.scheme == "https" else "ws"
    base_path = parsed.path.rstrip("/")
    return urllib.parse.urlunsplit(
        (scheme, parsed.netloc, f"{base_path}/api/agent/ws/{channel}", "", "")
    )


def connect_websocket(url: str, token: str):
    """兼容 websockets 旧版 extra_headers 与新版 additional_headers。"""
    try:
        parameters = inspect.signature(websockets.connect).parameters
    except (TypeError, ValueError):
        parameters = {}
    header_arg = "additional_headers" if "additional_headers" in parameters else "extra_headers"
    open_timeout_arg = "open_timeout" if "open_timeout" in parameters else "timeout"
    return websockets.connect(
        url,
        **{
            header_arg: {"X-Device-Token": token},
            open_timeout_arg: WEBSOCKET_OPEN_TIMEOUT_SEC,
            "ping_interval": WEBSOCKET_PING_INTERVAL_SEC,
            "ping_timeout": WEBSOCKET_PING_TIMEOUT_SEC,
            "close_timeout": 1,
        },
    )


# ---------------------------------------------------------------------------
# 串口 / 电机控制
# ---------------------------------------------------------------------------

def split_i16(value: int) -> Tuple[int, int]:
    normalized = value & 0xFFFF
    return (normalized >> 8) & 0xFF, normalized & 0xFF


def clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def motor_packet(v: float, w: float) -> bytes:
    tx = [0x7B, 0x00, 0x00, 0, 0, 0, 0, 0, 0]
    v_i16 = int(clamp(v, MAX_LINEAR) * 1000)
    w_i16 = int(clamp(w, MAX_ANGULAR) * 1000)
    tx[3], tx[4] = split_i16(v_i16)
    tx[7], tx[8] = split_i16(w_i16)
    checksum = 0
    for byte in tx:
        checksum ^= byte
    return bytes(tx + [checksum, 0x7D])


def send_cmd_to_motor(v: float, w: float) -> None:
    packet = motor_packet(v, w)
    written = ser.write(packet)
    packet_hex = " ".join(f"{byte:02x}" for byte in packet)
    print(
        f"[SERIAL] v={v:.3f} w={w:.3f} bytes={written} packet={packet_hex}",
        flush=True,
    )


def hard_stop() -> None:
    global current_v, current_w
    with state_lock:
        current_v = 0.0
        current_w = 0.0
    send_cmd_to_motor(0.0, 0.0)


def watchdog_loop() -> None:
    global last_cmd_time
    while True:
        time.sleep(0.05)
        should_stop = False
        with state_lock:
            if last_cmd_time > 0 and time.time() - last_cmd_time > CMD_TIMEOUT_SEC:
                last_cmd_time = 0.0
                should_stop = True
        if should_stop:
            log.warning("控制指令超时，执行停车")
            hard_stop()


# ---------------------------------------------------------------------------
def execute_command(command: dict) -> dict:
    global current_v, current_w, last_cmd_time
    now = int(time.time())
    command_type = command.get("type")
    if command_type == "ping":
        return {"type": "pong", "ok": True, "ts": now}
    if command_type == "stop":
        with state_lock:
            last_cmd_time = 0.0
        hard_stop()
        return {"type": "ack", "ok": True, "ts": now}
    if command_type == "cmd_vel":
        try:
            v = clamp(float(command.get("v", 0.0)), MAX_LINEAR)
            w = clamp(float(command.get("w", 0.0)), MAX_ANGULAR)
        except (TypeError, ValueError) as exc:
            return {"type": "ack", "ok": False, "error": str(exc), "ts": now}
        send_cmd_to_motor(v, w)
        with state_lock:
            last_cmd_time = time.time()
            current_v = v
            current_w = w
        return {"type": "ack", "ok": True, "v": v, "w": w, "ts": now}
    return {"type": "ack", "ok": False, "error": "unknown_type", "ts": now}


async def control_session(url: str, token: str) -> None:
    async with connect_websocket(url, token) as websocket:
        log.info("控制通道已连接")
        try:
            while True:
                try:
                    raw_message = await asyncio.wait_for(websocket.recv(), timeout=10)
                except asyncio.TimeoutError:
                    await websocket.send(json.dumps({"type": "heartbeat", "ts": int(time.time())}))
                    continue
                if not isinstance(raw_message, str):
                    continue
                message = json.loads(raw_message)
                if message.get("type") != "command" or not isinstance(message.get("id"), int):
                    continue
                command_id = message["id"]
                try:
                    response = execute_command(message.get("command") or {})
                    result = {
                        "type": "result",
                        "id": command_id,
                        "ok": bool(response.get("ok")),
                        "response": response,
                    }
                    if not response.get("ok"):
                        result["error"] = response.get("error") or "command_failed"
                except Exception as exc:
                    hard_stop()
                    result = {"type": "result", "id": command_id, "ok": False, "error": str(exc)}
                await websocket.send(json.dumps(result, separators=(",", ":")))
        finally:
            hard_stop()
            log.warning("控制通道已断开，车辆已停车")


async def control_loop(url: str, token: str) -> None:
    delay = 1
    while True:
        try:
            await control_session(url, token)
            delay = 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            hard_stop()
            log.error("控制通道连接失败: %s；%s 秒后重试", exc, delay)
            await asyncio.sleep(delay)
            delay = min(RECONNECT_DELAY_MAX_SEC, delay * 2)


async def send_media_frame(websocket, send_lock: asyncio.Lock, jpeg: bytes) -> None:
    payload = MEDIA_HEADER.pack(MEDIA_VIEW_CODE, int(time.time() * 1000)) + jpeg
    async with send_lock:
        try:
            await asyncio.wait_for(websocket.send(payload), timeout=MEDIA_SEND_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            await websocket.close(code=1011, reason="media send timeout")
            raise


def media_stream_worker(
    stop_event: threading.Event,
    loop: asyncio.AbstractEventLoop,
    websocket,
    send_lock: asyncio.Lock,
) -> None:
    while not stop_event.is_set():
        try:
            request = urllib.request.Request(LOCAL_CAMERA_URL, headers={"Connection": "close"})
            with urllib.request.urlopen(request, timeout=5) as response:
                buffer = bytearray()
                while not stop_event.is_set():
                    chunk = response.read(8192)
                    if not chunk:
                        raise ConnectionError("本机摄像头流已结束")
                    buffer.extend(chunk)
                    while not stop_event.is_set():
                        start = buffer.find(b"\xff\xd8")
                        if start < 0:
                            if len(buffer) > 1:
                                del buffer[:-1]
                            break
                        end = buffer.find(b"\xff\xd9", start + 2)
                        if end < 0:
                            if start > 0:
                                del buffer[:start]
                            if len(buffer) > 5 * 1024 * 1024:
                                buffer.clear()
                            break
                        end += 2
                        jpeg = bytes(buffer[start:end])
                        del buffer[:end]
                        future = asyncio.run_coroutine_threadsafe(
                            send_media_frame(websocket, send_lock, jpeg), loop
                        )
                        try:
                            future.result(timeout=5)
                        except Exception:
                            future.cancel()
                            raise
        except Exception as exc:
            if stop_event.is_set():
                break
            log.warning("彩色媒体流读取失败: %s；2 秒后重试", exc)
            stop_event.wait(2)


async def media_session(url: str, token: str) -> None:
    worker = None
    stop_event = None
    loop = asyncio.get_event_loop()
    send_lock = asyncio.Lock()
    async with connect_websocket(url, token) as websocket:
        log.info("媒体通道已连接")
        try:
            while True:
                raw_message = await websocket.recv()
                if not isinstance(raw_message, str):
                    continue
                message = json.loads(raw_message)
                if message.get("view") != "color":
                    continue
                if message.get("type") == "stream_start":
                    if worker and worker.is_alive():
                        continue
                    stop_event = threading.Event()
                    worker = threading.Thread(
                        target=media_stream_worker,
                        args=(stop_event, loop, websocket, send_lock),
                        name="media-color",
                        daemon=True,
                    )
                    worker.start()
                    log.info("开始上传彩色媒体流")
                elif message.get("type") == "stream_stop" and stop_event:
                    stop_event.set()
                    worker = None
                    stop_event = None
                    log.info("停止上传彩色媒体流")
        finally:
            if stop_event:
                stop_event.set()
            log.warning("媒体通道已断开")


async def media_loop(url: str, token: str) -> None:
    delay = 1
    while True:
        try:
            await media_session(url, token)
            delay = 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("媒体通道连接失败: %s；%s 秒后重试", exc, delay)
            await asyncio.sleep(delay)
            delay = min(RECONNECT_DELAY_MAX_SEC, delay * 2)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

async def run_agent(server: str, token: str) -> None:
    shutdown_event = asyncio.Event()
    loop = asyncio.get_event_loop()

    def request_shutdown() -> None:
        hard_stop()
        shutdown_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, request_shutdown)
    tasks = [
        asyncio.ensure_future(control_loop(websocket_url(server, "control"), token)),
        asyncio.ensure_future(media_loop(websocket_url(server, "media"), token)),
    ]
    await shutdown_event.wait()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="DevicesWebControl outbound agent")
    parser.add_argument("--config", default=str(CONFIG_FILE))
    args = parser.parse_args()
    server, token = load_config(Path(args.config))
    threading.Thread(target=watchdog_loop, name="control-watchdog", daemon=True).start()
    log.info("Agent 启动，公网入口: %s", server)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_agent(server, token))
    finally:
        hard_stop()
        ser.close()
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


if __name__ == "__main__":
    main()
