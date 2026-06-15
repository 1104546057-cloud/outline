"""
集群管理路由

提供集群 CRUD 接口和集群级别的批量控制指令下发。
"""

import json
import asyncio
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from database import get_db
from models import User, Device, Cluster
from schemas import (
    ClusterCreate, ClusterUpdate, ClusterResponse,
    ClusterAddDevice, ClusterControlSend, RobotControlCmdVel,
)
from auth import get_current_user
from robot_tcp import send_robot_control_message, normalize_control_value
from config import ROBOT_CONTROL_MAX_LINEAR, ROBOT_CONTROL_MAX_ANGULAR

router = APIRouter(prefix="/api/clusters", tags=["集群管理"])


@router.get("", response_model=list[ClusterResponse])
async def list_clusters(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取所有集群列表（需登录）"""
    clusters = db.query(Cluster).order_by(Cluster.id.asc()).all()
    return clusters


@router.post("", response_model=ClusterResponse)
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


@router.put("/{cluster_id}", response_model=ClusterResponse)
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


@router.delete("/{cluster_id}")
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


@router.post("/{cluster_id}/devices")
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


@router.delete("/{cluster_id}/devices/{device_id}")
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


@router.post("/{cluster_id}/cmd_vel")
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


@router.post("/{cluster_id}/stop")
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


@router.post("/{cluster_id}/send")
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
