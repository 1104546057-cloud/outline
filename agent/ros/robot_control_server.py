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
import tf2_ros
import websockets
from actionlib_msgs.msg import GoalStatus, GoalStatusArray
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped, Twist
from nav_msgs.msg import OccupancyGrid
try:
    from move_base_msgs.msg import MoveBaseActionResult
except ImportError:
    MoveBaseActionResult = None


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
MAPPING_PREVIEW_MAX_SIZE = int(os.environ.get("DWC_MAPPING_PREVIEW_MAX_SIZE", "700"))
MAPPING_LOG_FILE = Path(os.environ.get("DWC_MAPPING_LOG_FILE", "/tmp/devices_web_control_mapping.log"))
MAPPING_ALGORITHM = "cartographer"
ROS_SETUP = os.environ.get("DWC_ROS_SETUP", "/opt/ros/noetic/setup.bash")
LIDAR_SETUP = os.environ.get("DWC_LIDAR_SETUP", "/home/wheeltec/wheeltec_lidar/devel/setup.bash")
WHEELTEC_SETUP = os.environ.get("DWC_WHEELTEC_SETUP", "/home/wheeltec/wheeltec_robot/devel/setup.bash")
CARTOGRAPHER_SETUP = os.environ.get("DWC_CARTOGRAPHER_SETUP", "/home/wheeltec/cartographer_ws/devel/setup.bash")

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
tf_buffer = None
tf_listener = None
nav_lock = threading.Lock()
nav_process = None
nav_map_name = None
nav_pose_lock = threading.Lock()
nav_pose = None
nav_pose_time = 0.0
nav_goal_lock = threading.Lock()
nav_goal_status = None
nav_goal_status_time = 0.0
nav_goal_sent_time = 0.0
mapping_lock = threading.Lock()
mapping_process = None
mapping_started_at = 0.0
mapping_paused = False
mapping_error = ""
live_map_lock = threading.Lock()
live_map = None
live_map_time = 0.0
sensor_lock = threading.Lock()
sensor_times = {"odom": 0.0, "scan": 0.0, "scan_raw": 0.0, "point_cloud_raw": 0.0}

GOAL_STATUS_LABELS = {
    GoalStatus.PENDING: "PENDING",
    GoalStatus.ACTIVE: "ACTIVE",
    GoalStatus.PREEMPTED: "PREEMPTED",
    GoalStatus.SUCCEEDED: "SUCCEEDED",
    GoalStatus.ABORTED: "ABORTED",
    GoalStatus.REJECTED: "REJECTED",
    GoalStatus.PREEMPTING: "PREEMPTING",
    GoalStatus.RECALLING: "RECALLING",
    GoalStatus.RECALLED: "RECALLED",
    GoalStatus.LOST: "LOST",
}


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


def remember_sensor(name: str):
    def callback(_msg) -> None:
        with sensor_lock:
            sensor_times[name] = time.time()
    return callback


def on_live_map(msg: OccupancyGrid) -> None:
    global live_map, live_map_time
    origin = msg.info.origin
    snapshot = {
        "width": int(msg.info.width),
        "height": int(msg.info.height),
        "resolution": float(msg.info.resolution),
        "origin": [
            float(origin.position.x),
            float(origin.position.y),
            quaternion_to_yaw(origin.orientation.z, origin.orientation.w),
        ],
        "data": tuple(msg.data),
    }
    with live_map_lock:
        live_map = snapshot
        live_map_time = time.time()


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


def status_stamp_to_sec(status) -> float:
    try:
        return status.goal_id.stamp.to_sec()
    except Exception:
        return 0.0


def remember_move_base_status(status, source: str) -> None:
    global nav_goal_status, nav_goal_status_time
    with nav_goal_lock:
        sent_time = nav_goal_sent_time
        stamp = status_stamp_to_sec(status)
        if sent_time > 0 and stamp > 0 and stamp < sent_time - 1.0:
            return
        now = time.time()
        nav_goal_status = {
            "source": source,
            "status": int(status.status),
            "label": GOAL_STATUS_LABELS.get(int(status.status), str(status.status)),
            "text": status.text or "",
            "goalId": status.goal_id.id or "",
            "stamp": stamp,
            "updatedAt": now,
            "sentAt": sent_time,
        }
        nav_goal_status_time = now


