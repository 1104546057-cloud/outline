"""
IoT 遥测路由

提供设备遥测数据上报接口和遥测记录查询接口。
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.orm import Session

from database import get_db
from models import User, Device, DeviceTelemetry, DeviceToken, PatrolTask
from auth import get_current_user

router = APIRouter(prefix="/api", tags=["IoT 遥测"])


@router.post("/iot/telemetry")
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

    # ===== 自动追加 GPS 轨迹到正在运行的巡检任务 =====
    # 当设备上报了有效 GPS 坐标时，检查该设备是否有 running 状态的巡检任务
    # 如果有，则自动将 GPS 坐标追加到任务的 gps_track 中
    report_lat = payload.get("lat")
    report_lng = payload.get("lng")
    if report_lat is not None and report_lng is not None:
        running_tasks = db.query(PatrolTask).filter(
            PatrolTask.device_id == device.id,
            PatrolTask.status == "running",
        ).all()
        for task in running_tasks:
            current_track = list(task.gps_track or [])  # 必须用 list() 创建新列表，否则 SQLAlchemy 检测不到 JSON 字段的原地修改
            current_track.append({
                "lng": float(report_lng),
                "lat": float(report_lat),
                "ts": reported_at.isoformat(),
            })
            task.gps_track = current_track

    db.commit()

    return {"ok": True, "deviceId": device.id, "receivedAt": now.isoformat()}


@router.get("/devices/{device_id}/telemetry")
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
