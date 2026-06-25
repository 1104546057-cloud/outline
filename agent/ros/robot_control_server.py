#!/usr/bin/env python3
"""Outbound WebSocket agent for ROS1 wheeltec control and media relay."""

import argparse
import asyncio
import base64
import json
import logging
import math
import os
import signal
import struct
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from configparser import ConfigParser
from pathlib import Path
from typing import Dict, Tuple

import rospy
import websockets
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped, Twist


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "iot_client.conf"
CMD_TIMEOUT_SEC = 0.5
MAX_LINEAR = 3.0
MAX_ANGULAR = 2.0
RECONNECT_DELAY_MAX_SEC = 2
WEBSOCKET_OPEN_TIMEOUT_SEC = 5
WEBSOCKET_PING_INTERVAL_SEC = 5
WEBSOCKET_PING_TIMEOUT_SEC = 5
MEDIA_SEND_TIMEOUT_SEC = 3
LOCAL_CAMERA_URL = "http://127.0.0.1:8080/?action=stream&view={view}"
MEDIA_HEADER = struct.Struct("!BQ")
MEDIA_VIEW_CODES = {"color": 1, "depth": 2, "lidar": 3}
SLAM_MAP_DIR = Path(os.environ.get("DWC_SLAM_MAP_DIR", "/home/wheeltec/Dong/DevicesWebControl/slam_map"))
NAV_LOG_FILE = Path(os.environ.get("DWC_NAV_LOG_FILE", "/tmp/devices_web_control_navigation.log"))
NAV_PREVIEW_MAX_SIZE = int(os.environ.get("DWC_NAV_PREVIEW_MAX_SIZE", "1000"))
ROS_SETUP = os.environ.get("DWC_ROS_SETUP", "/opt/ros/noetic/setup.bash")
LIDAR_SETUP = os.environ.get("DWC_LIDAR_SETUP", "/home/wheeltec/wheeltec_lidar/devel/setup.bash")
WHEELTEC_SETUP = os.environ.get("DWC_WHEELTEC_SETUP", "/home/wheeltec/wheeltec_robot/devel/setup.bash")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("robot_agent")

state_lock = threading.Lock()
last_cmd_time = 0.0
current_v = 0.0
current_w = 0.0
cmd_vel_pub = None
simple_goal_pub = None
nav_lock = threading.Lock()
nav_process = None
nav_map_name = None
nav_pose_lock = threading.Lock()
nav_pose = None
nav_pose_time = 0.0


def configure_local_ros_network() -> None:
    """Advertise a reachable local address for this single-host vehicle ROS graph."""
    master_uri = os.environ.get("ROS_MASTER_URI", "http://localhost:11311")
    ros_ip = os.environ.get("DWC_ROS_IP", "127.0.0.1").strip() or "127.0.0.1"
    os.environ.pop("ROS_HOSTNAME", None)
    os.environ["ROS_IP"] = ros_ip
    log.info(
        "ROS 网络环境 master=%s ROS_IP=%s ROS_HOSTNAME=%s",
        master_uri,
        os.environ.get("ROS_IP", ""),
        os.environ.get("ROS_HOSTNAME", ""),
    )


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


def clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def send_cmd_to_motor(v: float, w: float, require_subscriber: bool = True) -> int:
    if cmd_vel_pub is None:
        raise RuntimeError("ROS /cmd_vel Publisher 尚未初始化")
    subscriber_count = cmd_vel_pub.get_num_connections()
    if require_subscriber and subscriber_count <= 0:
        raise RuntimeError("ROS /cmd_vel 没有订阅者，请检查 wheeltec_robot_node 是否运行")
    twist = Twist()
    twist.linear.x = v
    twist.angular.z = w
    cmd_vel_pub.publish(twist)
    log.info(
        "发布 /cmd_vel v=%.3f w=%.3f subscribers=%s",
        v,
        w,
        subscriber_count,
    )
    return subscriber_count


def hard_stop() -> None:
    global current_v, current_w
    with state_lock:
        current_v = 0.0
        current_w = 0.0
    if cmd_vel_pub is not None:
        send_cmd_to_motor(0.0, 0.0, require_subscriber=False)


def quaternion_to_yaw(z: float, w: float) -> float:
    return math.atan2(2.0 * w * z, 1.0 - 2.0 * z * z)


def on_amcl_pose(msg: PoseWithCovarianceStamped) -> None:
    global nav_pose, nav_pose_time
    pose = msg.pose.pose
    with nav_pose_lock:
        nav_pose = {
            "frame_id": msg.header.frame_id or "map",
            "x": pose.position.x,
            "y": pose.position.y,
            "yaw": quaternion_to_yaw(pose.orientation.z, pose.orientation.w),
            "stamp": msg.header.stamp.to_sec() if msg.header.stamp else time.time(),
        }
        nav_pose_time = time.time()


