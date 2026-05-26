"""
异构无人集群管理平台 - 后端服务

基于 FastAPI 框架构建的 RESTful API 后端服务。
提供用户认证、用户管理等接口。
"""

from fastapi import FastAPI, HTTPException, Depends, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from passlib.hash import bcrypt
import os
import jwt
from datetime import datetime, timedelta
from dotenv import load_dotenv
from typing import Optional

from database import get_db
from models import User, Device, Cluster
import random

# 确保加载环境变量
load_dotenv()

# JWT 配置
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dwc-default-secret-key")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))


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
    version="0.2.0",
)

# 配置 CORS 跨域中间件，允许前端开发服务器访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite 默认开发服务器地址
        "http://127.0.0.1:5173",
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
    token: str  # 后续替换为 JWT token
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


class DeviceUpdate(BaseModel):
    """更新设备请求体"""
    name: Optional[str] = None
    type: Optional[str] = None
    ip_address: Optional[str] = None


class DeviceCommand(BaseModel):
    """设备控制指令请求体"""
    command: str
    params: Optional[dict] = None


class DeviceResponse(BaseModel):
    """设备响应体"""
    id: int
    name: str
    type: str
    ip_address: str
    status: str
    battery: int
    health: int
    signal: int
    speed: str
    lat: Optional[str]
    lng: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


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

@app.get("/api/devices", response_model=list[DeviceResponse])
async def list_devices(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取所有设备列表（需登录）"""
    devices = db.query(Device).order_by(Device.id.asc()).all()
    # 模拟实时状态更新 (仅作演示)
    for dev in devices:
        if dev.status == "online":
            dev.battery = max(0, min(100, dev.battery + random.randint(-2, 1)))
            dev.signal = max(0, min(100, dev.signal + random.randint(-5, 5)))
    db.commit()
    return devices


@app.post("/api/devices", response_model=DeviceResponse)
async def create_device(
    device_data: DeviceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """添加设备（需登录）"""
    existing = db.query(Device).filter(Device.ip_address == device_data.ip_address).first()
    if existing:
        raise HTTPException(status_code=400, detail="该IP地址的设备已存在")

    new_device = Device(
        name=device_data.name,
        type=device_data.type,
        ip_address=device_data.ip_address,
        status="online",
        battery=random.randint(60, 100),
        health=100,
        signal=random.randint(70, 100),
        speed="0 km/h",
        lat="39.9042",
        lng="116.4074"
    )
    db.add(new_device)
    db.commit()
    db.refresh(new_device)
    return new_device


@app.put("/api/devices/{device_id}", response_model=DeviceResponse)
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

    db.commit()
    db.refresh(device)
    return device


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
async def scan_wifi(current_user: User = Depends(get_current_user)):
    """扫描局域网内的设备IP (通过 ARP 表获取真实在线IP)"""
    import subprocess
    import re
    
    devices = []
    try:
        # 在 Windows 上运行 arp -a
        result = subprocess.run(['arp', '-a'], capture_output=True, text=True, encoding='cp936', errors='replace')
        output = result.stdout
        
        # 解析 IP 和 MAC (匹配动态 IP)
        pattern = re.compile(r'^\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F:-]{17})\s+', re.MULTILINE)
        matches = pattern.findall(output)
        
        for ip, mac in matches:
            # 过滤掉组播和广播地址
            if ip.startswith('224.') or ip.startswith('239.') or ip.endswith('.255') or ip == '255.255.255.255':
                continue
                
            # 根据 MAC 简单猜测一下设备类型 (模拟逻辑)
            type_str = "未知设备"
            ssid = f"Device_{mac[-5:].replace('-', '').upper()}"
            mac_lower = mac.lower()
            if "04-67" in mac_lower: type_str = "无人机"
            elif "74-4c" in mac_lower: type_str = "无人车"
            else: type_str = "无人船" # 兜底演示
            
            devices.append({
                "ip": ip,
                "mac": mac,
                "ssid": ssid,
                "type": type_str
            })
            
    except Exception as e:
        print(f"扫描出错: {e}")
        
    return devices


@app.post("/api/devices/{device_id}/control")
async def control_device(
    device_id: int,
    command_data: DeviceCommand,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """下发设备控制指令"""
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
        
    if device.status != "online":
        raise HTTPException(status_code=400, detail="设备离线，无法接收指令")

    # 模拟指令下发
    print(f"[Device {device_id} - {device.name}] Received Command: {command_data.command} with params: {command_data.params}")
    
    return {
        "message": "指令下发成功",
        "device_id": device_id,
        "command": command_data.command
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
    """向集群中添加设备"""
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
    """从集群移除设备"""
    cluster = db.query(Cluster).filter(Cluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="集群不存在")
    
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device or device not in cluster.devices:
        raise HTTPException(status_code=404, detail="设备不在该集群中")
    
    cluster.devices.remove(device)
    db.commit()
    return {"message": "设备移除成功"}


@app.post("/api/clusters/{cluster_id}/control")
async def control_cluster(
    cluster_id: int,
    command_data: DeviceCommand,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """向下位机集群下发统一控制指令"""
    cluster = db.query(Cluster).filter(Cluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="集群不存在")
    
    # 筛选出集群中状态为 online 的设备
    online_devices = [d for d in cluster.devices if d.status == "online"]
    
    if not online_devices:
        raise HTTPException(status_code=400, detail="集群中没有在线的设备，无法接收指令")
        
    # 模拟指令下发
    success_count = 0
    for device in online_devices:
        print(f"[Cluster {cluster.name} -> Device {device.id} - {device.name}] Received Command: {command_data.command} with params: {command_data.params}")
        success_count += 1
        
    return {
        "message": f"指令已成功下发至 {success_count} 台设备",
        "cluster_id": cluster_id,
        "command": command_data.command,
        "success_count": success_count
    }