def on_move_base_status(msg: GoalStatusArray) -> None:
    if not msg.status_list:
        return
    status = max(msg.status_list, key=status_stamp_to_sec)
    remember_move_base_status(status, "status")


def on_move_base_result(msg) -> None:
    remember_move_base_status(msg.status, "result")


def clear_navigation_pose() -> None:
    global nav_pose, nav_pose_time
    with nav_pose_lock:
        nav_pose = None
        nav_pose_time = 0.0


def clear_navigation_goal_status() -> None:
    global nav_goal_status, nav_goal_status_time, nav_goal_sent_time
    with nav_goal_lock:
        nav_goal_status = None
        nav_goal_status_time = 0.0
        nav_goal_sent_time = 0.0


def current_navigation_pose() -> dict:
    with nav_pose_lock:
        if nav_pose is None:
            return {}
        pose = dict(nav_pose)
        pose["age"] = max(0.0, time.time() - nav_pose_time)
        return pose


def current_mapping_pose() -> dict:
    if tf_buffer is None:
        return {}
    for child_frame in ("base_footprint", "base_link"):
        try:
            transform = tf_buffer.lookup_transform(
                "map", child_frame, rospy.Time(0), rospy.Duration(0.05)
            )
        except (
            tf2_ros.LookupException,
            tf2_ros.ConnectivityException,
            tf2_ros.ExtrapolationException,
        ):
            continue
        translation = transform.transform.translation
        rotation = transform.transform.rotation
        return {
            "frame_id": transform.header.frame_id or "map",
            "child_frame_id": child_frame,
            "x": float(translation.x),
            "y": float(translation.y),
            "yaw": quaternion_to_yaw(rotation.z, rotation.w),
        }
    return {}


def current_navigation_goal_status() -> dict:
    with nav_goal_lock:
        if nav_goal_status is None:
            return {}
        status = dict(nav_goal_status)
        status["age"] = max(0.0, time.time() - nav_goal_status_time)
        return status


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


def mapping_process_running() -> bool:
    with mapping_lock:
        proc = mapping_process
    return proc is not None and proc.poll() is None


def sensor_age(name: str) -> float:
    with sensor_lock:
        stamp = sensor_times.get(name, 0.0)
    return max(0.0, time.time() - stamp) if stamp else -1.0


def mapping_sensor_status() -> dict:
    ages = {name: sensor_age(name) for name in sensor_times}
    lidar_candidates = [ages[name] for name in ("scan", "scan_raw", "point_cloud_raw") if ages[name] >= 0]
    ages["lidar"] = min(lidar_candidates) if lidar_candidates else -1.0
    return ages


def mapping_status_response(ok: bool = True, error: str = "") -> dict:
    with mapping_lock:
        proc = mapping_process
        started_at = mapping_started_at
        paused = mapping_paused
        remembered_error = mapping_error
    running = proc is not None and proc.poll() is None
    with live_map_lock:
        map_available = live_map is not None
        map_age = max(0.0, time.time() - live_map_time) if live_map_time else -1.0
    mode = "mapping_paused" if running and paused else "mapping" if running else "idle"
    return {
        "type": "map_status",
        "ok": ok,
        "mode": mode,
        "running": running,
        "paused": bool(running and paused),
        "pid": proc.pid if proc is not None and running else None,
        "elapsed": max(0, int(time.time() - started_at)) if running and started_at else 0,
        "mapAvailable": map_available and running,
        "mapAge": map_age if running else -1.0,
        "algorithm": MAPPING_ALGORITHM,
        "pose": current_mapping_pose() if running else {},
        "sensors": mapping_sensor_status(),
        "logFile": str(MAPPING_LOG_FILE),
        "error": error or remembered_error,
        "ts": int(time.time()),
    }


