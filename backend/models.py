"""
数据库模型定义

定义系统中的所有数据库表结构（ORM 模型）。
"""

from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Table, Text, Numeric, JSON, Float, UniqueConstraint
from sqlalchemy.orm import relationship
from database import Base

class User(Base):
    """用户表模型"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="用户ID")
    username = Column(String(50), unique=True, nullable=False, index=True, comment="用户名")
    password_hash = Column(String(255), nullable=False, comment="密码哈希值")
    nickname = Column(String(100), nullable=True, comment="用户昵称")
    is_active = Column(Boolean, default=True, nullable=False, comment="是否启用")
    created_at = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False, comment="更新时间")

    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}', nickname='{self.nickname}')>"


class Device(Base):
    """设备表模型"""
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="设备ID")
    name = Column(String(100), nullable=False, comment="设备名称")
    type = Column(String(50), nullable=False, comment="设备类型(无人车/无人机/无人船)")
    ip_address = Column(String(50), nullable=False, unique=True, comment="IP地址")
    port = Column(Integer, default=9000, nullable=False, comment="控制服务端口号")
    status = Column(String(20), default="offline", comment="在线状态(online/offline)")
    battery = Column(Integer, nullable=True, comment="电量%")
    health = Column(Integer, default=100, comment="健康度%")
    signal = Column(Integer, nullable=True, comment="信号强度%")
    speed = Column(String(20), default="0 m/s", comment="当前速度")
    lat = Column(String(50), nullable=True, comment="纬度")
    lng = Column(String(50), nullable=True, comment="经度")
    last_seen = Column(DateTime, nullable=True, comment="最后遥测上报时间")
    created_at = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False, comment="更新时间")

    # 关联遥测数据
    telemetry_records = relationship("DeviceTelemetry", back_populates="device", cascade="all, delete-orphan")
    # 关联设备 Token
    tokens = relationship("DeviceToken", back_populates="device", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Device(id={self.id}, name='{self.name}', ip='{self.ip_address}:{self.port}')>"


class DeviceTelemetry(Base):
    """设备遥测记录表"""
    __tablename__ = "device_telemetry"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="遥测记录ID")
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True, comment="设备ID")
    battery = Column(Integer, nullable=True, comment="电量%")
    signal = Column(Integer, nullable=True, comment="信号强度%")
    status = Column(String(32), nullable=True, comment="设备状态")
    lat = Column(Numeric(10, 7), nullable=True, comment="纬度")
    lng = Column(Numeric(10, 7), nullable=True, comment="经度")
    source_ip = Column(String(64), nullable=True, comment="上报来源IP")
    extra_json = Column(JSON, nullable=True, comment="扩展数据(CPU温度/GPS状态等)")
    reported_at = Column(DateTime, nullable=False, comment="上报时间")
    created_at = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")

    device = relationship("Device", back_populates="telemetry_records")

    def __repr__(self):
        return f"<DeviceTelemetry(id={self.id}, device_id={self.device_id}, reported_at={self.reported_at})>"


class DeviceToken(Base):
    """设备认证 Token 表"""
    __tablename__ = "device_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="Token ID")
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True, comment="设备ID")
    token = Column(String(128), unique=True, nullable=False, comment="设备Token")
    note = Column(String(256), nullable=True, comment="备注")
    is_active = Column(Boolean, default=True, nullable=False, comment="是否有效")
    created_at = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")

    device = relationship("Device", back_populates="tokens")

    def __repr__(self):
        return f"<DeviceToken(id={self.id}, device_id={self.device_id})>"


# 集群与设备的多对多关联表
cluster_device_association = Table(
    "cluster_device",
    Base.metadata,
    Column("cluster_id", Integer, ForeignKey("clusters.id", ondelete="CASCADE"), primary_key=True),
    Column("device_id", Integer, ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)
)


class Cluster(Base):
    """集群表模型"""
    __tablename__ = "clusters"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="集群ID")
    name = Column(String(100), nullable=False, unique=True, comment="集群名称")
    description = Column(String(255), nullable=True, comment="集群描述")
    created_at = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False, comment="更新时间")

    # 关联设备列表，自动加载
    devices = relationship("Device", secondary=cluster_device_association, backref="clusters", lazy="joined")

    def __repr__(self):
        return f"<Cluster(id={self.id}, name='{self.name}')>"


# ===== 巡检系统模型 =====

class PatrolArea(Base):
    """巡检区域表"""
    __tablename__ = "patrol_areas"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="区域ID")
    name = Column(String(100), nullable=False, comment="区域名称")
    description = Column(Text, nullable=True, comment="描述")
    manager = Column(String(100), nullable=True, comment="负责人")
    boundary = Column(JSON, nullable=True, comment="区域边界多边形坐标 [[lng,lat],...]")
    center_lng = Column(Numeric(10, 7), nullable=True, comment="中心点经度")
    center_lat = Column(Numeric(10, 7), nullable=True, comment="中心点纬度")
    area_sqm = Column(Float, nullable=True, comment="面积(平方米)")
    created_at = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False, comment="更新时间")

    # 关联点位和线路
    points = relationship("PatrolPoint", back_populates="area", cascade="all, delete-orphan")
    routes = relationship("PatrolRoute", back_populates="area", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<PatrolArea(id={self.id}, name='{self.name}')>"


class PatrolPoint(Base):
    """巡检点位表"""
    __tablename__ = "patrol_points"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="点位ID")
    area_id = Column(Integer, ForeignKey("patrol_areas.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属区域ID")
    name = Column(String(100), nullable=False, comment="点位名称")
    description = Column(Text, nullable=True, comment="描述")
    lng = Column(Numeric(10, 7), nullable=False, comment="经度")
    lat = Column(Numeric(10, 7), nullable=False, comment="纬度")
    address = Column(String(255), nullable=True, comment="位置名称(高德逆地理编码)")
    created_at = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False, comment="更新时间")

    area = relationship("PatrolArea", back_populates="points")
    route_points = relationship("PatrolRoutePoint", back_populates="point", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<PatrolPoint(id={self.id}, name='{self.name}')>"


class PatrolRoute(Base):
    """巡检线路表"""
    __tablename__ = "patrol_routes"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="线路ID")
    area_id = Column(Integer, ForeignKey("patrol_areas.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属区域ID")
    name = Column(String(100), nullable=False, comment="线路名称")
    description = Column(Text, nullable=True, comment="描述")
    distance = Column(Float, nullable=True, comment="线路总距离(米)")
    created_at = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False, comment="更新时间")

    area = relationship("PatrolArea", back_populates="routes")
    route_points = relationship("PatrolRoutePoint", back_populates="route", cascade="all, delete-orphan", order_by="PatrolRoutePoint.seq_order")
    tasks = relationship("PatrolTask", back_populates="route")

    def __repr__(self):
        return f"<PatrolRoute(id={self.id}, name='{self.name}')>"


class PatrolRoutePoint(Base):
    """线路-点位关联表（有序）"""
    __tablename__ = "patrol_route_points"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="关联ID")
    route_id = Column(Integer, ForeignKey("patrol_routes.id", ondelete="CASCADE"), nullable=False, index=True, comment="线路ID")
    point_id = Column(Integer, ForeignKey("patrol_points.id", ondelete="CASCADE"), nullable=False, comment="点位ID")
    seq_order = Column(Integer, nullable=False, default=1, comment="顺序编号(从1开始)")

    route = relationship("PatrolRoute", back_populates="route_points")
    point = relationship("PatrolPoint", back_populates="route_points")

    def __repr__(self):
        return f"<PatrolRoutePoint(route_id={self.route_id}, point_id={self.point_id}, order={self.seq_order})>"


class PatrolTask(Base):
    """巡检任务表"""
    __tablename__ = "patrol_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="任务ID")
    route_id = Column(Integer, ForeignKey("patrol_routes.id", ondelete="SET NULL"), nullable=True, index=True, comment="线路ID")
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="SET NULL"), nullable=True, index=True, comment="执行设备ID")
    name = Column(String(100), nullable=False, comment="任务名称")
    status = Column(String(20), default="pending", nullable=False, comment="状态(pending/running/paused/completed/cancelled)")
    gps_track = Column(JSON, nullable=True, comment="GPS轨迹 [{lng,lat,ts}, ...]")
    started_at = Column(DateTime, nullable=True, comment="开始时间")
    ended_at = Column(DateTime, nullable=True, comment="结束时间")
    created_at = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False, comment="更新时间")

    route = relationship("PatrolRoute", back_populates="tasks")
    device = relationship("Device")

    def __repr__(self):
        return f"<PatrolTask(id={self.id}, name='{self.name}', status='{self.status}')>"


class SecurityAlert(Base):
    """安全预警处置记录。"""
    __tablename__ = "security_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="告警ID")
    alert_type = Column(String(64), nullable=False, comment="告警类型")
    severity = Column(String(16), nullable=False, default="medium", index=True, comment="告警等级")
    title = Column(String(200), nullable=False, comment="告警标题")
    description = Column(Text, nullable=True, comment="告警描述")
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="SET NULL"), nullable=True, index=True, comment="来源设备ID")
    source_type = Column(String(64), nullable=False, default="manual", comment="来源类型")
    source_id = Column(String(128), nullable=True, comment="来源记录标识")
    media_path = Column(String(1024), nullable=True, comment="截图或媒体路径")
    occurred_at = Column(DateTime, nullable=False, default=datetime.now, index=True, comment="发生时间")
    status = Column(String(16), nullable=False, default="pending", index=True, comment="处置状态")
    assignee = Column(String(100), nullable=True, comment="处理人")
    handling_note = Column(Text, nullable=True, comment="处理备注")
    acknowledged_at = Column(DateTime, nullable=True, comment="确认时间")
    closed_at = Column(DateTime, nullable=True, comment="关闭时间")
    created_at = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False, comment="更新时间")

    device = relationship("Device")

    def __repr__(self):
        return f"<SecurityAlert(id={self.id}, severity='{self.severity}', status='{self.status}')>"


# ===== 用户角色扩展（RBAC） =====

# ===== 校园室外自主巡检模型（阶段 B/C） =====
#
# 设计原则（参见 docs/requirements/campus-outdoor-autonomous-patrol.md §5.1）：
#   1. 室内 SLAM 巡检表（PatrolArea/Point/Route/Task）与本组表严格分离，
#      不复用、不共享外键，避免坐标类型混用污染室内流程。
#   2. 所有地理坐标必须同时保留坐标类型（coordinate_type）与坐标参考版本
#      （calibration_id），禁止只存两个无单位数值。
#   3. 路线版本一旦冻结（status='frozen'）即不可修改，编辑生成新版本。
#   4. 任务创建时快照路线与标定版本，运行期不受后续编辑影响。


class OutdoorCalibration(Base):
    """校园坐标标定（FR-02）

    每条记录定义一个 ENU 原点（WGS84 经纬度 + 航向），作为路线与任务的
    坐标参考基准。版本号必须唯一；启用新版本前需通过现场对点验证。
    """
    __tablename__ = "outdoor_calibrations"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="标定ID")
    name = Column(String(100), nullable=False, comment="标定名称")
    version = Column(String(64), nullable=False, unique=True,
                    comment="唯一版本号，如 campus-main-v1")
    description = Column(Text, nullable=True, comment="描述")

    # 原点（WGS84）
    origin_lng = Column(Numeric(10, 7), nullable=False, comment="原点经度 (WGS84)")
    origin_lat = Column(Numeric(10, 7), nullable=False, comment="原点纬度 (WGS84)")
    origin_alt = Column(Numeric(10, 3), nullable=True, comment="原点椭球高 (m)")
    origin_yaw = Column(Numeric(8, 5), nullable=False, default=0,
                       comment="ENU 旋转到 ROS map 的偏航角 (rad)")

    # 对点验证记录（启用前的闸门证据）
    verification_geojson = Column(JSON, nullable=True,
                                 comment="对点验证结果 [{known_lng, known_lat, enu_x, enu_y, error_m}], ...]")
    verified_by = Column(String(100), nullable=True, comment="验证人")
    verified_at = Column(DateTime, nullable=True, comment="验证通过时间")

    # 状态：draft → verified → active → deprecated
    status = Column(String(16), nullable=False, default="draft", index=True,
                   comment="状态(draft/verified/active/deprecated)")

    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    # 关联
    routes = relationship("OutdoorRoute", back_populates="calibration")

    def __repr__(self):
        return f"<OutdoorCalibration(id={self.id}, version='{self.version}', status='{self.status}')>"


class OutdoorRoute(Base):
    """室外巡检路线（FR-03）

    绑定到一个校准版本；围栏与速度限制随路线版本冻结。
    """
    __tablename__ = "outdoor_routes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="路线名称")
    description = Column(Text, nullable=True)

    calibration_id = Column(Integer,
                           ForeignKey("outdoor_calibrations.id", ondelete="RESTRICT"),
                           nullable=False, index=True,
                           comment="绑定的坐标标定版本ID")

    version = Column(Integer, nullable=False, default=1, comment="路线版本号")
    parent_id = Column(Integer, ForeignKey("outdoor_routes.id", ondelete="SET NULL"),
                      nullable=True, comment="前一版本路线ID（版本链）")

    # 电子围栏（多边形顶点，ENU 坐标或 WGS84；以 coordinate_type 标识）
    fence_type = Column(String(16), nullable=False, default="polygon",
                       comment="围栏类型(polygon/corridor)")
    fence_geojson = Column(JSON, nullable=True,
                          comment="围栏几何，GeoJSON Feature 或简化坐标数组")
    fence_buffer_m = Column(Numeric(6, 2), nullable=True, default=0.3,
                           comment="围栏边界缓冲距离 (m)")

    # 速度限制与设备类型
    max_speed_ms = Column(Numeric(4, 2), nullable=True, default=0.8,
                          comment="最大允许速度 (m/s)")
    applicable_device_types = Column(JSON, nullable=True,
                                    comment="适用设备类型数组，如 ['无人车']")

    # 状态：draft → published → frozen → deprecated
    status = Column(String(16), nullable=False, default="draft", index=True,
                   comment="路线状态")

    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    calibration = relationship("OutdoorCalibration", back_populates="routes")
    waypoints = relationship("OutdoorWaypoint", back_populates="route",
                            cascade="all, delete-orphan",
                            order_by="OutdoorWaypoint.seq_order")
    tasks = relationship("OutdoorPatrolTask", back_populates="route")
    parent = relationship("OutdoorRoute", remote_side=[id], backref="child_versions")

    def __repr__(self):
        return f"<OutdoorRoute(id={self.id}, name='{self.name}', v{self.version}, status='{self.status}')>"


class OutdoorWaypoint(Base):
    """室外巡检航点（FR-03.2）

    每个航点同时保存 WGS84 与 ENU 两组坐标，互为冗余；
    实际下发给车端时根据接口契约选择使用哪种坐标。
    """
    __tablename__ = "outdoor_waypoints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    route_id = Column(Integer, ForeignKey("outdoor_routes.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    seq_order = Column(Integer, nullable=False, default=1, comment="执行顺序 (从1开始)")
    name = Column(String(100), nullable=False, comment="航点名称")

    # WGS84 坐标（必填，存储与前端展示基准）
    geo_lng = Column(Numeric(10, 7), nullable=False, comment="经度 (WGS84)")
    geo_lat = Column(Numeric(10, 7), nullable=False, comment="纬度 (WGS84)")

    # ENU 坐标（由后端按 calibration_id 转换后冗余存储）
    enu_x = Column(Numeric(10, 3), nullable=True, comment="ENU 东向 (m)")
    enu_y = Column(Numeric(10, 3), nullable=True, comment="ENU 北向 (m)")
    yaw = Column(Numeric(8, 5), nullable=True, comment="期望朝向 (rad)")

    # 到点判定参数
    arrival_radius_m = Column(Numeric(5, 2), nullable=False, default=0.5,
                             comment="到达半径 (m)")
    dwell_seconds = Column(Integer, nullable=False, default=0,
                          comment="到达后停留时长 (s)")

    # 巡检动作（可扩展：take_photo / record_video / pause 等）
    action = Column(String(64), nullable=True, comment="到达后动作")
    action_params = Column(JSON, nullable=True, comment="动作参数")

    # 超时与启用状态
    timeout_seconds = Column(Integer, nullable=False, default=120,
                            comment="最大执行时长 (s)")
    is_enabled = Column(Boolean, nullable=False, default=True,
                       comment="是否启用")

    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    route = relationship("OutdoorRoute", back_populates="waypoints")
    waypoint_results = relationship("OutdoorPatrolEvent", back_populates="waypoint")

    def __repr__(self):
        return f"<OutdoorWaypoint(route_id={self.route_id}, seq={self.seq_order}, name='{self.name}')>"


class OutdoorPatrolTask(Base):
    """室外巡检任务（FR-04）

    任务创建时冻结路线版本与标定版本快照，运行期不受编辑影响。
    所有状态变迁记录在 OutdoorPatrolEvent。
    """
    __tablename__ = "outdoor_patrol_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="任务名称")
    description = Column(Text, nullable=True)

    # 关联
    route_id = Column(Integer, ForeignKey("outdoor_routes.id", ondelete="RESTRICT"),
                     nullable=False, index=True, comment="路线ID")
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="SET NULL"),
                      nullable=True, index=True, comment="执行设备ID")

    # 启动快照（FR-04.5 / 需求 §6.2）
    route_snapshot = Column(JSON, nullable=False,
                           comment="启动时路线冻结副本，含航点序列")
    calibration_snapshot = Column(JSON, nullable=False,
                                 comment="启动时标定版本冻结副本")
    thresholds_snapshot = Column(JSON, nullable=True,
                                comment="启动时安全阈值冻结副本")

    # 计划类型
    schedule_type = Column(String(16), nullable=False, default="immediate",
                         comment="计划类型(immediate/scheduled)")
    scheduled_at = Column(DateTime, nullable=True, comment="计划执行时间")

    # 状态机（FR-04.3）
    # pending → running → completed
    #         → failed / paused / cancelled / safety_stopped
    status = Column(String(20), nullable=False, default="pending", index=True,
                   comment="任务状态")

    # 进度跟踪
    current_waypoint_seq = Column(Integer, nullable=True, comment="当前航点序号")
    precheck_result = Column(JSON, nullable=True,
                            comment="最近一次预检结果（含各项明细）")

    # 时间
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    # 创建者与操作审计
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"),
                       nullable=True, comment="创建用户ID")

    route = relationship("OutdoorRoute", back_populates="tasks")
    device = relationship("Device")
    events = relationship("OutdoorPatrolEvent", back_populates="task",
                         cascade="all, delete-orphan",
                         order_by="OutdoorPatrolEvent.occurred_at")

    def __repr__(self):
        return f"<OutdoorPatrolTask(id={self.id}, name='{self.name}', status='{self.status}')>"


class OutdoorPatrolEvent(Base):
    """室外巡检事件审计（FR-06.2 / FR-07.4）

    记录任务生命周期中的所有事件：状态变迁、航点结果、安全触发、人工操作等。
    每条事件携带发生时间、位置快照与原因，作为可审计、可回放的核心数据。
    """
    __tablename__ = "outdoor_patrol_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("outdoor_patrol_tasks.id", ondelete="CASCADE"),
                    nullable=False, index=True)
    waypoint_id = Column(Integer, ForeignKey("outdoor_waypoints.id", ondelete="SET NULL"),
                        nullable=True, index=True, comment="关联航点（如适用）")

    # 事件类型（参见 EVENT_TYPES 注释）
    event_type = Column(String(32), nullable=False, index=True,
                       comment="事件类型")
    # task_status_change / waypoint_reached / waypoint_failed / waypoint_skipped
    # precheck_passed / precheck_failed
    # localization_lost / fence_breach / obstacle_blocked / nav_abnormal
    # battery_low / control_lost / sensor_failure
    # user_pause / user_resume / user_cancel / user_estop
    # safety_stop / recovery_attempt / recovery_passed

    severity = Column(String(16), nullable=False, default="info",
                     comment="严重等级(info/warn/error/critical)")
    reason = Column(String(255), nullable=True, comment="事件原因（人类可读）")
    detail = Column(JSON, nullable=True, comment="扩展详情")

    # 位置快照（事件发生时的定位）
    loc_lng = Column(Numeric(10, 7), nullable=True, comment="事件位置经度 (WGS84)")
    loc_lat = Column(Numeric(10, 7), nullable=True, comment="事件位置纬度 (WGS84)")
    loc_enu_x = Column(Numeric(10, 3), nullable=True, comment="ENU 东向 (m)")
    loc_enu_y = Column(Numeric(10, 3), nullable=True, comment="ENU 北向 (m)")
    loc_gnss_fix = Column(String(16), nullable=True, comment="GNSS fix 状态")
    loc_health = Column(Boolean, nullable=True, comment="定位健康度")

    # 操作审计
    operator_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"),
                        nullable=True, comment="操作用户ID（人工操作时）")
    occurred_at = Column(DateTime, nullable=False, default=datetime.now, index=True,
                        comment="事件发生时间")

    task = relationship("OutdoorPatrolTask", back_populates="events")
    waypoint = relationship("OutdoorWaypoint", back_populates="waypoint_results")

    def __repr__(self):
        return f"<OutdoorPatrolEvent(id={self.id}, task_id={self.task_id}, type='{self.event_type}')>"


class UserRole(Base):
    """用户角色表：为现有 User 增加 viewer / analyst / admin 角色字段。

    不直接修改老 User 表，避免影响老接口；通过 user_id 关联。
    """
    __tablename__ = "user_roles"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True, comment="用户ID")
    role = Column(String(32), nullable=False, default="viewer", comment="角色(viewer/analyst/admin)")
    created_at = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False, comment="更新时间")

    user = relationship("User", backref="role_ref")

    def __repr__(self):
        return f"<UserRole(user_id={self.user_id}, role='{self.role}')>"


# ===== 数据统计研判模块 =====

class AnalyticsIndicator(Base):
    """指标字典：定义统计指标的计算口径与归属维度。"""
    __tablename__ = "analytics_indicator"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="指标ID")
    code = Column(String(64), unique=True, nullable=False, index=True, comment="指标编码")
    name = Column(String(128), nullable=False, comment="指标名称")
    category = Column(String(64), nullable=False, default="device", comment="分类(device/patrol/alert/energy/external/manual)")
    data_source = Column(String(64), nullable=False, default="telemetry", comment="数据源(telemetry/patrol/alert/external/manual)")
    expression = Column(JSON, nullable=True, comment="计算表达式 DSL")
    unit = Column(String(32), nullable=True, comment="单位")
    granularity = Column(String(16), nullable=False, default="day", comment="粒度(5min/hour/day/week/month)")
    baseline = Column(JSON, nullable=True, comment="基线参数(均值/标准差/阈值)")
    description = Column(Text, nullable=True, comment="指标说明")
    is_active = Column(Boolean, default=True, nullable=False, comment="是否启用")
    created_at = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False, comment="更新时间")

    metric_daily_records = relationship("AnalyticsMetricDaily", back_populates="indicator", cascade="all, delete-orphan")
    rules = relationship("AnalyticsRule", back_populates="indicator")

    def __repr__(self):
        return f"<AnalyticsIndicator(code='{self.code}', name='{self.name}')>"


class AnalyticsEvent(Base):
    """明细事件池：外部 Agent、外部 API、手动录入、文件导入统一写入此表。"""
    __tablename__ = "analytics_event"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="事件ID")
    event_type = Column(String(64), nullable=False, index=True, comment="事件类型")
    source = Column(String(32), nullable=False, default="manual", index=True, comment="来源(agent/api/manual/import)")
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="SET NULL"), nullable=True, index=True, comment="可选关联设备ID")
    occurred_at = Column(DateTime, nullable=False, default=datetime.now, index=True, comment="事件发生时间")
    payload = Column(JSON, nullable=True, comment="事件载荷(自由结构)")
    created_at = Column(DateTime, default=datetime.now, nullable=False, comment="入库时间")

    device = relationship("Device")

    def __repr__(self):
        return f"<AnalyticsEvent(id={self.id}, type='{self.event_type}', source='{self.source}')>"


class AnalyticsMetricDaily(Base):
    """日聚合表：存储按 (指标, 维度, 日期) 的预计算结果。"""
    __tablename__ = "analytics_metric_daily"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="聚合ID")
    indicator_id = Column(Integer, ForeignKey("analytics_indicator.id", ondelete="CASCADE"), nullable=False, index=True, comment="指标ID")
    dimension_key = Column(String(128), nullable=False, default="all", index=True, comment="维度组合(device_id=3 / cluster_id=1 / all)")
    date = Column(DateTime, nullable=False, index=True, comment="统计日期")
    value = Column(Numeric(18, 4), nullable=True, comment="指标值")
    sample_count = Column(Integer, nullable=True, default=0, comment="样本数")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False, comment="更新时间")

    indicator = relationship("AnalyticsIndicator", back_populates="metric_daily_records")

    def __repr__(self):
        return f"<AnalyticsMetricDaily(indicator_id={self.indicator_id}, dim='{self.dimension_key}', date={self.date})>"


class AnalyticsRule(Base):
    """研判规则：定义指标的异常识别条件与命中后生成的告警等级。"""
    __tablename__ = "analytics_rule"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="规则ID")
    name = Column(String(128), nullable=False, comment="规则名称")
    indicator_id = Column(Integer, ForeignKey("analytics_indicator.id", ondelete="CASCADE"), nullable=False, index=True, comment="关联指标ID")
    rule_type = Column(String(32), nullable=False, default="threshold", comment="规则类型(threshold/zscore/consecutive/ratio)")
    condition = Column(JSON, nullable=True, comment="触发条件 JSON")
    severity = Column(String(16), nullable=False, default="medium", comment="触发后告警等级(low/medium/high/critical)")
    alert_type = Column(String(64), nullable=False, default="analytics_rule", comment="写入 SecurityAlert.alert_type")
    description = Column(Text, nullable=True, comment="规则说明")
    is_active = Column(Boolean, default=True, nullable=False, comment="是否启用")
    created_at = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False, comment="更新时间")

    indicator = relationship("AnalyticsIndicator", back_populates="rules")

    def __repr__(self):
        return f"<AnalyticsRule(id={self.id}, name='{self.name}', type='{self.rule_type}')>"


class AnalyticsReportTemplate(Base):
    """报告模板：定义报告包含的指标、时间范围、图表布局。"""
    __tablename__ = "analytics_report_template"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="模板ID")
    name = Column(String(128), nullable=False, comment="模板名称")
    description = Column(Text, nullable=True, comment="模板说明")
    config = Column(JSON, nullable=False, comment="模板配置(指标列表/时间范围/布局)")
    format = Column(String(16), nullable=False, default="pdf", comment="输出格式(pdf/excel)")
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, comment="创建人")
    is_active = Column(Boolean, default=True, nullable=False, comment="是否启用")
    created_at = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False, comment="更新时间")

    runs = relationship("AnalyticsReportRun", back_populates="template", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<AnalyticsReportTemplate(id={self.id}, name='{self.name}')>"


class AnalyticsReportRun(Base):
    """报告生成记录：每次生成一份报告都写入此表，关联导出文件。"""
    __tablename__ = "analytics_report_run"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="运行ID")
    template_id = Column(Integer, ForeignKey("analytics_report_template.id", ondelete="CASCADE"), nullable=False, index=True, comment="模板ID")
    triggered_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, comment="触发用户ID")
    status = Column(String(16), nullable=False, default="pending", comment="状态(pending/running/completed/failed)")
    period_start = Column(DateTime, nullable=True, comment="报告周期开始")
    period_end = Column(DateTime, nullable=True, comment="报告周期结束")
    file_path = Column(String(1024), nullable=True, comment="导出文件相对路径")
    error_message = Column(Text, nullable=True, comment="失败原因")
    started_at = Column(DateTime, nullable=True, comment="开始执行时间")
    finished_at = Column(DateTime, nullable=True, comment="完成时间")
    created_at = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")

    template = relationship("AnalyticsReportTemplate", back_populates="runs")

    def __repr__(self):
        return f"<AnalyticsReportRun(id={self.id}, template={self.template_id}, status='{self.status}')>"


class AnalyticsNotification(Base):
    """站内消息：研判模块向用户推送的通知。"""
    __tablename__ = "analytics_notification"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="通知ID")
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True, comment="接收用户ID")
    title = Column(String(200), nullable=False, comment="标题")
    content = Column(Text, nullable=True, comment="内容")
    category = Column(String(32), nullable=False, default="alert", comment="类别(alert/report/system)")
    ref_type = Column(String(32), nullable=True, comment="关联类型(alert/rule/report)")
    ref_id = Column(Integer, nullable=True, comment="关联记录ID")
    is_read = Column(Boolean, default=False, nullable=False, comment="是否已读")
    created_at = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")

    def __repr__(self):
        return f"<AnalyticsNotification(id={self.id}, user_id={self.user_id}, title='{self.title}')>"