def current_navigation_pose() -> dict:
    with nav_pose_lock:
        if nav_pose is None:
            return {}
        pose = dict(nav_pose)
        pose["age"] = max(0.0, time.time() - nav_pose_time)
        return pose


def path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def parse_map_yaml(path: Path) -> dict:
    data = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            items = [item.strip() for item in value[1:-1].split(",") if item.strip()]
            parsed = []
            for item in items:
                try:
                    parsed.append(float(item))
                except ValueError:
                    parsed.append(item)
            data[key] = parsed
            continue
        try:
            data[key] = float(value)
            continue
        except ValueError:
            data[key] = value.strip("\"'")
    return data


def resolve_map_yaml(map_name: str) -> Path:
    if not map_name or "/" in map_name or "\\" in map_name:
        raise ValueError("地图名称非法")
    path = (SLAM_MAP_DIR / map_name).resolve()
    if path.suffix.lower() != ".yaml" or not path_is_relative_to(path, SLAM_MAP_DIR):
        raise ValueError("地图必须是 slam_map 目录中的 yaml 文件")
    if not path.exists():
        raise FileNotFoundError(f"地图不存在: {map_name}")
    return path


def map_summary(path: Path) -> dict:
    meta = parse_map_yaml(path)
    image_value = str(meta.get("image", "")).strip()
    image_path = Path(image_value)
    if not image_path.is_absolute():
        image_path = path.parent / image_path
    image_path = image_path.resolve()
    return {
        "name": path.name,
        "path": str(path),
        "image": str(image_path),
        "resolution": meta.get("resolution"),
        "origin": meta.get("origin", [0.0, 0.0, 0.0]),
        "imageExists": image_path.exists(),
    }


def list_navigation_maps() -> list:
    if not SLAM_MAP_DIR.exists():
        return []
    maps = []
    for path in sorted(SLAM_MAP_DIR.glob("*.yaml")):
        try:
            maps.append(map_summary(path))
        except Exception as exc:
            maps.append({"name": path.name, "path": str(path), "error": str(exc)})
    return maps


def read_pgm(path: Path) -> Tuple[int, int, int, bytes]:
    data = path.read_bytes()
    index = 0

    def next_token() -> bytes:
        nonlocal index
        while index < len(data):
            byte = data[index]
            if byte == 35:
                while index < len(data) and data[index] not in (10, 13):
                    index += 1
            elif chr(byte).isspace():
                index += 1
            else:
                break
        start = index
        while index < len(data) and not chr(data[index]).isspace():
            index += 1
        return data[start:index]

    magic = next_token()
    if magic != b"P5":
        raise ValueError("仅支持 P5 PGM 地图")
    width = int(next_token())
    height = int(next_token())
    max_value = int(next_token())
    while index < len(data) and chr(data[index]).isspace():
        index += 1
    if max_value > 255:
        raise ValueError("暂不支持 16-bit PGM 地图")
    pixels = data[index:index + width * height]
    if len(pixels) != width * height:
        raise ValueError("PGM 像素数据长度异常")
    return width, height, max_value, pixels


def downsample_gray8(width: int, height: int, pixels: bytes, max_size: int) -> Tuple[int, int, int, bytes]:
    stride = max(1, math.ceil(max(width, height) / max(1, max_size)))
    preview_width = math.ceil(width / stride)
    preview_height = math.ceil(height / stride)
    sampled = bytearray(preview_width * preview_height)
    out_index = 0
    for y in range(0, height, stride):
        row_offset = y * width
        for x in range(0, width, stride):
            sampled[out_index] = pixels[row_offset + x]
            out_index += 1
    return preview_width, preview_height, stride, bytes(sampled)


def navigation_map_preview(map_name: str) -> dict:
    yaml_path = resolve_map_yaml(map_name)
    summary = map_summary(yaml_path)
    image_path = Path(summary["image"])
    if not path_is_relative_to(image_path, SLAM_MAP_DIR):
        raise ValueError("地图 image 必须位于 slam_map 目录内")
    width, height, max_value, pixels = read_pgm(image_path)
    preview_width, preview_height, stride, preview_pixels = downsample_gray8(
        width,
        height,
        pixels,
        NAV_PREVIEW_MAX_SIZE,
    )
    return {
        "type": "nav_map_preview",
        "ok": True,
        **summary,
        "width": width,
        "height": height,
        "previewWidth": preview_width,
        "previewHeight": preview_height,
        "previewScale": stride,
        "maxValue": max_value,
        "encoding": "gray8",
        "data": base64.b64encode(preview_pixels).decode("ascii"),
    }