def mapping_preflight() -> None:
    if cmd_vel_pub is None or cmd_vel_pub.get_num_connections() <= 0:
        raise RuntimeError("底盘 /cmd_vel 无订阅者，请先恢复 turn_on_wheeltec_robot.service")
    sensors = mapping_sensor_status()
    if sensors["odom"] < 0 or sensors["odom"] > 2.0:
        raise RuntimeError("/odom 数据不可用或已超时，暂不能开始建图")
    mapping_sources = [sensors[name] for name in ("scan", "point_cloud_raw") if sensors[name] >= 0]
    if not mapping_sources or min(mapping_sources) > 2.0:
        raise RuntimeError("建图所需的 /point_cloud_raw 或 /scan 数据不可用，暂不能开始建图")


def stop_mapping_process() -> None:
    global mapping_process, mapping_started_at, mapping_paused
    hard_stop()
    with mapping_lock:
        proc = mapping_process
        mapping_process = None
        mapping_started_at = 0.0
        mapping_paused = False
    if proc is not None and proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGINT)
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
    with live_map_lock:
        global live_map, live_map_time
        live_map = None
        live_map_time = 0.0


def start_mapping_process() -> dict:
    global mapping_process, mapping_started_at, mapping_paused, mapping_error
    mapping_preflight()
    hard_stop()
    stop_navigation_process()
    if mapping_process_running():
        stop_mapping_process()
    with live_map_lock:
        global live_map, live_map_time
        live_map = None
        live_map_time = 0.0
    MAPPING_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(MAPPING_LOG_FILE, "ab", buffering=0)
    command = (
        f"source {sh_quote(ROS_SETUP)} 2>/dev/null || true; "
        f"source {sh_quote(LIDAR_SETUP)} 2>/dev/null || true; "
        f"source {sh_quote(WHEELTEC_SETUP)} 2>/dev/null || true; "
        f"source {sh_quote(CARTOGRAPHER_SETUP)} 2>/dev/null || true; "
        "export ROS_MASTER_URI=${ROS_MASTER_URI:-http://localhost:11311}; "
        "export ROS_IP=${DWC_ROS_IP:-127.0.0.1}; unset ROS_HOSTNAME; "
        "trap 'kill 0' INT TERM EXIT; "
        "roslaunch pointcloud_to_laserscan pointcloud_scan.launch & "
        "converter_pid=$!; "
        "sleep 1; "
        "roslaunch cartographer_ros 2d_online.launch & "
        "mapper_pid=$!; wait $mapper_pid"
    )
    proc = subprocess.Popen(
        ["/bin/bash", "-lc", command],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,
        close_fds=True,
    )
    log_file.close()
    with mapping_lock:
        mapping_process = proc
        mapping_started_at = time.time()
        mapping_paused = False
        mapping_error = ""
    time.sleep(1.2)
    if proc.poll() is not None:
        with mapping_lock:
            mapping_error = "建图进程启动后立即退出，请查看日志"
        return mapping_status_response(False)
    return mapping_status_response(True)


def pause_mapping() -> dict:
    global mapping_paused
    if not mapping_process_running():
        return mapping_status_response(False, "当前没有运行中的建图任务")
    hard_stop()
    with mapping_lock:
        mapping_paused = True
    return mapping_status_response(True)


