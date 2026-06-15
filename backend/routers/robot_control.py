"""
机器人 TCP 控制路由

提供无人车运动控制（cmd_vel / stop / send / ping）和配置查询接口。
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from database import get_db
from models import User, Device
from schemas import RobotControlCmdVel, RobotControlStop, RobotControlSend
from auth import get_current_user
from robot_tcp import (
    send_robot_control_message,
    normalize_control_value,
    resolve_device_target,
)
from config import ROBOT_CONTROL_MAX_LINEAR, ROBOT_CONTROL_MAX_ANGULAR

import json

router = APIRouter(prefix="/api/robot-control", tags=["机器人控制"])


@router.get("/status")
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


@router.post("/cmd_vel")
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


@router.post("/stop")
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


@router.post("/send")
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


@router.get("/config")
async def robot_control_config(
    current_user: User = Depends(get_current_user),
):
    """返回控制参数配置，供前端使用（需登录）"""
    return {
        "maxLinear": ROBOT_CONTROL_MAX_LINEAR,
        "maxAngular": ROBOT_CONTROL_MAX_ANGULAR,
    }
