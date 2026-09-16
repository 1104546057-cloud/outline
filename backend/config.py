"""
全局配置模块

集中管理所有环境变量和常量配置。
"""

import os
from dotenv import load_dotenv

# 确保加载环境变量
load_dotenv()

# JWT 配置
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dwc-default-secret-key")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))
AUTH_COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true"

# 公网原型统一入口：前端、REST 和 WebSocket 通过 path 复用同一端口
PUBLIC_SERVER_URL = os.getenv("PUBLIC_SERVER_URL", "http://192.168.31.28:5273").rstrip("/")

# 机器人控制配置
ROBOT_CONTROL_MAX_LINEAR = float(os.getenv("ROBOT_CONTROL_MAX_LINEAR", "0.4"))
ROBOT_CONTROL_MAX_ANGULAR = float(os.getenv("ROBOT_CONTROL_MAX_ANGULAR", "1.2"))
ROBOT_CONTROL_TIMEOUT_SECONDS = float(os.getenv("ROBOT_CONTROL_TIMEOUT_SECONDS", "3.0"))

# 设备在线判定超时（秒）：超过此时间未收到遥测则判定为离线
DEVICE_ONLINE_TIMEOUT_SECONDS = int(os.getenv("DEVICE_ONLINE_TIMEOUT_SECONDS", "180"))

# 视频录制结束处理超时。FFmpeg 由 imageio-ffmpeg 提供和解析。
CAMERA_RECORD_FINALIZE_TIMEOUT_SECONDS = int(os.getenv("CAMERA_RECORD_FINALIZE_TIMEOUT_SECONDS", "300"))

# Outdoor target recognition: YOLO on dai over ZeroTier. Do not default to LAN.
DETECTOR_URL = os.getenv("DETECTOR_URL", "http://10.139.91.78:9100").rstrip("/")
DETECTOR_URLS = [
    item.strip().rstrip("/")
    for item in os.getenv(
        "DETECTOR_URLS",
        "http://10.139.91.78:9100,http://127.0.0.1:9100",
    ).split(",")
    if item.strip()
]
DETECTOR_TIMEOUT = float(os.getenv("DETECTOR_TIMEOUT", "3"))
DETECTOR_STATUS_TIMEOUT = float(os.getenv("DETECTOR_STATUS_TIMEOUT", "2"))
RECOGNITION_REQUEST_TIMEOUT = float(os.getenv("RECOGNITION_REQUEST_TIMEOUT", "10"))
GUN_DETECT_INTERVAL_SECONDS = float(os.getenv("GUN_DETECT_INTERVAL_SECONDS", "1.0"))

# 平台地图默认中心对应的 WGS-84 GPS 坐标。新设备尚未上报定位时，
# 使用该位置附近的历史坐标作为初始位置。
PLATFORM_DEFAULT_GPS_LNG = float(os.getenv("PLATFORM_DEFAULT_GPS_LNG", "113.5790599"))
PLATFORM_DEFAULT_GPS_LAT = float(os.getenv("PLATFORM_DEFAULT_GPS_LAT", "22.3523145"))
