"""
Pydantic 数据模型（请求/响应 Schema）

集中定义所有 API 接口的请求体和响应体模型。
"""

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


# ===== 认证相关 =====

class LoginRequest(BaseModel):
    """登录请求体"""
    username: str
    password: str
    captcha_id: str
    captcha_code: str


class LoginResponse(BaseModel):
    """登录响应体"""
    message: str
    username: str
    token: str
    nickname: Optional[str] = None


# ===== 用户管理 =====

class UserCreate(BaseModel):
    """创建用户请求体"""
    username: str
    password: str
    nickname: Optional[str] = None
    is_active: bool = True


class UserUpdate(BaseModel):
    """更新用户请求体"""
    password: Optional[str] = None
    nickname: Optional[str] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    """用户响应体"""
    id: int
    username: str
    nickname: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ===== 设备管理 =====

class DeviceCreate(BaseModel):
    """创建设备请求体"""
    name: str
    type: str
    ip_address: Optional[str] = None
    port: int = 9000
    password: Optional[str] = None  # 兼容旧前端字段，公网 Agent 模式不再使用
    server_address: Optional[str] = None  # 兼容旧前端字段


class DeviceUpdate(BaseModel):
    """更新设备请求体"""
    name: Optional[str] = None
    type: Optional[str] = None
    ip_address: Optional[str] = None
    port: Optional[int] = None


class DeviceResponse(BaseModel):
    """设备响应体"""
    id: int
    name: str
    type: str
    ip_address: Optional[str]
    port: int
    status: str
    control_connected: bool = False
    media_connected: bool = False
    battery: Optional[int]
    health: int
    signal: Optional[int]
    speed: str
    lat: Optional[str]
    lng: Optional[str]
    last_seen: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    # 扩展遥测信息
    extra: Optional[dict] = None

    class Config:
        from_attributes = True


# ===== 机器人控制 =====

class RobotControlCmdVel(BaseModel):
    """机器人运动控制请求体"""
    robotId: Optional[int] = None
    linear: float = 0.0
    angular: float = 0.0


class RobotControlStop(BaseModel):
    """机器人停车请求体"""
    robotId: Optional[int] = None


class RobotControlSend(BaseModel):
    """发送自定义 TCP 指令请求体"""
    robotId: Optional[int] = None
    command: str  # 直接发送的 JSON 指令代码，例如 '{"type":"ping"}'


# ===== 集群管理 =====

class ClusterCreate(BaseModel):
    """创建集群请求体"""
    name: str
    description: Optional[str] = None


class ClusterUpdate(BaseModel):
    """更新集群请求体"""
    name: Optional[str] = None
    description: Optional[str] = None


class ClusterResponse(BaseModel):
    """集群响应体"""
    id: int
    name: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime
    devices: list[DeviceResponse] = []

    class Config:
        from_attributes = True


class ClusterAddDevice(BaseModel):
    """添加设备到集群请求体"""
    device_id: int


class ClusterControlSend(BaseModel):
    """集群发送自定义 TCP 指令请求体"""
    command: str


# ===== IoT 遥测 =====

class TelemetryExtra(BaseModel):
    cpu_temp_c: Optional[float] = None
    gps: Optional[dict] = None
    networkLocation: Optional[dict] = None
    locationSource: Optional[str] = None

class TelemetryRequest(BaseModel):
    status: str
    reportedAt: str
    battery: Optional[int] = None
    signal: Optional[int] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    extra: Optional[dict] = None


# ===== 巡检系统 =====

class PatrolAreaCreate(BaseModel):
    """创建巡检区域请求体"""
    name: str
    description: Optional[str] = None
    manager: Optional[str] = None
    boundary: Optional[list] = None
    center_lng: Optional[float] = None
    center_lat: Optional[float] = None
    area_sqm: Optional[float] = None


class PatrolAreaUpdate(BaseModel):
    """更新巡检区域请求体"""
    name: Optional[str] = None
    description: Optional[str] = None
    manager: Optional[str] = None
    boundary: Optional[list] = None
    center_lng: Optional[float] = None
    center_lat: Optional[float] = None
    area_sqm: Optional[float] = None


class PatrolPointCreate(BaseModel):
    """创建巡检点位请求体"""
    area_id: int
    name: str
    description: Optional[str] = None
    lng: float
    lat: float
    address: Optional[str] = None


class PatrolPointUpdate(BaseModel):
    """更新巡检点位请求体"""
    name: Optional[str] = None
    description: Optional[str] = None
    address: Optional[str] = None


class PatrolRouteCreate(BaseModel):
    """创建巡检线路请求体"""
    area_id: int
    name: str
    description: Optional[str] = None
    distance: Optional[float] = None
    point_ids: list[int] = []  # 有序点位ID列表


class PatrolRouteUpdate(BaseModel):
    """更新巡检线路请求体"""
    name: Optional[str] = None
    description: Optional[str] = None
    distance: Optional[float] = None
    point_ids: Optional[list[int]] = None  # 重新设置点位列表


class PatrolTaskCreate(BaseModel):
    """创建巡检任务请求体"""
    route_id: int
    device_id: Optional[int] = None
    name: str


class PatrolTrackAppend(BaseModel):
    """追加GPS轨迹点请求体"""
    points: list[dict]  # [{lng, lat, ts}]