def navigation_status_response(ok: bool = True, error: str = "") -> dict:
    with nav_lock:
        proc = nav_process
        map_name = nav_map_name
    running = proc is not None and proc.poll() is None
    code = None if proc is None or running else proc.poll()
    return {
        "type": "nav_status",
        "ok": ok,
        "running": running,
        "pid": proc.pid if proc is not None else None,
        "returncode": code,
        "mapName": map_name,
        "pose": current_navigation_pose(),
        "logFile": str(NAV_LOG_FILE),
        "error": error,
        "ts": int(time.time()),
    }


def stop_navigation_process() -> None:
    global nav_process, nav_map_name
    with nav_lock:
        proc = nav_process
        nav_process = None
        nav_map_name = None
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGINT)
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except ProcessLookupError:
        pass


def start_navigation_process(map_name: str) -> dict:
    global nav_process, nav_map_name
    yaml_path = resolve_map_yaml(map_name)
    with nav_lock:
        current = nav_process
    if current is not None and current.poll() is None:
        stop_navigation_process()
    if cmd_vel_pub is not None and cmd_vel_pub.get_num_connections() <= 0:
        raise RuntimeError("底盘 /cmd_vel 无订阅者，请先恢复 turn_on_wheeltec_robot.service")
    NAV_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(NAV_LOG_FILE, "ab", buffering=0)
    command = (
        f"source {sh_quote(ROS_SETUP)} 2>/dev/null || true; "
        f"source {sh_quote(LIDAR_SETUP)} 2>/dev/null || true; "
        f"source {sh_quote(WHEELTEC_SETUP)} 2>/dev/null || true; "
        "export ROS_MASTER_URI=${ROS_MASTER_URI:-http://localhost:11311}; "
        "export ROS_IP=${DWC_ROS_IP:-127.0.0.1}; unset ROS_HOSTNAME; "
        f"exec roslaunch turn_on_wheeltec_robot navigation.launch "
        f"map_file:={sh_quote(str(yaml_path))} "
        "start_base:=false start_lidar_driver:=false start_scan_converter:=true"
    )
    proc = subprocess.Popen(
        ["/bin/bash", "-lc", command],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,
        close_fds=True,
    )
    with nav_lock:
        nav_process = proc
        nav_map_name = yaml_path.name
    time.sleep(0.8)
    if proc.poll() is not None:
        return navigation_status_response(False, "navigation.launch 启动后立即退出，请查看日志")
    return navigation_status_response(True)


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def publish_navigation_goal(x: float, y: float, yaw: float) -> int:
    if simple_goal_pub is None:
        raise RuntimeError("ROS /move_base_simple/goal Publisher 尚未初始化")
    pose = PoseStamped()
    pose.header.frame_id = "map"
    pose.header.stamp = rospy.Time.now()
    pose.pose.position.x = x
    pose.pose.position.y = y
    pose.pose.position.z = 0.0
    pose.pose.orientation.z = math.sin(yaw / 2.0)
    pose.pose.orientation.w = math.cos(yaw / 2.0)
    simple_goal_pub.publish(pose)
    subscribers = simple_goal_pub.get_num_connections()
    log.info(
        "发布 /move_base_simple/goal x=%.3f y=%.3f yaw=%.3f subscribers=%s",
        x,
        y,
        yaw,
        subscribers,
    )
    return subscribers


def watchdog_loop() -> None:
    global last_cmd_time
    while not rospy.is_shutdown():
        time.sleep(0.05)
        should_stop = False
        with state_lock:
            if last_cmd_time > 0 and time.time() - last_cmd_time > CMD_TIMEOUT_SEC:
                last_cmd_time = 0.0
                should_stop = True
        if should_stop:
            log.warning("控制指令超时，执行停车")
            hard_stop()


