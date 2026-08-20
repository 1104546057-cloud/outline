"""
设备管理路由

提供设备的 CRUD 接口和 WiFi 扫描功能。
"""

import os
import re
import hashlib
import math
import secrets
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import User, Device, DeviceTelemetry, DeviceToken
from schemas import DeviceCreate, DeviceUpdate
from auth import get_current_user
from config import PLATFORM_DEFAULT_GPS_LAT, PLATFORM_DEFAULT_GPS_LNG, PUBLIC_SERVER_URL
from agent_gateway import agent_gateway
from robot_tcp import update_device_online_status

router = APIRouter(prefix="/api", tags=["设备管理"])


def _initial_gps_location() -> tuple[float, float]:
    """在平台默认定位周围随机生成 1-3 米的 WGS-84 坐标。"""
    earth_radius_m = 6378137.0
    distance_m = 1 + secrets.randbelow(2001) / 1000
    bearing = math.radians(secrets.randbelow(360000) / 1000)
    angular_distance = distance_m / earth_radius_m
    lat1 = math.radians(PLATFORM_DEFAULT_GPS_LAT)
    lng1 = math.radians(PLATFORM_DEFAULT_GPS_LNG)

    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular_distance)
        + math.cos(lat1) * math.sin(angular_distance) * math.cos(bearing)
    )
    lng2 = lng1 + math.atan2(
        math.sin(bearing) * math.sin(angular_distance) * math.cos(lat1),
        math.cos(angular_distance) - math.sin(lat1) * math.sin(lat2),
    )
    return round(math.degrees(lat2), 7), round(math.degrees(lng2), 7)


def _build_device_response(dev: Device, db: Session) -> dict:
    """构建设备响应，附带最新遥测扩展信息"""
    agent_connected = agent_gateway.is_control_connected(dev.id) or agent_gateway.is_media_connected(dev.id)
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
        "ip_address": None if dev.ip_address.startswith("agent-") else dev.ip_address,
        "port": dev.port or 9000,
        "status": "online" if agent_connected else (dev.status or "offline"),
        "control_connected": agent_gateway.is_control_connected(dev.id),
        "media_connected": agent_gateway.is_media_connected(dev.id),
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


@router.get("/devices")
async def list_devices(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取所有设备列表，并自动更新在线状态（需登录）"""
    # 根据 last_seen 自动更新在线/离线状态
    update_device_online_status(db)
    devices = db.query(Device).order_by(Device.id.asc()).all()
    return [_build_device_response(dev, db) for dev in devices]


@router.post("/devices")
async def create_device(
    device_data: DeviceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    添加设备（需登录）。

    公网 Agent 模式下平台先创建设备和 Token，再将返回的配置写入车端。
    车端使用该 Token 主动连接本平台，无需平台访问车端 IP。
    """
    requested_ip = (device_data.ip_address or "").strip()
    if requested_ip:
        existing = db.query(Device).filter(Device.ip_address == requested_ip).first()
        if existing:
            raise HTTPException(status_code=400, detail="该IP地址的设备已存在")

    # 验证端口号范围
    port = device_data.port
    if port < 1 or port > 65535:
        raise HTTPException(status_code=422, detail="端口号必须在 1 到 65535 之间")

    # ---- 存入数据库 ----
    initial_lat, initial_lng = _initial_gps_location()
    now = datetime.now()
    new_device = Device(
        name=device_data.name,
        type=device_data.type,
        # 兼容现有非空唯一列；占位值不再参与任何网络路由。
        ip_address=requested_ip or f"agent-{secrets.token_hex(8)}",
        port=port,
        status="offline",
        last_seen=None,
        health=100,
        speed="0 m/s",
        lat=str(initial_lat),
        lng=str(initial_lng),
    )
    db.add(new_device)
    db.flush()

    device_token = secrets.token_hex(32)
    new_token = DeviceToken(
        device_id=new_device.id,
        token=device_token,
        note=f"公网 Agent 预配置，由 {current_user.username} 添加",
        is_active=True,
    )
    db.add(new_token)

    # 在设备首次上报真实 GPS 前，保留一条平台默认定位附近的历史记录。
    initial_telemetry = DeviceTelemetry(
        device_id=new_device.id,
        status="offline",
        lat=initial_lat,
        lng=initial_lng,
        extra_json={
            "gps": {
                "status": "fix",
                "source": "platform_default",
                "is_historical": True,
            }
        },
        reported_at=now,
    )
    db.add(initial_telemetry)
    db.commit()
    db.refresh(new_device)

    response = _build_device_response(new_device, db)
    response.update({
        "token": device_token,
        "token_id": new_token.id,
        "server_address": PUBLIC_SERVER_URL,
    })
    return response


@router.put("/devices/{device_id}")
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


@router.delete("/devices/{device_id}")
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


@router.get("/wifi/scan")
async def scan_wifi(subnet: str = "192.168.31.0/24", current_user: User = Depends(get_current_user)):
    """
    使用 nmap 扫描局域网内的设备 IP（需登录）。
    支持前端传入自定义扫描网段，并提供 ARP 缓存表读取作为备用/降级机制。
    """
    import subprocess
    
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
            import subprocess
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


# ===== 设备 Token 管理接口 =====

@router.get("/devices/{device_id}/tokens")
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


@router.post("/devices/{device_id}/tokens")
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
