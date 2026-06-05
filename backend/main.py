"""
异构无人集群管理平台 - 后端服务

基于 FastAPI 框架构建的 RESTful API 后端服务。
提供用户认证、用户管理、设备管理、真实无人车 TCP 控制和 IoT 遥测接口。
"""

from fastapi import FastAPI, HTTPException, Depends, Response, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from passlib.hash import bcrypt
import os
import jwt
import json
import socket
import time
import hashlib
import secrets
import threading
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from typing import Optional, Any
from fastapi.concurrency import run_in_threadpool

from database import get_db
from models import User, Device, Cluster, DeviceTelemetry, DeviceToken, \
    PatrolArea, PatrolPoint, PatrolRoute, PatrolRoutePoint, PatrolTask

# 确保加载环境变量
load_dotenv()

# JWT 配置
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dwc-default-secret-key")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))

# 机器人控制配置
ROBOT_CONTROL_MAX_LINEAR = float(os.getenv("ROBOT_CONTROL_MAX_LINEAR", "0.4"))
ROBOT_CONTROL_MAX_ANGULAR = float(os.getenv("ROBOT_CONTROL_MAX_ANGULAR", "1.2"))
ROBOT_CONTROL_TIMEOUT_SECONDS = float(os.getenv("ROBOT_CONTROL_TIMEOUT_SECONDS", "3.0"))

# 设备在线判定超时（秒）：超过此时间未收到遥测则判定为离线
DEVICE_ONLINE_TIMEOUT_SECONDS = int(os.getenv("DEVICE_ONLINE_TIMEOUT_SECONDS", "180"))

# TCP 连接池（缓存到树莓派控制服务的 TCP 连接）
_robot_control_state: dict[str, Any] = {"connections": {}}
_robot_control_locks_lock = threading.Lock()
_robot_control_locks = {}

def _get_robot_lock(key: str) -> threading.Lock:
    with _robot_control_locks_lock:
        if key not in _robot_control_locks:
            _robot_control_locks[key] = threading.Lock()
        return _robot_control_locks[key]


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def get_current_user(request: Request, db: Session = Depends(get_db)):
    """
    从 Cookie 中提取 JWT Token，验证并返回当前用户

    用于需要认证的接口的依赖注入。
    """
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="未登录，请先登录")

    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="无效的认证信息")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效的认证信息")

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")

    return user


# 创建 FastAPI 应用实例
app = FastAPI(
    title="异构无人集群管理平台",
    description="基于 FastAPI 的异构无人集群管理平台后端 API",
    version="0.3.0",
)

# 配置 CORS 跨域中间件，允许前端开发服务器访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite 默认开发服务器地址
        "http://127.0.0.1:5173",
        "http://192.168.31.28:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有 HTTP 方法
    allow_headers=["*"],  # 允许所有请求头
)


# ===== 数据模型 =====

class LoginRequest(BaseModel):
    """登录请求体"""
    username: str
    password: str


class LoginResponse(BaseModel):
    """登录响应体"""
    message: str
    username: str
    token: str
    nickname: Optional[str] = None


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


class DeviceCreate(BaseModel):
    """创建设备请求体"""
    name: str
    type: str
    ip_address: str
    port: int = 9000
    password: str  # 设备连接密码，用于向设备注册并获取 token
    server_address: str  # 后端服务器地址（设备通过此地址上报遥测数据）


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
    ip_address: str
    port: int
    status: str
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


# ===== TCP 控制辅助函数 =====

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


def _target_key(host: str, port: int) -> str:
    """生成 TCP 连接缓存 key"""
    return f"{host}:{port}"


def _close_robot_socket(host: str, port: int) -> None:
    """关闭到指定目标的缓存 TCP 连接"""
    connections = _robot_control_state["connections"]
    key = _target_key(host, port)
    conn = connections.pop(key, None)
    if conn and conn.get("socket"):
        try:
            conn["socket"].close()
        except OSError:
            pass


def _get_robot_socket(host: str, port: int) -> socket.socket:
    """获取到树莓派控制服务的 TCP 连接（带缓存）"""
    connections = _robot_control_state["connections"]
    key = _target_key(host, port)
    conn = connections.get(key)
    if conn and conn.get("socket"):
        return conn["socket"]
    try:
        active_socket = socket.create_connection(
            (host, port),
            timeout=ROBOT_CONTROL_TIMEOUT_SECONDS,
        )
    except OSError as exc:
        raise HTTPException(status_code=502, detail=f"无人车控制服务不可达: {host}:{port}") from exc
    active_socket.settimeout(ROBOT_CONTROL_TIMEOUT_SECONDS)
    connections[key] = {"socket": active_socket, "buffer": b""}
    return active_socket


def _read_robot_message(active_socket: socket.socket, key: str) -> dict:
    """从 TCP 连接读取一条 JSON 消息"""
    connections = _robot_control_state["connections"]
    conn = connections.get(key, {"buffer": b""})
    buf = conn.get("buffer", b"")
    while b"\n" not in buf:
        chunk = active_socket.recv(4096)
        if not chunk:
            raise ConnectionError("无人车控制连接已断开。")
        buf += chunk
    line, buf = buf.split(b"\n", 1)
    conn["buffer"] = buf
    parsed = json.loads(line.decode("utf-8"))
    print(f"[{datetime.now()}] [TCP RECV] from {key} -> {parsed}", flush=True)
    return parsed


def _send_robot_message_once(host: str, port: int, payload: dict, expected_type: str) -> dict:
    """发送一条消息并等待预期类型的响应"""
    key = _target_key(host, port)
    active_socket = _get_robot_socket(host, port)
    data = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
    print(f"[{datetime.now()}] [TCP SEND] to {key} -> {payload}", flush=True)
    active_socket.sendall(data)
    deadline = time.time() + ROBOT_CONTROL_TIMEOUT_SECONDS
    while time.time() < deadline:
        message = _read_robot_message(active_socket, key)
        if message.get("type") == expected_type:
            return message
    _close_robot_socket(host, port)
    raise HTTPException(status_code=504, detail="无人车控制服务响应超时。")


def send_robot_control_message(host: str, port: int, payload: dict, expected_type: str) -> dict:
    """
    向树莓派控制服务发送消息并等待响应。
    支持缓存连接自动重连一次。
    """
    key = _target_key(host, port)
    lock = _get_robot_lock(key)
    with lock:
        has_cached = key in _robot_control_state["connections"]
        for attempt in range(2 if has_cached else 1):
            try:
                return _send_robot_message_once(host, port, payload, expected_type)
            except HTTPException:
                raise
            except (ConnectionError, OSError, json.JSONDecodeError):
                _close_robot_socket(host, port)
                if attempt == 0 and has_cached:
                    continue
                raise HTTPException(status_code=502, detail="无人车控制服务响应异常。")
    raise HTTPException(status_code=502, detail="无人车控制服务响应异常。")


def normalize_control_value(value: Any, limit: float, field: str) -> float:
    """对控制值进行限幅"""
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{field} 必须是数字。") from exc
    return max(-limit, min(limit, parsed))