def execute_command(command: dict) -> dict:
    global current_v, current_w, last_cmd_time
    command_type = command.get("type")
    now = int(time.time())
    if command_type == "ping":
        return {
            "type": "pong",
            "ok": True,
            "subscribers": cmd_vel_pub.get_num_connections() if cmd_vel_pub is not None else 0,
            "ts": now,
        }
    if command_type == "stop":
        with state_lock:
            last_cmd_time = 0.0
        hard_stop()
        return {
            "type": "ack",
            "ok": True,
            "subscribers": cmd_vel_pub.get_num_connections() if cmd_vel_pub is not None else 0,
            "ts": now,
        }
    if command_type == "cmd_vel":
        try:
            linear = clamp(float(command.get("v", 0.0)), MAX_LINEAR)
            angular = clamp(float(command.get("w", 0.0)), MAX_ANGULAR)
        except (TypeError, ValueError) as exc:
            return {"type": "ack", "ok": False, "error": str(exc), "ts": now}
        subscriber_count = send_cmd_to_motor(linear, angular)
        with state_lock:
            last_cmd_time = time.time()
            current_v = linear
            current_w = angular
        return {
            "type": "ack",
            "ok": True,
            "v": linear,
            "w": angular,
            "subscribers": subscriber_count,
            "ts": now,
        }
    if command_type == "nav_maps":
        return {
            "type": "nav_maps",
            "ok": True,
            "mapDir": str(SLAM_MAP_DIR),
            "maps": list_navigation_maps(),
            "ts": now,
        }
    if command_type == "nav_map_preview":
        try:
            return navigation_map_preview(str(command.get("mapName", "")))
        except Exception as exc:
            return {"type": "nav_map_preview", "ok": False, "error": str(exc), "ts": now}
    if command_type == "nav_start":
        try:
            return start_navigation_process(str(command.get("mapName", "")))
        except Exception as exc:
            return navigation_status_response(False, str(exc))
    if command_type == "nav_stop":
        try:
            hard_stop()
            stop_navigation_process()
            return navigation_status_response(True)
        except Exception as exc:
            return navigation_status_response(False, str(exc))
    if command_type == "nav_status":
        return navigation_status_response(True)
    if command_type == "nav_goal":
        try:
            x = float(command.get("x", 0.0))
            y = float(command.get("y", 0.0))
            yaw = float(command.get("yaw", 0.0))
        except (TypeError, ValueError) as exc:
            return {"type": "ack", "ok": False, "error": str(exc), "ts": now}
        try:
            subscriber_count = publish_navigation_goal(x, y, yaw)
        except Exception as exc:
            return {"type": "ack", "ok": False, "error": str(exc), "ts": now}
        if subscriber_count <= 0:
            return {
                "type": "ack",
                "ok": False,
                "error": "ROS /move_base_simple/goal 没有订阅者，请先启动 navigation.launch",
                "subscribers": subscriber_count,
                "ts": now,
            }
        return {
            "type": "ack",
            "ok": True,
            "topic": "/move_base_simple/goal",
            "frame_id": "map",
            "x": x,
            "y": y,
            "yaw": yaw,
            "subscribers": subscriber_count,
            "ts": now,
        }
    return {"type": "ack", "ok": False, "error": "unknown_type", "ts": now}


async def control_session(url: str, token: str) -> None:
    headers = {"X-Device-Token": token}
    async with websockets.connect(
        url,
        extra_headers=headers,
        timeout=WEBSOCKET_OPEN_TIMEOUT_SEC,
        ping_interval=WEBSOCKET_PING_INTERVAL_SEC,
        ping_timeout=WEBSOCKET_PING_TIMEOUT_SEC,
        close_timeout=1,
        max_size=1024 * 1024,
    ) as websocket:
        log.info("控制通道已连接")
        try:
            while not rospy.is_shutdown():
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
                    result = {
                        "type": "result",
                        "id": command_id,
                        "ok": False,
                        "error": str(exc),
                    }
                await websocket.send(json.dumps(result, separators=(",", ":")))
        finally:
            hard_stop()
            log.warning("控制通道已断开，车辆已停车")


async def control_loop(url: str, token: str) -> None:
    delay = 1
    while not rospy.is_shutdown():
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


async def send_media_frame(websocket, send_lock: asyncio.Lock, view: str, jpeg: bytes) -> None:
    payload = MEDIA_HEADER.pack(MEDIA_VIEW_CODES[view], int(time.time() * 1000)) + jpeg
    async with send_lock:
        try:
            await asyncio.wait_for(websocket.send(payload), timeout=MEDIA_SEND_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            await websocket.close(code=1011, reason="media send timeout")
            raise


def media_stream_worker(
    view: str,
    stop_event: threading.Event,
    loop: asyncio.AbstractEventLoop,
    websocket,
    send_lock: asyncio.Lock,
) -> None:
    while not stop_event.is_set():
        try:
            request = urllib.request.Request(
                LOCAL_CAMERA_URL.format(view=urllib.parse.quote(view)),
                headers={"Connection": "close"},
            )
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
                            send_media_frame(websocket, send_lock, view, jpeg),
                            loop,
                        )
                        try:
                            future.result(timeout=5)
                        except Exception:
                            future.cancel()
                            raise
        except Exception as exc:
            if stop_event.is_set():
                break
            log.warning("%s 媒体流读取失败: %s；2 秒后重试", view, exc)
            stop_event.wait(2)


