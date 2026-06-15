"""
TCP 控制辅助模块

管理到树莓派控制服务的 TCP 连接池，提供消息收发、设备注册、
控制值限幅、设备在线状态更新等通用功能。
"""

import json
import socket
import time
import threading
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import Device
from config import ROBOT_CONTROL_TIMEOUT_SECONDS, DEVICE_ONLINE_TIMEOUT_SECONDS


# TCP 连接池（缓存到树莓派控制服务的 TCP 连接）
_robot_control_state: dict[str, Any] = {"connections": {}}
_robot_control_locks_lock = threading.Lock()
_robot_control_locks = {}


def _get_robot_lock(key: str) -> threading.Lock:
    with _robot_control_locks_lock:
        if key not in _robot_control_locks:
            _robot_control_locks[key] = threading.Lock()
        return _robot_control_locks[key]


def _target_key(host: str, port: int) -> str:
    """生成 TCP 连接缓存 key"""
    return f"{host}:{port}"


def _close_robot_socket(host: str, port: int) -> None:
    """关闭到指定目标的缓存 TCP 连接"""
    connections = _robot_control_state["connections"]
    key = _target_key(host, port)
    conn = connections.pop(key, None)
    if conn and conn.get("socket"):
        try:
            conn["socket"].close()
        except OSError:
            pass


def _get_robot_socket(host: str, port: int) -> socket.socket:
    """获取到树莓派控制服务的 TCP 连接（带缓存）"""
    connections = _robot_control_state["connections"]
    key = _target_key(host, port)
    conn = connections.get(key)
    if conn and conn.get("socket"):
        return conn["socket"]
    try:
        active_socket = socket.create_connection(
            (host, port),
            timeout=ROBOT_CONTROL_TIMEOUT_SECONDS,
        )
    except OSError as exc:
        raise HTTPException(status_code=502, detail=f"无人车控制服务不可达: {host}:{port}") from exc
    active_socket.settimeout(ROBOT_CONTROL_TIMEOUT_SECONDS)
    connections[key] = {"socket": active_socket, "buffer": b""}
    return active_socket


def _read_robot_message(active_socket: socket.socket, key: str) -> dict:
    """从 TCP 连接读取一条 JSON 消息"""
    connections = _robot_control_state["connections"]
    conn = connections.get(key, {"buffer": b""})
    buf = conn.get("buffer", b"")
    while b"\n" not in buf:
        chunk = active_socket.recv(4096)
        if not chunk:
            raise ConnectionError("无人车控制连接已断开。")
        buf += chunk
    line, buf = buf.split(b"\n", 1)
    conn["buffer"] = buf
    parsed = json.loads(line.decode("utf-8"))
    print(f"[{datetime.now()}] [TCP RECV] from {key} -> {parsed}", flush=True)
    return parsed


def _send_robot_message_once(host: str, port: int, payload: dict, expected_type: str) -> dict:
    """发送一条消息并等待预期类型的响应"""
    key = _target_key(host, port)
    active_socket = _get_robot_socket(host, port)
    data = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
    print(f"[{datetime.now()}] [TCP SEND] to {key} -> {payload}", flush=True)
    active_socket.sendall(data)
    deadline = time.time() + ROBOT_CONTROL_TIMEOUT_SECONDS
    while time.time() < deadline:
        message = _read_robot_message(active_socket, key)
        if message.get("type") == expected_type:
            return message
    _close_robot_socket(host, port)
    raise HTTPException(status_code=504, detail="无人车控制服务响应超时。")


def send_robot_control_message(host: str, port: int, payload: dict, expected_type: str) -> dict:
    """
    向树莓派控制服务发送消息并等待响应。
    支持缓存连接自动重连一次。
    """
    key = _target_key(host, port)
    lock = _get_robot_lock(key)
    with lock:
        has_cached = key in _robot_control_state["connections"]
        for attempt in range(2 if has_cached else 1):
            try:
                return _send_robot_message_once(host, port, payload, expected_type)
            except HTTPException:
                raise
            except (ConnectionError, OSError, json.JSONDecodeError):
                _close_robot_socket(host, port)
                if attempt == 0 and has_cached:
                    continue
                raise HTTPException(status_code=502, detail="无人车控制服务响应异常。")
    raise HTTPException(status_code=502, detail="无人车控制服务响应异常。")


def normalize_control_value(value: Any, limit: float, field: str) -> float:
    """对控制值进行限幅"""
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{field} 必须是数字。") from exc
    return max(-limit, min(limit, parsed))


def register_device_tcp(host: str, port: int, register_payload: dict) -> dict:
    """
    通过独立的 TCP 连接向设备 robot_control_server 发送 register 消息并读取响应。

    注册流程（参照 robot_control_server.py 的 handle_client）：
    1. 建立 TCP 连接
    2. 发送 {"type":"register", "password":"...", "server_address":"..."}\\n
    3. 读取 {"type":"register_result", "ok":true/false, "token":"...", ...}\\n
    4. 关闭连接

    不复用连接池，因为注册只在添加设备时执行一次。
    """
    try:
        sock = socket.create_connection((host, port), timeout=ROBOT_CONTROL_TIMEOUT_SECONDS)
    except OSError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"无法连接到设备 {host}:{port}，请检查设备是否在线",
        ) from exc

    try:
        sock.settimeout(ROBOT_CONTROL_TIMEOUT_SECONDS + 2)
        # 发送 register 消息
        data = (json.dumps(register_payload, separators=(",", ":")) + "\n").encode("utf-8")
        print(f"[{datetime.now()}] [TCP SEND] to {host}:{port} (Register) -> {register_payload}", flush=True)
        sock.sendall(data)

        # 读取响应
        buf = b""
        deadline = time.time() + ROBOT_CONTROL_TIMEOUT_SECONDS + 2
        while b"\n" not in buf:
            if time.time() > deadline:
                raise HTTPException(status_code=504, detail="设备注册响应超时")
            chunk = sock.recv(4096)
            if not chunk:
                raise HTTPException(status_code=502, detail="设备连接在等待注册响应时断开")
            buf += chunk

        line, _ = buf.split(b"\n", 1)
        response = json.loads(line.decode("utf-8"))
        print(f"[{datetime.now()}] [TCP RECV] from {host}:{port} (Register) -> {response}", flush=True)
        return response
    finally:
        try:
            sock.close()
        except OSError:
            pass


def resolve_device_target(device_id: int, db: Session) -> tuple[str, int]:
    """解析设备的控制目标（IP 和端口）"""
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    if not device.ip_address:
        raise HTTPException(status_code=422, detail="设备未配置 IP 地址，无法控制。")
    return device.ip_address, device.port or 9000


def update_device_online_status(db: Session) -> None:
    """根据 last_seen 更新设备在线状态"""
    cutoff = datetime.now() - timedelta(seconds=DEVICE_ONLINE_TIMEOUT_SECONDS)
    # 将超时未上报的设备标记为离线
    db.query(Device).filter(
        Device.last_seen != None,
        Device.last_seen < cutoff,
        Device.status == "online"
    ).update({"status": "offline"}, synchronize_session="fetch")
    # 将从未上报过，但添加时间已经超过超时的设备标记为离线
    db.query(Device).filter(
        Device.last_seen == None,
        Device.created_at < cutoff,
        Device.status == "online"
    ).update({"status": "offline"}, synchronize_session="fetch")
    db.commit()
