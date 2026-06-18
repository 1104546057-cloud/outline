#!/usr/bin/env python3
"""TCP cmd_vel bridge for ROS1 (Noetic) wheeltec robot.

运动控制方式：通过 rospy 发布 geometry_msgs/Twist 到 /cmd_vel 话题，
由 wheeltec_robot_node 底层驱动节点订阅并执行。

依赖：
  - ROS Noetic 环境（source /opt/ros/noetic/setup.bash）
  - rospy, geometry_msgs（ROS 标准包）
"""


import json
import os
import re
import secrets
import signal
import socket
import subprocess
import time
from configparser import ConfigParser
from threading import Lock, Thread
from typing import Tuple

import rospy
from geometry_msgs.msg import Twist

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

# ROS Publisher（在 main 中初始化）
cmd_vel_pub = None  # type: rospy.Publisher | None

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
# ROS /cmd_vel 运动控制
# ---------------------------------------------------------------------------

def clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def send_cmd_to_motor(v: float, w: float) -> None:
    """通过 ROS 发布 Twist 消息到 /cmd_vel 话题来控制运动。

    参数:
        v: 线速度 (m/s)，正值前进，负值后退
        w: 角速度 (rad/s)，正值左转，负值右转
    """
    if cmd_vel_pub is None:
        print("[ROS] cmd_vel_pub 未初始化，跳过发送", flush=True)
        return

    twist = Twist()
    twist.linear.x = v
    twist.angular.z = w

    cmd_vel_pub.publish(twist)
    print(
        f"[ROS] /cmd_vel v={v:.3f} w={w:.3f}",
        flush=True,
    )


def hard_stop() -> None:
    global current_v, current_w
    current_v = 0.0
    current_w = 0.0
    send_cmd_to_motor(0.0, 0.0)


def watchdog_loop() -> None:
    global last_cmd_time
    while not rospy.is_shutdown():
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
    while not rospy.is_shutdown():
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
        while not rospy.is_shutdown():
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
    global cmd_vel_pub

    # 冷启动：加载配置
    load_conf()

    # 初始化 ROS 节点（anonymous=True 避免节点名冲突）
    rospy.init_node("robot_control_server", anonymous=True, disable_signals=True)
    print("[ROS] 节点 robot_control_server 已初始化", flush=True)

    # 创建 /cmd_vel 话题发布者
    # queue_size=1: 只保留最新指令，丢弃堆积的旧指令
    cmd_vel_pub = rospy.Publisher("/cmd_vel", Twist, queue_size=1)
    print("[ROS] /cmd_vel Publisher 已创建", flush=True)

    # 等待 Publisher 连接就绪（最多 5 秒）
    wait_start = time.time()
    while cmd_vel_pub.get_num_connections() == 0 and (time.time() - wait_start) < 5.0:
        if rospy.is_shutdown():
            return
        time.sleep(0.1)
    if cmd_vel_pub.get_num_connections() > 0:
        print(f"[ROS] /cmd_vel 已连接到 {cmd_vel_pub.get_num_connections()} 个订阅者", flush=True)
    else:
        print("[ROS] 警告: /cmd_vel 暂无订阅者（wheeltec_robot_node 可能未启动），但服务器将继续运行", flush=True)

    # 启动看门狗
    Thread(target=watchdog_loop, daemon=True).start()

    # 注册 SIGINT/SIGTERM 信号处理，优雅退出
    def _shutdown_handler(signum, frame):
        print(f"\n[MAIN] 收到信号 {signum}，正在停止...", flush=True)
        hard_stop()
        rospy.signal_shutdown("signal received")

    signal.signal(signal.SIGINT, _shutdown_handler)
    signal.signal(signal.SIGTERM, _shutdown_handler)

    # TCP 指令服务器
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, TCP_PORT))
    server.listen(1)
    server.settimeout(1.0)  # 允许定期检查 rospy.is_shutdown()
    print(f"[TCP] 指令服务监听在 {HOST}:{TCP_PORT}", flush=True)
    while not rospy.is_shutdown():
        try:
            conn, addr = server.accept()
            Thread(target=handle_client, args=(conn, addr), daemon=True).start()
        except socket.timeout:
            continue
        except OSError:
            break

    # 退出前确保停车
    hard_stop()
    print("[MAIN] 服务已停止", flush=True)


if __name__ == "__main__":
    main()
