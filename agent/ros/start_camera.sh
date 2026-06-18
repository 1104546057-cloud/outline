#!/bin/bash
set -euo pipefail

ROS_SETUP="${ROS_SETUP:-/opt/ros/noetic/setup.bash}"
RUN_USER_NAME="${USER:-$(id -un)}"
WHEELTEC_SETUP="${WHEELTEC_SETUP:-/home/${RUN_USER_NAME}/wheeltec_robot/devel/setup.bash}"
LIDAR_SETUP="${LIDAR_SETUP:-/home/${RUN_USER_NAME}/wheeltec_lidar/devel/setup.bash}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
CAMERA_DEVICE="${CAMERA_DEVICE:-/dev/Astra_Gemini}"
CAMERA_HTTP_PORT="${CAMERA_HTTP_PORT:-8080}"
CAMERA_ROSCONSOLE_CONFIG="${CAMERA_ROSCONSOLE_CONFIG:-${SCRIPT_DIR}/rosconsole_camera.config}"
LIDAR_TOPIC="${LIDAR_TOPIC:-/point_cloud_raw}"
START_LIDAR_DRIVER="${START_LIDAR_DRIVER:-auto}"

if [ ! -f "$ROS_SETUP" ] || [ ! -f "$WHEELTEC_SETUP" ]; then
  echo "ROS 环境未找到: $ROS_SETUP / $WHEELTEC_SETUP" >&2
  exit 1
fi
if [ ! -e "$CAMERA_DEVICE" ]; then
  echo "Gemini Pro 彩色设备不存在: $CAMERA_DEVICE" >&2
  exit 1
fi
if [ ! -f "$CAMERA_ROSCONSOLE_CONFIG" ]; then
  echo "ROS 相机日志配置不存在: $CAMERA_ROSCONSOLE_CONFIG" >&2
  exit 1
fi

# ROS setup scripts read optional variables that are absent in a clean systemd environment.
set +u
source "$ROS_SETUP"
source "$WHEELTEC_SETUP"
if [ -f "$LIDAR_SETUP" ]; then
  source "$LIDAR_SETUP"
fi
set -u

children=()
cleanup() {
  local pid
  for pid in "${children[@]}"; do
    kill -TERM "$pid" 2>/dev/null || true
  done
  for pid in "${children[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT
trap 'exit 0' INT TERM HUP

# Astra 节点只打开深度传感器，彩色 MJPEG 由 ros_camera_server.py 原样转发。
ROSCONSOLE_CONFIG_FILE="$CAMERA_ROSCONSOLE_CONFIG" \
  roslaunch astra_camera gemini.launch \
  enable_color:=false \
  use_uvc_camera:=false \
  enable_ir:=false \
  enable_point_cloud:=false \
  enable_point_cloud_xyzrgb:=false \
  depth_fps:=30 &
children+=("$!")

lidar_has_publisher() {
  timeout 2 rostopic echo -n 1 "$LIDAR_TOPIC" >/dev/null 2>&1
}

lidar_watchdog() {
  local lidar_pid=""

  cleanup_lidar() {
    if [ -n "$lidar_pid" ]; then
      kill -TERM "$lidar_pid" 2>/dev/null || true
      wait "$lidar_pid" 2>/dev/null || true
    fi
  }
  trap cleanup_lidar EXIT
  trap 'exit 0' INT TERM HUP

  while true; do
    if [ -n "$lidar_pid" ] && kill -0 "$lidar_pid" 2>/dev/null; then
      sleep 3
      continue
    fi
    if [ -n "$lidar_pid" ]; then
      wait "$lidar_pid" 2>/dev/null || true
    fi
    lidar_pid=""

    if [ "$START_LIDAR_DRIVER" = "auto" ] && lidar_has_publisher; then
      sleep 3
      continue
    fi

    echo "C16 雷达未运行，正在启动雷达驱动..." >&2
    roslaunch lslidar_cx_driver lslidar_cx.launch &
    lidar_pid="$!"
    sleep 3
  done
}

if [ "$START_LIDAR_DRIVER" != "never" ]; then
  if [ ! -f "$LIDAR_SETUP" ]; then
    echo "C16 雷达 ROS 环境未找到: $LIDAR_SETUP" >&2
    exit 1
  fi
  lidar_watchdog &
  children+=("$!")
fi

"$PYTHON_BIN" "$SCRIPT_DIR/ros_camera_server.py" \
  --port "$CAMERA_HTTP_PORT" \
  --camera-device "$CAMERA_DEVICE" \
  --camera-fps 30 \
  --rgb-compressed-topic /camera/rgb/image_raw/compressed \
  --depth-topic /camera/depth/image_raw \
  --depth-max-fps 30 \
  --lidar-topic "$LIDAR_TOPIC" \
  --lidar-max-fps 10 \
  --lidar-range-m 20 \
  --stream-fps 30 &
children+=("$!")

# 任一核心进程退出时，停止整组进程并交给 systemd 重启。
wait -n "${children[@]}"
