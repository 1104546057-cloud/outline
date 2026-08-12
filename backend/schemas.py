"""
Pydantic 数据模型（请求/响应 Schema）

集中定义所有 API 接口的请求体和响应体模型。
"""

from pydantic import BaseModel
from typing import Literal, Optional
from datetime import datetime


# ===== 认证相关 =====

class LoginRequest(BaseModel):
    """登录请求体"""
    username: str
    password: str
    captcha_id: str
    captcha_code: str


class RegisterRequest(BaseModel):
    """公开注册请求体"""
    username: str
    password: str
    nickname: Optional[str] = None
    captcha_id: str
    captcha_code: str


class LoginResponse(BaseModel):
    """登录响应体"""
    message: str
    username: str
    token: str
    nickname: Optional[str] = None


class RegisterResponse(BaseModel):
    """公开注册响应体"""
    message: str
    username: str
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


# ===== 巡检导航 =====

class NavigationMapPreviewRequest(BaseModel):
    """获取车端 SLAM 地图预览"""
    robotId: Optional[int] = None
    mapName: str


class NavigationStartRequest(BaseModel):
    """启动车端 navigation.launch"""
    robotId: Optional[int] = None
    mapName: str


class NavigationGoalRequest(BaseModel):
    """发送地图坐标系目标点"""
    robotId: Optional[int] = None
    x: float
    y: float
    yaw: float = 0.0


class NavigationStopRequest(BaseModel):
    """停止 Web 平台启动的导航进程"""
    robotId: Optional[int] = None


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


class SecurityAlertCreate(BaseModel):
    alert_type: str
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    title: str
    description: Optional[str] = None
    device_id: Optional[int] = None
    source_type: str = "manual"
    source_id: Optional[str] = None
    media_path: Optional[str] = None
    occurred_at: Optional[datetime] = None


class SecurityAlertAssign(BaseModel):
    assignee: str


class SecurityAlertClose(BaseModel):
    handling_note: Optional[str] = None


# ===== 数据统计研判模块 =====

class AnalyticsEventIngest(BaseModel):
    """外部 Agent / 系统接入事件。"""
    event_type: str
    source: Literal["agent", "api", "manual", "import"] = "api"
    device_id: Optional[int] = None
    occurred_at: Optional[datetime] = None
    payload: Optional[dict] = None


class AnalyticsEventManual(BaseModel):
    """前端手动录入事件。"""
    event_type: str
    device_id: Optional[int] = None
    occurred_at: Optional[datetime] = None
    payload: Optional[dict] = None


class AnalyticsIndicatorCreate(BaseModel):
    code: str
    name: str
    category: str = "device"
    data_source: str = "telemetry"
    expression: Optional[dict] = None
    unit: Optional[str] = None
    granularity: str = "day"
    baseline: Optional[dict] = None
    description: Optional[str] = None
    is_active: bool = True


class AnalyticsIndicatorUpdate(BaseModel):
    name: Optional[str] = None
    expression: Optional[dict] = None
    unit: Optional[str] = None
    baseline: Optional[dict] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class AnalyticsRuleCreate(BaseModel):
    name: str
    indicator_id: int
    rule_type: Literal["threshold", "zscore", "consecutive", "ratio"] = "threshold"
    condition: Optional[dict] = None
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    alert_type: str = "analytics_rule"
    description: Optional[str] = None
    is_active: bool = True


class AnalyticsRuleUpdate(BaseModel):
    name: Optional[str] = None
    condition: Optional[dict] = None
    severity: Optional[Literal["low", "medium", "high", "critical"]] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class AnalyticsReportTemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    config: dict
    format: Literal["pdf", "excel"] = "pdf"
    is_active: bool = True


class AnalyticsReportRunCreate(BaseModel):
    template_id: int
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None


class UserRoleUpdate(BaseModel):
    role: Literal["viewer", "analyst", "admin"]


# ====================================================================
# 校园室外自主巡检（阶段 B/C）
# 关联：docs/requirements/campus-outdoor-autonomous-patrol.md
# 设计：与既有 Patrol* schema 严格分离，避免坐标混用污染室内 SLAM 流程。
# ====================================================================


class OutdoorCalibrationCreate(BaseModel):
    """创建校园坐标标定（FR-02）

    原点必须以 WGS84 经纬度提交；ENU 转换由后端按标定版本计算。
    """
    name: str
    version: str
    description: Optional[str] = None
    origin_lng: float
    origin_lat: float
    origin_alt: Optional[float] = None
    origin_yaw: float = 0.0


class OutdoorCalibrationUpdate(BaseModel):
    """更新坐标标定

    版本号一经创建不可修改；原点修改仅允许在 draft 状态下进行。
    """
    name: Optional[str] = None
    description: Optional[str] = None
    origin_lng: Optional[float] = None
    origin_lat: Optional[float] = None
    origin_alt: Optional[float] = None
    origin_yaw: Optional[float] = None
    status: Optional[Literal["draft", "verified", "active", "deprecated"]] = None
    verification_geojson: Optional[dict] = None
    verified_by: Optional[str] = None


