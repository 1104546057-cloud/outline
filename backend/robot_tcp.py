"""Robot control helpers backed by outbound vehicle-agent WebSockets."""

from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from agent_gateway import agent_gateway
from config import DEVICE_ONLINE_TIMEOUT_SECONDS, ROBOT_CONTROL_TIMEOUT_SECONDS
from models import Device


async def send_robot_control_message(
    device_id: int,
    payload: dict[str, Any],
    expected_type: str,
) -> dict[str, Any]:
    """Send one correlated command to the connected agent and validate its response."""
    response = await agent_gateway.send_command(
        device_id=device_id,
        command=payload,
        timeout=ROBOT_CONTROL_TIMEOUT_SECONDS,
    )
    if response.get("type") != expected_type:
        raise HTTPException(status_code=502, detail="无人车返回了非预期响应")
    return response


def normalize_control_value(value: Any, limit: float, field: str) -> float:
    """Clamp a numeric robot-control value to the configured safety limit."""
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{field} 必须是数字。") from exc
    return max(-limit, min(limit, parsed))


def require_device(device_id: int, db: Session) -> Device:
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    return device


def update_device_online_status(db: Session) -> None:
    """Mark telemetry-stale devices offline unless their control agent is connected."""
    cutoff = datetime.now() - timedelta(seconds=DEVICE_ONLINE_TIMEOUT_SECONDS)
    stale_devices = db.query(Device).filter(
        Device.status == "online",
        (Device.last_seen == None) | (Device.last_seen < cutoff),
    ).all()
    for device in stale_devices:
        if not agent_gateway.is_control_connected(device.id) and not agent_gateway.is_media_connected(device.id):
            device.status = "offline"
    db.commit()