def live_mapping_preview() -> dict:
    if not mapping_process_running():
        raise RuntimeError("当前没有运行中的建图任务")
    with live_map_lock:
        snapshot = dict(live_map) if live_map is not None else None
        age = max(0.0, time.time() - live_map_time) if live_map_time else -1.0
    if not snapshot:
        raise RuntimeError("尚未收到 /map 数据，请稍候")
    width = snapshot["width"]
    height = snapshot["height"]
    occupancy = snapshot["data"]
    pixels = bytearray(width * height)
    output_index = 0
    for y in range(height - 1, -1, -1):
        row_offset = y * width
        for x in range(width):
            value = occupancy[row_offset + x]
            pixels[output_index] = 205 if value < 0 else max(0, min(254, 254 - round(value * 2.54)))
            output_index += 1
    preview_width, preview_height, stride, preview_pixels = downsample_gray8(
        width, height, bytes(pixels), MAPPING_PREVIEW_MAX_SIZE
    )
    return {
        "type": "map_live_preview",
        "ok": True,
        "width": width,
        "height": height,
        "previewWidth": preview_width,
        "previewHeight": preview_height,
        "previewScale": stride,
        "resolution": snapshot["resolution"],
        "origin": snapshot["origin"],
        "encoding": "gray8",
        "maxValue": 255,
        "age": age,
        "pose": current_mapping_pose(),
        "data": base64.b64encode(preview_pixels).decode("ascii"),
    }


def safe_map_stem(display_name: str) -> str:
    name = display_name.strip()
    if name.lower().endswith(".yaml"):
        name = name[:-5]
    if not name or len(name) > 64 or name in (".", ".."):
        raise ValueError("地图名称长度应为 1 到 64 个字符")
    if any(char in name for char in "/\\\0"):
        raise ValueError("地图名称不能包含路径分隔符")
    if any(ord(char) < 32 for char in name):
        raise ValueError("地图名称包含非法控制字符")
    target = (SLAM_MAP_DIR / name).resolve()
    if not path_is_relative_to(target, SLAM_MAP_DIR):
        raise ValueError("地图名称非法")
    return name


def save_mapping_map(display_name: str) -> dict:
    if not mapping_process_running():
        raise RuntimeError("当前没有运行中的建图任务")
    with live_map_lock:
        if live_map is None:
            raise RuntimeError("尚未收到 /map 数据，不能保存")
    hard_stop()
    stem = safe_map_stem(display_name)
    SLAM_MAP_DIR.mkdir(parents=True, exist_ok=True)
    prefix = (SLAM_MAP_DIR / stem).resolve()
    yaml_path = prefix.with_suffix(".yaml")
    pgm_path = prefix.with_suffix(".pgm")
    if yaml_path.exists() or pgm_path.exists():
        raise FileExistsError(f"地图已存在: {stem}")
    command = (
        f"source {sh_quote(ROS_SETUP)} 2>/dev/null || true; "
        f"source {sh_quote(WHEELTEC_SETUP)} 2>/dev/null || true; "
        "export ROS_MASTER_URI=${ROS_MASTER_URI:-http://localhost:11311}; "
        "export ROS_IP=${DWC_ROS_IP:-127.0.0.1}; unset ROS_HOSTNAME; "
        f"rosrun map_server map_saver -f {sh_quote(str(prefix))} map:=/map"
    )
    result = subprocess.run(["/bin/bash", "-lc", command], capture_output=True, text=True, timeout=20)
    if result.returncode != 0 or not yaml_path.exists() or not pgm_path.exists():
        raise RuntimeError((result.stderr or result.stdout or "map_saver 保存失败").strip())
    summary = map_summary(yaml_path)
    stop_mapping_process()
    return summary


def delete_navigation_map(map_name: str) -> dict:
    yaml_path = resolve_map_yaml(map_name)
    with nav_lock:
        if nav_process is not None and nav_process.poll() is None and nav_map_name == yaml_path.name:
            raise RuntimeError("该地图正在导航中，不能删除")
    summary = map_summary(yaml_path)
    image_path = Path(summary["image"])
    yaml_path.unlink()
    if image_path.exists() and path_is_relative_to(image_path, SLAM_MAP_DIR):
        image_path.unlink()
    return {"name": map_name}


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
        "pose": current_navigation_pose() if running else {},
        "goalStatus": current_navigation_goal_status(),
        "logFile": str(NAV_LOG_FILE),
        "error": error,
        "ts": int(time.time()),
    }