async def media_session(url: str, token: str) -> None:
    headers = {"X-Device-Token": token}
    workers: Dict[str, Tuple[threading.Thread, threading.Event]] = {}
    loop = asyncio.get_running_loop()
    send_lock = asyncio.Lock()

    async with websockets.connect(
        url,
        extra_headers=headers,
        timeout=WEBSOCKET_OPEN_TIMEOUT_SEC,
        ping_interval=WEBSOCKET_PING_INTERVAL_SEC,
        ping_timeout=WEBSOCKET_PING_TIMEOUT_SEC,
        close_timeout=1,
        max_size=1024 * 1024,
    ) as websocket:
        log.info("媒体通道已连接")
        try:
            async for raw_message in websocket:
                if not isinstance(raw_message, str):
                    continue
                message = json.loads(raw_message)
                view = message.get("view")
                if view not in MEDIA_VIEW_CODES:
                    continue
                if message.get("type") == "stream_start":
                    current = workers.get(view)
                    if current and current[0].is_alive():
                        continue
                    stop_event = threading.Event()
                    worker = threading.Thread(
                        target=media_stream_worker,
                        args=(view, stop_event, loop, websocket, send_lock),
                        name=f"media-{view}",
                        daemon=True,
                    )
                    workers[view] = (worker, stop_event)
                    worker.start()
                    log.info("开始上传 %s 媒体流", view)
                elif message.get("type") == "stream_stop":
                    current = workers.pop(view, None)
                    if current:
                        current[1].set()
                        log.info("停止上传 %s 媒体流", view)
        finally:
            for _, stop_event in workers.values():
                stop_event.set()
            log.warning("媒体通道已断开")


async def media_loop(url: str, token: str) -> None:
    delay = 1
    while not rospy.is_shutdown():
        try:
            await media_session(url, token)
            delay = 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("媒体通道连接失败: %s；%s 秒后重试", exc, delay)
            await asyncio.sleep(delay)
            delay = min(RECONNECT_DELAY_MAX_SEC, delay * 2)


def init_ros() -> None:
    global cmd_vel_pub, simple_goal_pub
    configure_local_ros_network()
    rospy.init_node("devices_web_control_agent", anonymous=False, disable_signals=True)
    cmd_vel_pub = rospy.Publisher("/cmd_vel", Twist, queue_size=1)
    simple_goal_pub = rospy.Publisher("/move_base_simple/goal", PoseStamped, queue_size=1)
    rospy.Subscriber("/amcl_pose", PoseWithCovarianceStamped, on_amcl_pose, queue_size=1)
    wait_started = time.time()
    while cmd_vel_pub.get_num_connections() == 0 and time.time() - wait_started < 5:
        if rospy.is_shutdown():
            return
        time.sleep(0.1)
    log.info("ROS /cmd_vel Publisher 已就绪，订阅者数量: %s", cmd_vel_pub.get_num_connections())
    if cmd_vel_pub.get_num_connections() == 0:
        try:
            cmd_topics = [
                f"{name} ({topic_type})"
                for name, topic_type in rospy.get_published_topics()
                if "cmd_vel" in name.lower()
            ]
            log.warning("ROS 图中可见的 cmd_vel 话题: %s", cmd_topics or "无")
        except Exception as exc:
            log.warning("读取 ROS 话题图失败: %s", exc)
    threading.Thread(target=watchdog_loop, name="control-watchdog", daemon=True).start()


async def run_agent(server: str, token: str) -> None:
    control_url = websocket_url(server, "control")
    media_url = websocket_url(server, "media")
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_shutdown() -> None:
        hard_stop()
        rospy.signal_shutdown("process signal")
        shutdown_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, request_shutdown)

    tasks = [
        asyncio.create_task(control_loop(control_url, token)),
        asyncio.create_task(media_loop(media_url, token)),
    ]
    await shutdown_event.wait()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="DevicesWebControl ROS1 outbound agent")
    parser.add_argument("--config", default=str(CONFIG_FILE))
    args = parser.parse_args()
    server, token = load_config(Path(args.config))
    init_ros()
    log.info("Agent 启动，公网入口: %s", server)
    try:
        asyncio.run(run_agent(server, token))
    finally:
        stop_navigation_process()
        hard_stop()


if __name__ == "__main__":
    main()
