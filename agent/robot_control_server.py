#!/usr/bin/env python3
"""TCP cmd_vel bridge for the Raspberry Pi motor controller."""


import json
import os
import re
import secrets
import socket
import subprocess
import time
from configparser import ConfigParser
from threading import Lock, Thread
from typing import Tuple

import serial

# ---------------------------------------------------------------------------
# 配置文件路径
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONF_PATH = os.path.join(SCRIPT_DIR, "robot_control_server.conf")
IOT_CONF_PATH = os.path.join(SCRIPT_DIR, "iot_client.conf")

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
HOST = "0.0.0.0"
TCP_PORT = 9000
CMD_TIMEOUT_SEC = 0.5
STATUS_PERIOD_SEC = 1.0
SERIAL_PORT = "/dev/ttyACM0"
BAUDRATE = 115200
MAX_LINEAR = 0.6
MAX_ANGULAR = 2.0

IOT_SERVICE_NAME = "DevicesWebControl-iot_client"

# ---------------------------------------------------------------------------
# 全局状态
# ---------------------------------------------------------------------------
lock = Lock()
last_cmd_time = 0.0
current_v = 0.0
current_w = 0.0
ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=1)

# ---------------------------------------------------------------------------
# 鉴权状态
# ---------------------------------------------------------------------------
_password: str = ""


def _replace_conf_value(filepath: str, key: str, new_value: str) -> None:
    """在 INI 配置文件中原地替换某个 key 的值，保留注释和格式。"""
    pattern = re.compile(
        rf"^(\s*{re.escape(key)}\s*=\s*)(.*)$", re.MULTILINE
    )
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    new_content, n = pattern.subn(rf"\g<1>{new_value}", content)
    if n == 0:
        raise ValueError(f"在 {filepath} 中未找到 key: {key}")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_content)


def load_conf() -> None:
    """冷启动时从配置文件加载 password。"""
    global _password
    cfg = ConfigParser()
    cfg.read(CONF_PATH, encoding="utf-8")
    _password = cfg.get("server", "password", fallback="").strip()


def update_iot_conf(token: str, server_address: str) -> None:
    """将 token 和后端服务器地址写入 iot_client.conf（保留注释）。"""
    _replace_conf_value(IOT_CONF_PATH, "token", token)
    _replace_conf_value(IOT_CONF_PATH, "server", server_address)
    print(f"[AUTH] token 和 server 已写入 {IOT_CONF_PATH}", flush=True)


def restart_iot_service() -> None:
    """重启 DevicesWebControl-iot_client 系统服务。"""
    try:
        subprocess.run(
            ["sudo", "systemctl", "restart", IOT_SERVICE_NAME],
            check=True,
            timeout=15,
        )
        print(f"[AUTH] 已重启系统服务: {IOT_SERVICE_NAME}", flush=True)
    except Exception as exc:
        print(f"[AUTH] 重启服务 {IOT_SERVICE_NAME} 失败: {exc}", flush=True)


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
    current_v = 0.0
    current_w = 0.0
    send_cmd_to_motor(0.0, 0.0)


def watchdog_loop() -> None:
    global last_cmd_time
    while True:
        time.sleep(0.05)
        with lock:
            expired = last_cmd_time > 0 and (time.time() - last_cmd_time) > CMD_TIMEOUT_SEC
            if expired:
                last_cmd_time = 0
                print("[SAFE] cmd timeout -> STOP", flush=True)
                hard_stop()


# ---------------------------------------------------------------------------
# TCP 指令服务
# ---------------------------------------------------------------------------

def send_json_line(conn: socket.socket, obj: dict) -> None:
    data = (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")
    conn.sendall(data)


def status_loop(conn: socket.socket) -> None:
    while True:
        time.sleep(STATUS_PERIOD_SEC)
        try:
            send_json_line(conn, {"type": "status", "motor": "ok", "v": current_v, "w": current_w, "ts": int(time.time())})
        except OSError:
            return


def handle_command(conn: socket.socket, msg: dict) -> None:
    global current_v, current_w, last_cmd_time
    now = time.time()
    mtype = msg.get("type")
    if mtype == "ping":
        send_json_line(conn, {"type": "pong", "ts": int(now)})
        return
    if mtype == "stop":
        with lock:
            last_cmd_time = now
        hard_stop()
        send_json_line(conn, {"type": "ack", "ok": True, "ts": int(now)})
        return
    if mtype == "cmd_vel":
        v = clamp(float(msg.get("v", 0.0)), MAX_LINEAR)
        w = clamp(float(msg.get("w", 0.0)), MAX_ANGULAR)
        with lock:
            last_cmd_time = now
            current_v = v
            current_w = w
        send_cmd_to_motor(v, w)
        send_json_line(conn, {"type": "ack", "ok": True, "ts": int(now)})
        return
    send_json_line(conn, {"type": "ack", "ok": False, "err": "unknown_type", "ts": int(now)})


def handle_client(conn: socket.socket, addr: Tuple[str, int]) -> None:
    """处理 TCP 客户端连接。
    无 token 鉴权，支持 register 和其他控制指令。
    """
    print("connected:", addr, flush=True)
    conn.settimeout(2.0)
    buf = b""

    Thread(target=status_loop, args=(conn,), daemon=True).start()

    try:
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip():
                    continue
                msg = json.loads(line.decode("utf-8"))
                mtype = msg.get("type")

                # ---- register ----
                if mtype == "register":
                    password = str(msg.get("password", ""))
                    server_address = str(msg.get("server_address", "")).strip()

                    if not password or not server_address:
                        send_json_line(conn, {"type": "register_result", "ok": False, "err": "password 和 server_address 为必填项", "ts": int(time.time())})
                        continue

                    if not secrets.compare_digest(password, _password):
                        send_json_line(conn, {"type": "register_result", "ok": False, "err": "密码错误", "ts": int(time.time())})
                        print(f"[AUTH] {addr} 注册失败：密码错误", flush=True)
                        continue

                    # 生成新 token
                    new_token = secrets.token_hex(32)

                    # 1) 写入 iot_client.conf
                    update_iot_conf(new_token, server_address)

                    # 2) 异步重启 iot_client 服务
                    Thread(target=restart_iot_service, daemon=True).start()

                    send_json_line(conn, {
                        "type": "register_result",
                        "ok": True,
                        "token": new_token,
                        "message": f"注册成功，{IOT_SERVICE_NAME} 服务正在重启",
                        "ts": int(time.time()),
                    })
                    print(f"[AUTH] {addr} 注册成功，token 已更新", flush=True)
                else:
                    # 其他正常指令
                    handle_command(conn, msg)

    except Exception as exc:
        print("client error:", exc, flush=True)
    finally:
        print("disconnected:", addr, flush=True)
        hard_stop()
        conn.close()


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main() -> None:
    # 冷启动：加载配置
    load_conf()

    # 启动看门狗
    Thread(target=watchdog_loop, daemon=True).start()

    # TCP 指令服务器
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, TCP_PORT))
    server.listen(1)
    print(f"[TCP] 指令服务监听在 {HOST}:{TCP_PORT}", flush=True)
    while True:
        conn, addr = server.accept()
        Thread(target=handle_client, args=(conn, addr), daemon=True).start()


if __name__ == "__main__":
    main()