def stop_navigation_process() -> None:
    global nav_process, nav_map_name
    clear_navigation_pose()
    clear_navigation_goal_status()
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
    if mapping_process_running():
        raise RuntimeError("建图任务仍在运行，请先保存或放弃本次建图")
    yaml_path = resolve_map_yaml(map_name)
    with nav_lock:
        current = nav_process
    if current is not None and current.poll() is None:
        stop_navigation_process()
    clear_navigation_pose()
    clear_navigation_goal_status()
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
    global nav_goal_status, nav_goal_status_time, nav_goal_sent_time
    if simple_goal_pub is None:
        raise RuntimeError("ROS /move_base_simple/goal Publisher 尚未初始化")
    with nav_goal_lock:
        nav_goal_sent_time = time.time()
        nav_goal_status = None
        nav_goal_status_time = 0.0
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
    global current_v, current_w, last_cmd_time, mapping_paused
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
        if mapping_process_running() and (linear != 0.0 or angular != 0.0):
            with mapping_lock:
                mapping_paused = False
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
    if command_type == "map_status":
        return mapping_status_response(True)
    if command_type == "map_start":
        try:
            return start_mapping_process()
        except Exception as exc:
            return mapping_status_response(False, str(exc))
    if command_type == "map_pause":
        try:
            return pause_mapping()
        except Exception as exc:
            return mapping_status_response(False, str(exc))
    if command_type == "map_discard":
        try:
            stop_mapping_process()
            return mapping_status_response(True)
        except Exception as exc:
            return mapping_status_response(False, str(exc))
    if command_type == "map_live_preview":
        try:
            return live_mapping_preview()
        except Exception as exc:
            return {"type": "map_live_preview", "ok": False, "error": str(exc), "ts": now}
    if command_type == "map_save":
        try:
            saved_map = save_mapping_map(str(command.get("mapName", "")))
            return {"type": "map_saved", "ok": True, "map": saved_map, "ts": now}
        except Exception as exc:
            return {"type": "map_saved", "ok": False, "error": str(exc), "ts": now}
    if command_type == "map_delete":
        try:
            deleted_map = delete_navigation_map(str(command.get("mapName", "")))
            return {"type": "map_deleted", "ok": True, "map": deleted_map, "ts": now}
        except Exception as exc:
            return {"type": "map_deleted", "ok": False, "error": str(exc), "ts": now}
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
    global cmd_vel_pub, simple_goal_pub, tf_buffer, tf_listener
    configure_local_ros_network()
    rospy.init_node("devices_web_control_agent", anonymous=False, disable_signals=True)
    cmd_vel_pub = rospy.Publisher("/cmd_vel", Twist, queue_size=1)
    simple_goal_pub = rospy.Publisher("/move_base_simple/goal", PoseStamped, queue_size=1)
    tf_buffer = tf2_ros.Buffer(cache_time=rospy.Duration(10.0))
    tf_listener = tf2_ros.TransformListener(tf_buffer)
    rospy.Subscriber("/amcl_pose", PoseWithCovarianceStamped, on_amcl_pose, queue_size=1)
    rospy.Subscriber("/map", OccupancyGrid, on_live_map, queue_size=1)
    rospy.Subscriber("/odom", rospy.AnyMsg, remember_sensor("odom"), queue_size=1)
    rospy.Subscriber("/scan", rospy.AnyMsg, remember_sensor("scan"), queue_size=1)
    rospy.Subscriber("/scan_raw", rospy.AnyMsg, remember_sensor("scan_raw"), queue_size=1)
    rospy.Subscriber("/point_cloud_raw", rospy.AnyMsg, remember_sensor("point_cloud_raw"), queue_size=1)
    rospy.Subscriber("/move_base/status", GoalStatusArray, on_move_base_status, queue_size=1)
    if MoveBaseActionResult is not None:
        rospy.Subscriber("/move_base/result", MoveBaseActionResult, on_move_base_result, queue_size=1)
    else:
        log.warning("move_base_msgs 不可用，将仅通过 /move_base/status 判断导航目标状态")
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