def _register_device_tcp(host: str, port: int, register_payload: dict) -> dict:
    """
    通过独立的 TCP 连接向设备 robot_control_server 发送 register 消息并读取响应。

    注册流程（参照 robot_control_server.py 的 handle_client）：
    1. 建立 TCP 连接
    2. 发送 {"type":"register", "password":"...", "server_address":"..."}\n
    3. 读取 {"type":"register_result", "ok":true/false, "token":"...", ...}\n
    4. 关闭连接

    不复用连接池，因为注册只在添加设备时执行一次。
    """
    try:
        sock = socket.create_connection((host, port), timeout=ROBOT_CONTROL_TIMEOUT_SECONDS)
    except OSError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"无法连接到设备 {host}:{port}，请检查设备是否在线",
        ) from exc

    try:
        sock.settimeout(ROBOT_CONTROL_TIMEOUT_SECONDS + 2)
        # 发送 register 消息
        data = (json.dumps(register_payload, separators=(",", ":")) + "\n").encode("utf-8")
        print(f"[{datetime.now()}] [TCP SEND] to {host}:{port} (Register) -> {register_payload}", flush=True)
        sock.sendall(data)

        # 读取响应
        buf = b""
        deadline = time.time() + ROBOT_CONTROL_TIMEOUT_SECONDS + 2
        while b"\n" not in buf:
            if time.time() > deadline:
                raise HTTPException(status_code=504, detail="设备注册响应超时")
            chunk = sock.recv(4096)
            if not chunk:
                raise HTTPException(status_code=502, detail="设备连接在等待注册响应时断开")
            buf += chunk

        line, _ = buf.split(b"\n", 1)
        response = json.loads(line.decode("utf-8"))
        print(f"[{datetime.now()}] [TCP RECV] from {host}:{port} (Register) -> {response}", flush=True)
        return response
    finally:
        try:
            sock.close()
        except OSError:
            pass


def resolve_device_target(device_id: int, db: Session) -> tuple[str, int]:
    """解析设备的控制目标（IP 和端口）"""
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    if not device.ip_address:
        raise HTTPException(status_code=422, detail="设备未配置 IP 地址，无法控制。")
    return device.ip_address, device.port or 9000


def update_device_online_status(db: Session) -> None:
    """根据 last_seen 更新设备在线状态"""
    cutoff = datetime.now() - timedelta(seconds=DEVICE_ONLINE_TIMEOUT_SECONDS)
    # 将超时未上报的设备标记为离线
    db.query(Device).filter(
        Device.last_seen != None,
        Device.last_seen < cutoff,
        Device.status == "online"
    ).update({"status": "offline"}, synchronize_session="fetch")
    # 将从未上报过，但添加时间已经超过超时的设备标记为离线
    db.query(Device).filter(
        Device.last_seen == None,
        Device.created_at < cutoff,
        Device.status == "online"
    ).update({"status": "offline"}, synchronize_session="fetch")
    db.commit()


# ===== 路由接口 =====

@app.get("/")
async def root():
    """根路径接口，返回欢迎信息"""
    return {"message": "欢迎使用异构无人集群管理平台 API"}


@app.get("/api/health")
async def health_check():
    """健康检查接口"""
    return {"status": "ok", "message": "服务运行正常"}


@app.post("/api/auth/login")
async def login(request: LoginRequest, response: Response, db: Session = Depends(get_db)):
    """
    用户登录接口

    从 MySQL 数据库查询用户，使用 bcrypt 验证密码。
    测试账号可在 .env 中配置 (DEFAULT_ADMIN_USER / DEFAULT_ADMIN_PASSWORD)。
    """
    # 从数据库查询用户
    user = db.query(User).filter(User.username == request.username).first()

    if user is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 验证密码（bcrypt 哈希比对）
    if not bcrypt.verify(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 检查用户是否被禁用
    if not user.is_active:
        raise HTTPException(status_code=403, detail="该账号已被禁用")

    # 生成 JWT token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )

    # 通过 Set-Cookie 下发 JWT
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        secure=False,  # 开发环境设为False，生产环境 HTTPS 建议设为 True
    )

    return LoginResponse(
        message="登录成功",
        username=user.username,
        token=access_token,
        nickname=user.nickname,
    )


# ===== 用户管理接口 =====