class OutdoorCalibrationResponse(BaseModel):
    id: int
    name: str
    version: str
    description: Optional[str]
    origin_lng: float
    origin_lat: float
    origin_alt: Optional[float]
    origin_yaw: float
    status: str
    verified_by: Optional[str]
    verified_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class OutdoorWaypointCreate(BaseModel):
    """创建室外航点（FR-03.2）

    必须提交 WGS84 经纬度；ENU 坐标由后端按 route.calibration_id 自动计算填充。
    """
    seq_order: int
    name: str
    geo_lng: float
    geo_lat: float
    yaw: Optional[float] = None
    arrival_radius_m: float = 0.5
    dwell_seconds: int = 0
    action: Optional[str] = None
    action_params: Optional[dict] = None
    timeout_seconds: int = 120
    is_enabled: bool = True


class OutdoorWaypointUpdate(BaseModel):
    """更新室外航点"""
    seq_order: Optional[int] = None
    name: Optional[str] = None
    geo_lng: Optional[float] = None
    geo_lat: Optional[float] = None
    yaw: Optional[float] = None
    arrival_radius_m: Optional[float] = None
    dwell_seconds: Optional[int] = None
    action: Optional[str] = None
    action_params: Optional[dict] = None
    timeout_seconds: Optional[int] = None
    is_enabled: Optional[bool] = None


class OutdoorRouteCreate(BaseModel):
    """创建室外路线（FR-03）

    路线必须绑定 calibration_id；提交航点列表后自动生成 v1。
    编辑现有路线会生成新版本，旧版本进入 frozen 状态。
    """
    name: str
    description: Optional[str] = None
    calibration_id: int
    fence_type: Literal["polygon", "corridor"] = "polygon"
    fence_geojson: Optional[dict] = None
    fence_buffer_m: float = 0.3
    max_speed_ms: float = 0.8
    applicable_device_types: Optional[list[str]] = None
    waypoints: list[OutdoorWaypointCreate] = []


class OutdoorRouteUpdate(BaseModel):
    """更新室外路线

    更新路线几何或航点会触发新版本生成；parent_id 自动指向上版本。
    """
    name: Optional[str] = None
    description: Optional[str] = None
    fence_type: Optional[Literal["polygon", "corridor"]] = None
    fence_geojson: Optional[dict] = None
    fence_buffer_m: Optional[float] = None
    max_speed_ms: Optional[float] = None
    applicable_device_types: Optional[list[str]] = None
    status: Optional[Literal["draft", "published", "frozen", "deprecated"]] = None
    waypoints: Optional[list[OutdoorWaypointCreate]] = None


class OutdoorRouteResponse(BaseModel):
    """路线响应（含航点列表）"""
    id: int
    name: str
    description: Optional[str]
    calibration_id: int
    calibration_version: Optional[str] = None
    version: int
    parent_id: Optional[int]
    fence_type: str
    fence_geojson: Optional[dict]
    fence_buffer_m: Optional[float]
    max_speed_ms: Optional[float]
    applicable_device_types: Optional[list[str]]
    status: str
    waypoint_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class OutdoorPatrolTaskCreate(BaseModel):
    """创建室外巡检任务（FR-04）

    任务创建时不立刻冻结路线；启动预检通过后才生成快照。
    """
    name: str
    description: Optional[str] = None
    route_id: int
    device_id: Optional[int] = None
    schedule_type: Literal["immediate", "scheduled"] = "immediate"
    scheduled_at: Optional[datetime] = None


class OutdoorPatrolTaskResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    route_id: int
    device_id: Optional[int]
    schedule_type: str
    scheduled_at: Optional[datetime]
    status: str
    current_waypoint_seq: Optional[int]
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class OutdoorGoalRequest(BaseModel):
    """室外导航目标请求（FR §8.1）

    与既有 NavigationGoalRequest 严格分离：
      - 必须显式声明 coordinateType
      - 必须绑定 calibrationVersion
      - 必须携带 goalId（用于航点级追踪）
    """
    robotId: int
    coordinateType: Literal["enu", "wgs84"]
    calibrationVersion: str
    goalId: str
    # 当 coordinateType=enu
    x: Optional[float] = None
    y: Optional[float] = None
    # 当 coordinateType=wgs84
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    yaw: float = 0.0


class OutdoorPrecheckRequest(BaseModel):
    """任务启动预检请求（FR-04.2）"""
    task_id: int


class OutdoorPrecheckResponse(BaseModel):
    """预检响应：任一 passed=false 则禁止启动"""
    ok: bool
    checks: list[dict] = []
    # 每项形如：
    # {"item": "device_online", "passed": true, "reason": null}
    # {"item": "localization_healthy", "passed": false, "reason": "GNSS fix=GPS, 低于阈值 RTK_FLOAT"}
