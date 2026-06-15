"""
设备管理路由

提供设备的 CRUD 接口和 WiFi 扫描功能。
"""

import os
import re
import hashlib
import secrets
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from database import get_db
from models import User, Device, DeviceTelemetry, DeviceToken
from schemas import DeviceCreate, DeviceUpdate
from auth import get_current_user
from robot_tcp import register_device_tcp, update_device_online_status

router = APIRouter(prefix="/api", tags=["设备管理"])


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
            register_device_tcp,
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