@app.get("/api/users", response_model=list[UserResponse])
async def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取所有用户列表（需登录）"""
    users = db.query(User).order_by(User.id.asc()).all()
    return users


@app.post("/api/users", response_model=UserResponse)
async def create_user(
    user_data: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建新用户（需登录）"""
    # 检查用户名是否已存在
    existing = db.query(User).filter(User.username == user_data.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")

    # 创建用户
    new_user = User(
        username=user_data.username,
        password_hash=bcrypt.hash(user_data.password),
        nickname=user_data.nickname,
        is_active=user_data.is_active,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@app.put("/api/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_data: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新用户信息（需登录）"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 更新字段
    if user_data.password is not None and user_data.password.strip():
        user.password_hash = bcrypt.hash(user_data.password)
    if user_data.nickname is not None:
        user.nickname = user_data.nickname
    if user_data.is_active is not None:
        user.is_active = user_data.is_active

    db.commit()
    db.refresh(user)
    return user


@app.delete("/api/users/{user_id}")
async def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除用户（需登录）"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 防止删除自己
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录的用户")

    db.delete(user)
    db.commit()
    return {"message": f"用户 {user.username} 已删除"}


# ===== 设备管理接口 =====

def _build_device_response(dev: Device, db: Session) -> dict:
    """构建设备响应，附带最新遥测扩展信息"""
    extra = None
    # 查询最新遥测记录的扩展信息
    latest_telemetry = db.query(DeviceTelemetry).filter(
        DeviceTelemetry.device_id == dev.id
    ).order_by(DeviceTelemetry.reported_at.desc()).first()

    if latest_telemetry and latest_telemetry.extra_json:
        extra = latest_telemetry.extra_json

    return {
        "id": dev.id,
        "name": dev.name,
        "type": dev.type,
        "ip_address": dev.ip_address,
        "port": dev.port or 9000,
        "status": dev.status or "offline",
        "battery": dev.battery,
        "health": dev.health or 100,
        "signal": dev.signal,
        "speed": dev.speed or "0 m/s",
        "lat": dev.lat,
        "lng": dev.lng,
        "last_seen": dev.last_seen.isoformat() if dev.last_seen else None,
        "created_at": dev.created_at.isoformat() if dev.created_at else None,
        "updated_at": dev.updated_at.isoformat() if dev.updated_at else None,
        "extra": extra,
    }


@app.get("/api/devices")
async def list_devices(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取所有设备列表，并自动更新在线状态（需登录）"""
    # 根据 last_seen 自动更新在线/离线状态
    update_device_online_status(db)
    devices = db.query(Device).order_by(Device.id.asc()).all()
    return [_build_device_response(dev, db) for dev in devices]


@app.post("/api/devices")
async def create_device(
    device_data: DeviceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    添加设备（需登录）。

    流程：
    1. 通过 TCP 连接到设备的 robot_control_server
    2. 发送 register 消息（携带连接密码和本后端 server_address）
    3. 设备验证密码后生成 token 并返回
    4. 后端将设备信息和 token 存入数据库
    """
    existing = db.query(Device).filter(Device.ip_address == device_data.ip_address).first()
    if existing:
        raise HTTPException(status_code=400, detail="该IP地址的设备已存在")

    # 验证端口号范围
    port = device_data.port
    if port < 1 or port > 65535:
        raise HTTPException(status_code=422, detail="端口号必须在 1 到 65535 之间")

    # ---- 通过 TCP 向设备注册，获取 token ----
    register_payload = {
        "type": "register",
        "password": device_data.password,
        "server_address": device_data.server_address,
    }

    try:
        register_response = await run_in_threadpool(
            _register_device_tcp,
            device_data.ip_address,
            port,
            register_payload,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"无法连接到设备 {device_data.ip_address}:{port}，请检查设备是否在线: {exc}",
        )

    if not register_response.get("ok"):
        err_msg = register_response.get("err", "注册失败")
        raise HTTPException(status_code=400, detail=f"设备注册失败: {err_msg}")

    device_token = register_response.get("token", "")
    if not device_token:
        raise HTTPException(status_code=502, detail="设备注册成功但未返回 token")

    # ---- 存入数据库 ----
    new_device = Device(
        name=device_data.name,
        type=device_data.type,
        ip_address=device_data.ip_address,
        port=port,
        status="online",
        last_seen=None,
        health=100,
        speed="0 m/s",
    )
    db.add(new_device)
    db.commit()
    db.refresh(new_device)

    # 将设备返回的 token 存入 device_tokens 表
    new_token = DeviceToken(
        device_id=new_device.id,
        token=device_token,
        note=f"设备注册时自动生成，由 {current_user.username} 添加",
        is_active=True,
    )
    db.add(new_token)
    db.commit()

    return _build_device_response(new_device, db)


@app.put("/api/devices/{device_id}")
async def update_device(
    device_id: int,
    device_data: DeviceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新设备信息（需登录）"""
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")

    if device_data.name is not None:
        device.name = device_data.name
    if device_data.type is not None:
        device.type = device_data.type
    if device_data.ip_address is not None:
        device.ip_address = device_data.ip_address
    if device_data.port is not None:
        if device_data.port < 1 or device_data.port > 65535:
            raise HTTPException(status_code=422, detail="端口号必须在 1 到 65535 之间")
        device.port = device_data.port

    db.commit()
    db.refresh(device)
    return _build_device_response(device, db)


@app.delete("/api/devices/{device_id}")
async def delete_device(
    device_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除设备（需登录）"""
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")

    db.delete(device)
    db.commit()
    return {"message": f"设备 {device.name} 已删除"}


@app.get("/api/wifi/scan")
async def scan_wifi(subnet: str = "192.168.31.0/24", current_user: User = Depends(get_current_user)):
    """
    使用 nmap 扫描局域网内的设备 IP（需登录）。
    支持前端传入自定义扫描网段，并提供 ARP 缓存表读取作为备用/降级机制。
    """
    import subprocess
    import re
    
    # 安全校验网段格式
    if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d{1,2}$', subnet):
        subnet = "192.168.31.0/24"
        
    devices = []
    try:
        # 使用 nmap -sn -n -T5 扫描网段
        result = subprocess.run(
            ['nmap', '-sn', '-n', '-T5', subnet],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=15
        )
        output = result.stdout
        
        # 解析 nmap 扫描块
        blocks = output.split("Nmap scan report for ")
        for block in blocks[1:]:
            lines = block.strip().splitlines()
            if not lines:
                continue
            
            ip_match = re.match(r'^(\d+\.\d+\.\d+\.\d+)', lines[0])
            if not ip_match:
                continue
            ip = ip_match.group(1)
            
            mac = ""
            vendor = ""
            for line in lines[1:]:
                mac_match = re.search(r'MAC Address:\s*([0-9a-fA-F:-]{17})(?:\s+\((.*?)\))?', line)
                if mac_match:
                    mac = mac_match.group(1).replace('-', ':').upper()
                    vendor = mac_match.group(2) or ""
                    break
            
            type_str = "未知设备"
            mac_lower = mac.lower() if mac else ""
            vendor_lower = vendor.lower() if vendor else ""
            
            if "dji" in vendor_lower or "uav" in vendor_lower:
                type_str = "无人机"
            elif "raspberry" in vendor_lower or "robot" in vendor_lower:
                type_str = "无人车"
            elif "04:67" in mac_lower or "04-67" in mac_lower:
                type_str = "无人机"
            elif "74:4c" in mac_lower or "74-4c" in mac_lower:
                type_str = "无人车"
                
            ssid = f"Device_{mac[-5:].replace(':', '').replace('-', '').upper()}" if mac else f"Device_{ip.split('.')[-1]}"
            devices.append({
                "ip": ip,
                "mac": mac or "未知",
                "ssid": ssid,
                "type": type_str,
                "vendor": vendor or "未知"
            })
            
    except Exception as nmap_exc:
        # 如果 nmap 报错（如未安装），则优雅降级为使用本地 ARP 表扫描
        print(f"nmap 扫描不可用或出错，将使用 ARP 作为备用方案: {nmap_exc}")
        try:
            # 兼容 Windows 和 Linux 的 arp 读取
            is_windows = os.name == 'nt'
            if is_windows:
                result = subprocess.run(['arp', '-a'], capture_output=True, text=True, encoding='cp936', errors='replace', timeout=5)
                output = result.stdout
                pattern = re.compile(r'^\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F:-]{17})\s+', re.MULTILINE)
                matches = pattern.findall(output)
            else:
                result = subprocess.run(['arp', '-n'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5)
                output = result.stdout
                pattern = re.compile(r'(\d+\.\d+\.\d+\.\d+)\s+\w+\s+([0-9a-fA-F:-]{17})', re.MULTILINE)
                matches = pattern.findall(output)

            for ip, mac in matches:
                if ip.startswith('224.') or ip.startswith('239.') or ip.endswith('.255') or ip == '255.255.255.255':
                    continue
                
                type_str = "未知设备"
                ssid = f"Device_{mac[-5:].replace('-', '').replace(':', '').upper()}"
                mac_lower = mac.lower()
                if "04-67" in mac_lower or "04:67" in mac_lower: type_str = "无人机"
                elif "74-4c" in mac_lower or "74:4c" in mac_lower: type_str = "无人车"
                
                devices.append({
                    "ip": ip,
                    "mac": mac.replace('-', ':').upper(),
                    "ssid": ssid,
                    "type": type_str,
                    "vendor": "未知"
                })
        except Exception as arp_exc:
            print(f"ARP 备用扫描亦出错: {arp_exc}")
            
    return devices


# ===== 真实无人车 TCP 控制接口 =====

@app.get("/api/robot-control/status")
async def robot_control_status(
    robotId: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    检测无人车控制服务是否可达（需登录）。
    向树莓派发送 ping 消息，等待 pong 响应。
    连接成功后自动将设备标记为在线并更新 last_seen。
    """
    if robotId is None:
        raise HTTPException(status_code=422, detail="请选择一个设备")
    
    print(f"[{datetime.now()}] [HTTP REQ] GET /api/robot-control/status?robotId={robotId}", flush=True)
    host, port = resolve_device_target(robotId, db)
    response = await run_in_threadpool(send_robot_control_message, host, port, {"type": "ping"}, "pong")
    print(f"[{datetime.now()}] [HTTP RES] /api/robot-control/status -> {response}", flush=True)
    
    # TCP ping 成功 → 标记设备在线
    device = db.query(Device).filter(Device.id == robotId).first()
    if device:
        device.status = "online"
        device.last_seen = datetime.now()
        db.commit()
    
    return {"ok": True, "target": {"host": host, "port": port}, "response": response}


@app.post("/api/robot-control/cmd_vel")
async def robot_control_cmd_vel(
    cmd: RobotControlCmdVel,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    发送线速度和角速度控制指令到树莓派（需登录）。
    速度值会被后端限幅，防止异常请求绕过前端限制。
    """
    if cmd.robotId is None:
        raise HTTPException(status_code=422, detail="请选择一个设备")
    
    print(f"[{datetime.now()}] [HTTP REQ] POST /api/robot-control/cmd_vel Body: {cmd.dict()}", flush=True)
    host, port = resolve_device_target(cmd.robotId, db)
    linear = normalize_control_value(cmd.linear, ROBOT_CONTROL_MAX_LINEAR, "linear")
    angular = normalize_control_value(cmd.angular, ROBOT_CONTROL_MAX_ANGULAR, "angular")
    response = await run_in_threadpool(
        send_robot_control_message,
        host, port,
        {"type": "cmd_vel", "v": linear, "w": angular},
        "ack"
    )
    print(f"[{datetime.now()}] [HTTP RES] /api/robot-control/cmd_vel -> {response}", flush=True)
    
    # TCP 指令成功 → 更新设备在线状态
    device = db.query(Device).filter(Device.id == cmd.robotId).first()
    if device:
        device.status = "online"
        device.last_seen = datetime.now()
        db.commit()
    
    return {
        "ok": bool(response.get("ok")),
        "target": {"host": host, "port": port},
        "linear": linear,
        "angular": angular,
        "response": response,
    }


@app.post("/api/robot-control/stop")
async def robot_control_stop(
    cmd: RobotControlStop,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    发送停车指令到树莓派（需登录）。
    松开按键、切换设备、离开页面时都应调用此接口。
    """
    if cmd.robotId is None:
        raise HTTPException(status_code=422, detail="请选择一个设备")
    
    print(f"[{datetime.now()}] [HTTP REQ] POST /api/robot-control/stop Body: {cmd.dict()}", flush=True)
    host, port = resolve_device_target(cmd.robotId, db)
    response = await run_in_threadpool(send_robot_control_message, host, port, {"type": "stop"}, "ack")
    print(f"[{datetime.now()}] [HTTP RES] /api/robot-control/stop -> {response}", flush=True)
    
    # TCP 指令成功 → 更新设备在线状态
    device = db.query(Device).filter(Device.id == cmd.robotId).first()
    if device:
        device.status = "online"
        device.last_seen = datetime.now()
        db.commit()
    
    return {"ok": bool(response.get("ok")), "target": {"host": host, "port": port}, "response": response}


@app.post("/api/robot-control/send")
async def robot_control_send(
    cmd: RobotControlSend,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    向设备发送自定义 TCP JSON 指令（需登录）。
    前端直接传入完整的 JSON 字符串，后端转发到设备 TCP 端口。
    """
    if cmd.robotId is None:
        raise HTTPException(status_code=422, detail="请选择一个设备")
    
    print(f"[{datetime.now()}] [HTTP REQ] POST /api/robot-control/send Body: {cmd.dict()}", flush=True)
    
    # 解析用户输入的 JSON 指令
    try:
        payload = json.loads(cmd.command)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"指令必须是合法的 JSON: {exc}") from exc
    
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="指令必须是 JSON 对象")
    
    # 根据 type 决定期望的响应类型
    msg_type = payload.get("type", "")
    expected = "pong" if msg_type == "ping" else "ack"
    
    host, port = resolve_device_target(cmd.robotId, db)
    response = await run_in_threadpool(send_robot_control_message, host, port, payload, expected)
    print(f"[{datetime.now()}] [HTTP RES] /api/robot-control/send -> {response}", flush=True)
    
    # 成功发送指令 → 标记设备在线
    device = db.query(Device).filter(Device.id == cmd.robotId).first()
    if device:
        device.status = "online"
        device.last_seen = datetime.now()
        db.commit()
    
    return {
        "ok": True,
        "target": {"host": host, "port": port},
        "sent": payload,
        "response": response,
    }


@app.get("/api/robot-control/config")
async def robot_control_config(
    current_user: User = Depends(get_current_user),
):
    """返回控制参数配置，供前端使用（需登录）"""
    return {
        "maxLinear": ROBOT_CONTROL_MAX_LINEAR,
        "maxAngular": ROBOT_CONTROL_MAX_ANGULAR,
    }


# ===== IoT 遥测接口 =====

@app.post("/api/iot/telemetry")
async def iot_telemetry(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    IoT 设备遥测数据上报接口。

    树莓派通过 X-Device-Token 头进行认证，定期上报设备状态。
    上报数据包括：status, battery, signal, lat, lng, extra(cpu_temp, gps 状态等)
    """
    # 通过设备 Token 认证
    token = request.headers.get("X-Device-Token")
    if not token:
        raise HTTPException(status_code=401, detail="缺少设备 Token")

    device_token = db.query(DeviceToken).filter(
        DeviceToken.token == token,
        DeviceToken.is_active == True,
    ).first()
    if not device_token:
        raise HTTPException(status_code=401, detail="设备 Token 无效或已禁用")

    device = db.query(Device).filter(Device.id == device_token.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")

    # 解析上报数据
    try:
        payload = await request.json()
        print(f"[{datetime.now()}] /api/iot/ request body: {payload}")
    except Exception:
        raise HTTPException(status_code=422, detail="请求体必须是合法的 JSON")

    now = datetime.now()
    reported_at_str = payload.get("reportedAt")
    if reported_at_str:
        try:
            reported_at = datetime.fromisoformat(reported_at_str)
        except ValueError:
            reported_at = now
    else:
        reported_at = now

    # 更新设备主表状态
    device.status = payload.get("status", "online")
    if payload.get("battery") is not None:
        device.battery = int(payload["battery"])
    if payload.get("signal") is not None:
        device.signal = int(payload["signal"])
    if payload.get("lat") is not None:
        device.lat = str(payload["lat"])
    if payload.get("lng") is not None:
        device.lng = str(payload["lng"])
    device.last_seen = now

    # 获取来源IP
    source_ip = request.client.host if request.client else None

    # 插入遥测记录
    telemetry = DeviceTelemetry(
        device_id=device.id,
        battery=payload.get("battery"),
        signal=payload.get("signal"),
        status=payload.get("status", "online"),
        lat=payload.get("lat"),
        lng=payload.get("lng"),
        source_ip=source_ip,
        extra_json=payload.get("extra"),
        reported_at=reported_at,
    )
    db.add(telemetry)
    db.commit()

    return {"ok": True, "deviceId": device.id, "receivedAt": now.isoformat()}


@app.get("/api/devices/{device_id}/telemetry")
async def get_device_telemetry(
    device_id: int,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取设备的遥测记录历史（需登录）"""
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")

    records = db.query(DeviceTelemetry).filter(
        DeviceTelemetry.device_id == device_id
    ).order_by(DeviceTelemetry.reported_at.desc()).limit(min(limit, 100)).all()

    return [
        {
            "id": r.id,
            "battery": r.battery,
            "signal": r.signal,
            "status": r.status,
            "lat": str(r.lat) if r.lat else None,
            "lng": str(r.lng) if r.lng else None,
            "source_ip": r.source_ip,
            "extra": r.extra_json,
            "reported_at": r.reported_at.isoformat() if r.reported_at else None,
        }
        for r in records
    ]


# ===== 设备 Token 管理接口 =====

@app.get("/api/devices/{device_id}/tokens")
async def list_device_tokens(
    device_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取设备的认证 Token 列表（需登录）"""
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")

    tokens = db.query(DeviceToken).filter(
        DeviceToken.device_id == device_id
    ).order_by(DeviceToken.id.desc()).all()

    return [
        {
            "id": t.id,
            "token": t.token,
            "note": t.note,
            "is_active": t.is_active,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in tokens
    ]


@app.post("/api/devices/{device_id}/tokens")
async def create_device_token(
    device_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """为设备生成新的认证 Token（需登录）"""
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")

    # 生成 Token
    raw = f"{device_id}-{secrets.token_hex(16)}-{datetime.now().isoformat()}"
    token_value = hashlib.sha256(raw.encode()).hexdigest()

    new_token = DeviceToken(
        device_id=device_id,
        token=token_value,
        note=f"由 {current_user.username} 创建",
        is_active=True,
    )
    db.add(new_token)
    db.commit()
    db.refresh(new_token)

    return {
        "ok": True,
        "token": token_value,
        "id": new_token.id,
    }


# ===== 集群管理接口 =====

@app.get("/api/clusters", response_model=list[ClusterResponse])
async def list_clusters(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取所有集群列表（需登录）"""
    clusters = db.query(Cluster).order_by(Cluster.id.asc()).all()
    return clusters


@app.post("/api/clusters", response_model=ClusterResponse)
async def create_cluster(
    cluster_data: ClusterCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建新集群（需登录）"""
    existing = db.query(Cluster).filter(Cluster.name == cluster_data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="集群名称已存在")
    
    new_cluster = Cluster(
        name=cluster_data.name,
        description=cluster_data.description
    )
    db.add(new_cluster)
    db.commit()
    db.refresh(new_cluster)
    return new_cluster


@app.put("/api/clusters/{cluster_id}", response_model=ClusterResponse)
async def update_cluster(
    cluster_id: int,
    cluster_data: ClusterUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新集群信息（需登录）"""
    cluster = db.query(Cluster).filter(Cluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="集群不存在")
    
    if cluster_data.name is not None:
        cluster.name = cluster_data.name
    if cluster_data.description is not None:
        cluster.description = cluster_data.description

    db.commit()
    db.refresh(cluster)
    return cluster


@app.delete("/api/clusters/{cluster_id}")
async def delete_cluster(
    cluster_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除集群（需登录）"""
    cluster = db.query(Cluster).filter(Cluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="集群不存在")
    
    db.delete(cluster)
    db.commit()
    return {"message": f"集群 {cluster.name} 已删除"}


@app.post("/api/clusters/{cluster_id}/devices")
async def add_device_to_cluster(
    cluster_id: int,
    device_data: ClusterAddDevice,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """向集群中添加设备（需登录）"""
    cluster = db.query(Cluster).filter(Cluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="集群不存在")
    
    device = db.query(Device).filter(Device.id == device_data.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    
    if device in cluster.devices:
        raise HTTPException(status_code=400, detail="设备已在该集群中")
    
    cluster.devices.append(device)
    db.commit()
    return {"message": "设备添加成功"}


@app.delete("/api/clusters/{cluster_id}/devices/{device_id}")
async def remove_device_from_cluster(
    cluster_id: int,
    device_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """从集群移除设备（需登录）"""
    cluster = db.query(Cluster).filter(Cluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="集群不存在")
    
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device or device not in cluster.devices:
        raise HTTPException(status_code=404, detail="设备不在该集群中")
    
    cluster.devices.remove(device)
    db.commit()
    return {"message": "设备移除成功"}


@app.post("/api/clusters/{cluster_id}/cmd_vel")
async def cluster_control_cmd_vel(
    cluster_id: int,
    cmd: RobotControlCmdVel,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """向集群中的在线设备批量发送运动指令（需登录）"""
    cluster = db.query(Cluster).filter(Cluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="集群不存在")
    
    online_devices = [d for d in cluster.devices if d.status == "online"]
    if not online_devices:
        raise HTTPException(status_code=400, detail="集群中没有在线的设备")
    
    linear = normalize_control_value(cmd.linear, ROBOT_CONTROL_MAX_LINEAR, "linear")
    angular = normalize_control_value(cmd.angular, ROBOT_CONTROL_MAX_ANGULAR, "angular")
    
    results = []
    
    async def _send_to_device(device):
        try:
            response = await run_in_threadpool(
                send_robot_control_message,
                device.ip_address, device.port or 9000,
                {"type": "cmd_vel", "v": linear, "w": angular},
                "ack"
            )
            print(f"[{datetime.now()}] Cluster {cluster_id} Device {device.id} Response: {response}")
            return {"device": device, "device_id": device.id, "ok": True, "response": response}
        except HTTPException as exc:
            return {"device": device, "device_id": device.id, "ok": False, "error": exc.detail}

    tasks = [_send_to_device(d) for d in online_devices]
    outcomes = await asyncio.gather(*tasks)

    for outcome in outcomes:
        device = outcome.pop("device")
        if outcome["ok"]:
            device.last_seen = datetime.now()
        results.append(outcome)
    
    db.commit()
    success_count = sum(1 for r in results if r["ok"])
    return {"message": f"指令已下发至 {success_count}/{len(online_devices)} 台设备", "results": results}


@app.post("/api/clusters/{cluster_id}/stop")
async def cluster_control_stop(
    cluster_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """向集群中的在线设备批量发送停车指令（需登录）"""
    cluster = db.query(Cluster).filter(Cluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="集群不存在")
    
    online_devices = [d for d in cluster.devices if d.status == "online"]
    if not online_devices:
        raise HTTPException(status_code=400, detail="集群中没有在线的设备")
    
    results = []

    async def _send_to_device(device):
        try:
            response = await run_in_threadpool(
                send_robot_control_message,
                device.ip_address, device.port or 9000,
                {"type": "stop"},
                "ack"
            )
            print(f"[{datetime.now()}] Cluster {cluster_id} Device {device.id} Response: {response}")
            return {"device": device, "device_id": device.id, "ok": True, "response": response}
        except HTTPException as exc:
            return {"device": device, "device_id": device.id, "ok": False, "error": exc.detail}

    tasks = [_send_to_device(d) for d in online_devices]
    outcomes = await asyncio.gather(*tasks)

    for outcome in outcomes:
        device = outcome.pop("device")
        if outcome["ok"]:
            device.last_seen = datetime.now()
        results.append(outcome)
            
    db.commit()
    success_count = sum(1 for r in results if r["ok"])
    return {"message": f"停车指令已下发至 {success_count}/{len(online_devices)} 台设备", "results": results}


class ClusterControlSend(BaseModel):
    command: str

@app.post("/api/clusters/{cluster_id}/send")
async def cluster_control_send(
    cluster_id: int,
    cmd: ClusterControlSend,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """向集群下发特定的 TCP JSON 指令（需登录）"""
    cluster = db.query(Cluster).filter(Cluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="集群不存在")
    
    try:
        payload = json.loads(cmd.command)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"指令必须是合法的 JSON: {exc}") from exc
        
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="指令必须是 JSON 对象")

    msg_type = payload.get("type", "")
    expected = "pong" if msg_type == "ping" else "ack"

    online_devices = [d for d in cluster.devices if d.status == "online"]
    if not online_devices:
        raise HTTPException(status_code=400, detail="集群中没有在线的设备")

    results = []

    async def _send_to_device(device):
        try:
            response = await run_in_threadpool(
                send_robot_control_message,
                device.ip_address, device.port or 9000,
                payload,
                expected
            )
            print(f"[{datetime.now()}] Cluster {cluster_id} Device {device.id} Response: {response}")
            return {"device": device, "device_id": device.id, "ok": True, "response": response}
        except HTTPException as exc:
            return {"device": device, "device_id": device.id, "ok": False, "error": exc.detail}

    tasks = [_send_to_device(d) for d in online_devices]
    outcomes = await asyncio.gather(*tasks)

    for outcome in outcomes:
        device = outcome.pop("device")
        if outcome["ok"]:
            device.last_seen = datetime.now()
        results.append(outcome)
            
    db.commit()
    success_count = sum(1 for r in results if r["ok"])
    return {"message": f"特定指令已下发至 {success_count}/{len(online_devices)} 台设备", "results": results}


# ===== 摄像头视频流代理接口 =====

# 摄像头服务端口（mjpg_streamer 默认 8080）
CAMERA_STREAM_PORT = int(os.getenv("CAMERA_STREAM_PORT", "8080"))


@app.get("/api/devices/{device_id}/camera/stream")
async def proxy_camera_stream(
    device_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    代理转发设备的 MJPEG 摄像头视频流（需登录）

    设备端运行 mjpg_streamer，在 8080 端口提供 MJPEG 流。
    本接口通过后端代理转发，确保前端访问需要经过 JWT 鉴权。

    使用独立的 httpx.AsyncClient 实例避免与其他请求共享连接池，
    从而解决多路视频流并发时阻塞的问题。
    """
    import httpx
    from starlette.responses import StreamingResponse

    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    if not device.ip_address:
        raise HTTPException(status_code=422, detail="设备未配置 IP 地址")

    camera_url = f"http://{device.ip_address}:{CAMERA_STREAM_PORT}/?action=stream"

    async def stream_generator():
        """异步读取 MJPEG 流并逐块转发，每路流独立创建连接"""
        client = None
        try:
            # 每路视频流创建独立的 httpx 客户端，避免连接池竞争
            client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5.0, read=None, write=5.0, pool=None),
                limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
            )
            async with client.stream("GET", camera_url) as response:
                if response.status_code != 200:
                    print(f"[{datetime.now()}] 摄像头流代理: 设备 {device_id} 返回 HTTP {response.status_code}")
                    return
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    yield chunk
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
            print(f"[{datetime.now()}] 摄像头流代理失败 (设备 {device_id}): {exc}")
            return
        except Exception as exc:
            print(f"[{datetime.now()}] 摄像头流代理异常 (设备 {device_id}): {exc}")
            return
        finally:
            if client:
                await client.aclose()

    return StreamingResponse(
        stream_generator(),
        media_type="multipart/x-mixed-replace; boundary=boundarydonotcross",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Content-Type-Options": "nosniff",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/devices/{device_id}/camera/snapshot")
async def proxy_camera_snapshot(
    device_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取设备摄像头的单帧快照（JPEG 图片）（需登录）

    通过后端代理从 mjpg_streamer 的 ?action=snapshot 接口获取。
    用于截图保存等功能。
    """
    import httpx

    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    if not device.ip_address:
        raise HTTPException(status_code=422, detail="设备未配置 IP 地址")

    snapshot_url = f"http://{device.ip_address}:{CAMERA_STREAM_PORT}/?action=snapshot"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=10.0)) as client:
            response = await client.get(snapshot_url)
            if response.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"摄像头快照获取失败 (HTTP {response.status_code})"
                )
            return Response(
                content=response.content,
                media_type="image/jpeg",
                headers={
                    "Content-Disposition": f"attachment; filename=snapshot_{device_id}_{int(time.time())}.jpg",
                    "Cache-Control": "no-cache",
                },
            )
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="无法连接到设备摄像头服务")
    except httpx.ReadTimeout:
        raise HTTPException(status_code=504, detail="摄像头响应超时")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"摄像头快照获取异常: {exc}")


# ===== 巡检系统 Pydantic 模型 =====

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


# ===== 巡检区域 API =====

@app.get("/api/patrol/areas")
async def list_patrol_areas(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取所有巡检区域列表"""
    areas = db.query(PatrolArea).order_by(PatrolArea.id.asc()).all()
    result = []
    for a in areas:
        result.append({
            "id": a.id,
            "name": a.name,
            "description": a.description,
            "manager": a.manager,
            "boundary": a.boundary,
            "center_lng": float(a.center_lng) if a.center_lng else None,
            "center_lat": float(a.center_lat) if a.center_lat else None,
            "area_sqm": a.area_sqm,
            "point_count": len(a.points),
            "route_count": len(a.routes),
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "updated_at": a.updated_at.isoformat() if a.updated_at else None,
        })
    return result


@app.post("/api/patrol/areas")
async def create_patrol_area(
    data: PatrolAreaCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建巡检区域"""
    area = PatrolArea(
        name=data.name,
        description=data.description,
        manager=data.manager,
        boundary=data.boundary,
        center_lng=data.center_lng,
        center_lat=data.center_lat,
        area_sqm=data.area_sqm,
    )
    db.add(area)
    db.commit()
    db.refresh(area)
    return {
        "id": area.id,
        "name": area.name,
        "description": area.description,
        "manager": area.manager,
        "boundary": area.boundary,
        "center_lng": float(area.center_lng) if area.center_lng else None,
        "center_lat": float(area.center_lat) if area.center_lat else None,
        "area_sqm": area.area_sqm,
        "point_count": 0,
        "route_count": 0,
        "created_at": area.created_at.isoformat() if area.created_at else None,
        "updated_at": area.updated_at.isoformat() if area.updated_at else None,
    }


@app.put("/api/patrol/areas/{area_id}")
async def update_patrol_area(
    area_id: int,
    data: PatrolAreaUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新巡检区域"""
    area = db.query(PatrolArea).filter(PatrolArea.id == area_id).first()
    if not area:
        raise HTTPException(status_code=404, detail="巡检区域不存在")
    if data.name is not None:
        area.name = data.name
    if data.description is not None:
        area.description = data.description
    if data.manager is not None:
        area.manager = data.manager
    if data.boundary is not None:
        area.boundary = data.boundary
    if data.center_lng is not None:
        area.center_lng = data.center_lng
    if data.center_lat is not None:
        area.center_lat = data.center_lat
    if data.area_sqm is not None:
        area.area_sqm = data.area_sqm
    db.commit()
    db.refresh(area)
    return {
        "id": area.id,
        "name": area.name,
        "description": area.description,
        "manager": area.manager,
        "boundary": area.boundary,
        "center_lng": float(area.center_lng) if area.center_lng else None,
        "center_lat": float(area.center_lat) if area.center_lat else None,
        "area_sqm": area.area_sqm,
        "point_count": len(area.points),
        "route_count": len(area.routes),
        "created_at": area.created_at.isoformat() if area.created_at else None,
        "updated_at": area.updated_at.isoformat() if area.updated_at else None,
    }


@app.delete("/api/patrol/areas/{area_id}")
async def delete_patrol_area(
    area_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除巡检区域（级联删除点位和线路）"""
    area = db.query(PatrolArea).filter(PatrolArea.id == area_id).first()
    if not area:
        raise HTTPException(status_code=404, detail="巡检区域不存在")
    db.delete(area)
    db.commit()
    return {"message": f"巡检区域 {area.name} 已删除"}


# ===== 巡检点位 API =====

@app.get("/api/patrol/points")
async def list_patrol_points(
    area_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取巡检点位列表（可按区域筛选）"""
    query = db.query(PatrolPoint)
    if area_id is not None:
        query = query.filter(PatrolPoint.area_id == area_id)
    points = query.order_by(PatrolPoint.id.asc()).all()
    return [{
        "id": p.id,
        "area_id": p.area_id,
        "name": p.name,
        "description": p.description,
        "lng": float(p.lng) if p.lng else None,
        "lat": float(p.lat) if p.lat else None,
        "address": p.address,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    } for p in points]


@app.post("/api/patrol/points")
async def create_patrol_point(
    data: PatrolPointCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建巡检点位"""
    area = db.query(PatrolArea).filter(PatrolArea.id == data.area_id).first()
    if not area:
        raise HTTPException(status_code=404, detail="巡检区域不存在")
    point = PatrolPoint(
        area_id=data.area_id,
        name=data.name,
        description=data.description,
        lng=data.lng,
        lat=data.lat,
        address=data.address,
    )
    db.add(point)
    db.commit()
    db.refresh(point)
    return {
        "id": point.id,
        "area_id": point.area_id,
        "name": point.name,
        "description": point.description,
        "lng": float(point.lng) if point.lng else None,
        "lat": float(point.lat) if point.lat else None,
        "address": point.address,
        "created_at": point.created_at.isoformat() if point.created_at else None,
        "updated_at": point.updated_at.isoformat() if point.updated_at else None,
    }


@app.put("/api/patrol/points/{point_id}")
async def update_patrol_point(
    point_id: int,
    data: PatrolPointUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新巡检点位"""
    point = db.query(PatrolPoint).filter(PatrolPoint.id == point_id).first()
    if not point:
        raise HTTPException(status_code=404, detail="巡检点位不存在")
    if data.name is not None:
        point.name = data.name
    if data.description is not None:
        point.description = data.description
    if data.address is not None:
        point.address = data.address
    db.commit()
    db.refresh(point)
    return {
        "id": point.id,
        "area_id": point.area_id,
        "name": point.name,
        "description": point.description,
        "lng": float(point.lng) if point.lng else None,
        "lat": float(point.lat) if point.lat else None,
        "address": point.address,
        "created_at": point.created_at.isoformat() if point.created_at else None,
        "updated_at": point.updated_at.isoformat() if point.updated_at else None,
    }


@app.delete("/api/patrol/points/{point_id}")
async def delete_patrol_point(
    point_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除巡检点位"""
    point = db.query(PatrolPoint).filter(PatrolPoint.id == point_id).first()
    if not point:
        raise HTTPException(status_code=404, detail="巡检点位不存在")
    db.delete(point)
    db.commit()
    return {"message": f"巡检点位 {point.name} 已删除"}


# ===== 巡检线路 API =====

@app.get("/api/patrol/routes")
async def list_patrol_routes(
    area_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取巡检线路列表（可按区域筛选）"""
    query = db.query(PatrolRoute)
    if area_id is not None:
        query = query.filter(PatrolRoute.area_id == area_id)
    routes = query.order_by(PatrolRoute.id.asc()).all()
    result = []
    for r in routes:
        pts = sorted(r.route_points, key=lambda x: x.seq_order)
        result.append({
            "id": r.id,
            "area_id": r.area_id,
            "name": r.name,
            "description": r.description,
            "distance": r.distance,
            "point_count": len(pts),
            "points": [{
                "id": rp.point.id,
                "name": rp.point.name,
                "lng": float(rp.point.lng),
                "lat": float(rp.point.lat),
                "address": rp.point.address,
                "seq_order": rp.seq_order,
            } for rp in pts],
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        })
    return result


@app.get("/api/patrol/routes/{route_id}")
async def get_patrol_route(
    route_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取巡检线路详情（含点位列表）"""
    r = db.query(PatrolRoute).filter(PatrolRoute.id == route_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="巡检线路不存在")
    pts = sorted(r.route_points, key=lambda x: x.seq_order)
    return {
        "id": r.id,
        "area_id": r.area_id,
        "name": r.name,
        "description": r.description,
        "distance": r.distance,
        "points": [{
            "id": rp.point.id,
            "name": rp.point.name,
            "lng": float(rp.point.lng),
            "lat": float(rp.point.lat),
            "address": rp.point.address,
            "seq_order": rp.seq_order,
        } for rp in pts],
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


@app.post("/api/patrol/routes")
async def create_patrol_route(
    data: PatrolRouteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建巡检线路（含点位顺序）"""
    area = db.query(PatrolArea).filter(PatrolArea.id == data.area_id).first()
    if not area:
        raise HTTPException(status_code=404, detail="巡检区域不存在")
    route = PatrolRoute(
        area_id=data.area_id,
        name=data.name,
        description=data.description,
        distance=data.distance,
    )
    db.add(route)
    db.flush()  # 获取 route.id
    for i, pid in enumerate(data.point_ids):
        rp = PatrolRoutePoint(route_id=route.id, point_id=pid, seq_order=i + 1)
        db.add(rp)
    db.commit()
    db.refresh(route)
    pts = sorted(route.route_points, key=lambda x: x.seq_order)
    return {
        "id": route.id,
        "area_id": route.area_id,
        "name": route.name,
        "description": route.description,
        "distance": route.distance,
        "points": [{
            "id": rp.point.id,
            "name": rp.point.name,
            "lng": float(rp.point.lng),
            "lat": float(rp.point.lat),
            "address": rp.point.address,
            "seq_order": rp.seq_order,
        } for rp in pts],
        "created_at": route.created_at.isoformat() if route.created_at else None,
        "updated_at": route.updated_at.isoformat() if route.updated_at else None,
    }


@app.put("/api/patrol/routes/{route_id}")
async def update_patrol_route(
    route_id: int,
    data: PatrolRouteUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新巡检线路"""
    route = db.query(PatrolRoute).filter(PatrolRoute.id == route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail="巡检线路不存在")
    if data.name is not None:
        route.name = data.name
    if data.description is not None:
        route.description = data.description
    if data.distance is not None:
        route.distance = data.distance
    if data.point_ids is not None:
        # 重置点位关联
        db.query(PatrolRoutePoint).filter(PatrolRoutePoint.route_id == route_id).delete()
        for i, pid in enumerate(data.point_ids):
            rp = PatrolRoutePoint(route_id=route.id, point_id=pid, seq_order=i + 1)
            db.add(rp)
    db.commit()
    db.refresh(route)
    pts = sorted(route.route_points, key=lambda x: x.seq_order)
    return {
        "id": route.id,
        "area_id": route.area_id,
        "name": route.name,
        "description": route.description,
        "distance": route.distance,
        "points": [{
            "id": rp.point.id,
            "name": rp.point.name,
            "lng": float(rp.point.lng),
            "lat": float(rp.point.lat),
            "address": rp.point.address,
            "seq_order": rp.seq_order,
        } for rp in pts],
        "created_at": route.created_at.isoformat() if route.created_at else None,
        "updated_at": route.updated_at.isoformat() if route.updated_at else None,
    }


@app.delete("/api/patrol/routes/{route_id}")
async def delete_patrol_route(
    route_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除巡检线路"""
    route = db.query(PatrolRoute).filter(PatrolRoute.id == route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail="巡检线路不存在")
    db.delete(route)
    db.commit()
    return {"message": f"巡检线路 {route.name} 已删除"}


# ===== 巡检任务 API =====

@app.get("/api/patrol/tasks")
async def list_patrol_tasks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取所有巡检任务列表"""
    tasks = db.query(PatrolTask).order_by(PatrolTask.id.desc()).all()
    result = []
    for t in tasks:
        result.append({
            "id": t.id,
            "name": t.name,
            "status": t.status,
            "route_id": t.route_id,
            "route_name": t.route.name if t.route else None,
            "device_id": t.device_id,
            "device_name": t.device.name if t.device else None,
            "gps_track": t.gps_track,
            "started_at": t.started_at.isoformat() if t.started_at else None,
            "ended_at": t.ended_at.isoformat() if t.ended_at else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        })
    return result


@app.get("/api/patrol/tasks/{task_id}")
async def get_patrol_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取巡检任务详情（含GPS轨迹和线路信息）"""
    t = db.query(PatrolTask).filter(PatrolTask.id == task_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="巡检任务不存在")
    route_data = None
    if t.route:
        pts = sorted(t.route.route_points, key=lambda x: x.seq_order)
        route_data = {
            "id": t.route.id,
            "name": t.route.name,
            "area_id": t.route.area_id,
            "distance": t.route.distance,
            "points": [{
                "id": rp.point.id,
                "name": rp.point.name,
                "lng": float(rp.point.lng),
                "lat": float(rp.point.lat),
                "seq_order": rp.seq_order,
            } for rp in pts],
        }
    return {
        "id": t.id,
        "name": t.name,
        "status": t.status,
        "route_id": t.route_id,
        "route": route_data,
        "device_id": t.device_id,
        "device_name": t.device.name if t.device else None,
        "device_ip": t.device.ip_address if t.device else None,
        "device_port": t.device.port if t.device else None,
        "gps_track": t.gps_track or [],
        "started_at": t.started_at.isoformat() if t.started_at else None,
        "ended_at": t.ended_at.isoformat() if t.ended_at else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


@app.post("/api/patrol/tasks")
async def create_patrol_task(
    data: PatrolTaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建巡检任务"""
    route = db.query(PatrolRoute).filter(PatrolRoute.id == data.route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail="巡检线路不存在")
    if data.device_id:
        device = db.query(Device).filter(Device.id == data.device_id).first()
        if not device:
            raise HTTPException(status_code=404, detail="设备不存在")
    task = PatrolTask(
        route_id=data.route_id,
        device_id=data.device_id,
        name=data.name,
        status="pending",
        gps_track=[],
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return {
        "id": task.id,
        "name": task.name,
        "status": task.status,
        "route_id": task.route_id,
        "device_id": task.device_id,
        "gps_track": task.gps_track,
        "started_at": None,
        "ended_at": None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


@app.put("/api/patrol/tasks/{task_id}/start")
async def start_patrol_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """开始巡检任务（开始记录GPS轨迹）"""
    task = db.query(PatrolTask).filter(PatrolTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="巡检任务不存在")
    if task.status == "running":
        raise HTTPException(status_code=400, detail="任务已在运行中")
    if task.status == "completed":
        raise HTTPException(status_code=400, detail="任务已完成，无法重新开始")
    task.status = "running"
    task.started_at = datetime.now()
    task.gps_track = []
    db.commit()
    return {"message": "任务已开始", "status": "running"}


@app.put("/api/patrol/tasks/{task_id}/pause")
async def pause_patrol_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """暂停巡检任务"""
    task = db.query(PatrolTask).filter(PatrolTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="巡检任务不存在")
    if task.status != "running":
        raise HTTPException(status_code=400, detail="只有运行中的任务才能暂停")
    task.status = "paused"
    db.commit()
    return {"message": "任务已暂停", "status": "paused"}


@app.put("/api/patrol/tasks/{task_id}/resume")
async def resume_patrol_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """恢复巡检任务"""
    task = db.query(PatrolTask).filter(PatrolTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="巡检任务不存在")
    if task.status != "paused":
        raise HTTPException(status_code=400, detail="只有暂停中的任务才能恢复")
    task.status = "running"
    db.commit()
    return {"message": "任务已恢复", "status": "running"}


@app.put("/api/patrol/tasks/{task_id}/stop")
async def stop_patrol_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """停止巡检任务（结束GPS记录）"""
    task = db.query(PatrolTask).filter(PatrolTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="巡检任务不存在")
    if task.status in ("completed", "cancelled"):
        raise HTTPException(status_code=400, detail="任务已结束")
    task.status = "completed"
    task.ended_at = datetime.now()
    db.commit()
    return {"message": "任务已停止", "status": "completed"}


@app.put("/api/patrol/tasks/{task_id}/track")
async def append_gps_track(
    task_id: int,
    data: PatrolTrackAppend,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """追加GPS轨迹点（仅running状态可追加）"""
    task = db.query(PatrolTask).filter(PatrolTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="巡检任务不存在")
    if task.status != "running":
        raise HTTPException(status_code=400, detail="只有运行中的任务才能追加GPS轨迹")
    current_track = task.gps_track or []
    current_track.extend(data.points)
    task.gps_track = current_track
    db.commit()
    return {"message": f"已追加 {len(data.points)} 个轨迹点", "total": len(current_track)}


@app.delete("/api/patrol/tasks/{task_id}")
async def delete_patrol_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除巡检任务"""
    task = db.query(PatrolTask).filter(PatrolTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="巡检任务不存在")
    if task.status == "running":
        raise HTTPException(status_code=400, detail="任务运行中，请先停止任务后再删除")
    db.delete(task)
    db.commit()
    return {"message": f"巡检任务 {task.name} 已删除"}
