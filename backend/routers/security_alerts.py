"""安全预警处置路由。"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Device, SecurityAlert, User
from schemas import SecurityAlertAssign, SecurityAlertClose, SecurityAlertCreate


router = APIRouter(prefix="/api/security-alerts", tags=["安全预警处置"])


def _serialize_alert(alert: SecurityAlert) -> dict:
    return {
        "id": alert.id,
        "alert_type": alert.alert_type,
        "severity": alert.severity,
        "title": alert.title,
        "description": alert.description,
        "device_id": alert.device_id,
        "device_name": alert.device.name if alert.device else None,
        "source_type": alert.source_type,
        "source_id": alert.source_id,
        "media_path": alert.media_path,
        "occurred_at": alert.occurred_at.isoformat() if alert.occurred_at else None,
        "status": alert.status,
        "assignee": alert.assignee,
        "handling_note": alert.handling_note,
        "acknowledged_at": alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
        "closed_at": alert.closed_at.isoformat() if alert.closed_at else None,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
        "updated_at": alert.updated_at.isoformat() if alert.updated_at else None,
    }


def _get_alert(alert_id: int, db: Session) -> SecurityAlert:
    alert = db.query(SecurityAlert).filter(SecurityAlert.id == alert_id).first()
    if alert is None:
        raise HTTPException(status_code=404, detail="告警不存在")
    return alert


@router.get("")
async def list_security_alerts(
    severity: str | None = Query(None),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(SecurityAlert).order_by(SecurityAlert.occurred_at.desc(), SecurityAlert.id.desc())
    if severity:
        query = query.filter(SecurityAlert.severity == severity)
    if status:
        query = query.filter(SecurityAlert.status == status)
    return [_serialize_alert(alert) for alert in query.all()]


@router.post("")
async def create_security_alert(
    payload: SecurityAlertCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if payload.device_id is not None and not db.query(Device.id).filter(Device.id == payload.device_id).first():
        raise HTTPException(status_code=404, detail="来源设备不存在")

    alert = SecurityAlert(
        alert_type=payload.alert_type,
        severity=payload.severity,
        title=payload.title,
        description=payload.description,
        device_id=payload.device_id,
        source_type=payload.source_type,
        source_id=payload.source_id,
        media_path=payload.media_path,
        occurred_at=payload.occurred_at or datetime.now(),
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return _serialize_alert(alert)


@router.put("/{alert_id}/acknowledge")
async def acknowledge_security_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    alert = _get_alert(alert_id, db)
    if alert.status == "closed":
        raise HTTPException(status_code=400, detail="已关闭的告警不能再次确认")
    alert.status = "acknowledged"
    alert.acknowledged_at = alert.acknowledged_at or datetime.now()
    alert.assignee = alert.assignee or current_user.nickname or current_user.username
    db.commit()
    db.refresh(alert)
    return _serialize_alert(alert)


@router.put("/{alert_id}/assign")
async def assign_security_alert(
    alert_id: int,
    payload: SecurityAlertAssign,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assignee = payload.assignee.strip()
    if not assignee:
        raise HTTPException(status_code=422, detail="处理人不能为空")
    alert = _get_alert(alert_id, db)
    if alert.status == "closed":
        raise HTTPException(status_code=400, detail="已关闭的告警不能重新指派")
    alert.assignee = assignee
    if alert.status == "pending":
        alert.status = "acknowledged"
        alert.acknowledged_at = datetime.now()
    db.commit()
    db.refresh(alert)
    return _serialize_alert(alert)


@router.put("/{alert_id}/close")
async def close_security_alert(
    alert_id: int,
    payload: SecurityAlertClose,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    alert = _get_alert(alert_id, db)
    alert.status = "closed"
    alert.closed_at = datetime.now()
    alert.assignee = alert.assignee or current_user.nickname or current_user.username
    alert.handling_note = payload.handling_note.strip() if payload.handling_note else None
    db.commit()
    db.refresh(alert)
    return _serialize_alert(alert)
