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

# 平台地图默认中心对应的 WGS-84 GPS 坐标。新设备尚未上报定位时，
# 使用该位置附近的历史坐标作为初始位置。
PLATFORM_DEFAULT_GPS_LNG = float(os.getenv("PLATFORM_DEFAULT_GPS_LNG", "113.5790599"))
PLATFORM_DEFAULT_GPS_LAT = float(os.getenv("PLATFORM_DEFAULT_GPS_LAT", "22.3523145"))

# ===== 数据统计研判模块配置 =====

# Redis 缓存（可选，未配置则使用进程内字典缓存）
REDIS_URL = os.getenv("REDIS_URL", "")
ANALYTICS_CACHE_TTL_SECONDS = int(os.getenv("ANALYTICS_CACHE_TTL_SECONDS", "300"))

# 近实时刷新间隔（秒）
ANALYTICS_NEAR_REALTIME_INTERVAL = int(os.getenv("ANALYTICS_NEAR_REALTIME_INTERVAL", "300"))

# 日聚合执行时刻（24 小时制小时数）
ANALYTICS_DAILY_RUN_HOUR = int(os.getenv("ANALYTICS_DAILY_RUN_HOUR", "2"))

# 邮件通道（默认关闭，仅在 .env 设置 EMAIL_ENABLED=true 时启用）
EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", "25"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER)
