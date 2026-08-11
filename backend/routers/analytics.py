"""数据统计研判 · 查询与采集路由（普通用户与外部接入）。

权限约定：
- 查询类接口：登录用户均可访问（viewer 即可）
- 采集类接口：外部 Agent 用设备 Token，手动录入用登录用户
- 管理/配置类接口：见 analytics_admin.py（需 analyst 或 admin）
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session

from auth import get_current_user, get_user_role
from database import get_db
from models import (
    User, Device, DeviceToken,
    AnalyticsIndicator, AnalyticsEvent, AnalyticsMetricDaily,
    AnalyticsNotification,
)
from schemas import AnalyticsEventIngest, AnalyticsEventManual
from analytics.engine import compute_indicator


router = APIRouter(prefix="/api/analytics", tags=["数据统计研判"])


# ===== 仪表盘与查询 =====

@router.get("/overview")
async def analytics_overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """仪表盘总览：返回所有启用指标的最近一次聚合值 + 设备/告警基础计数。"""
    indicators = db.query(AnalyticsIndicator).filter(
        AnalyticsIndicator.is_active == True  # noqa: E712
    ).order_by(AnalyticsIndicator.category, AnalyticsIndicator.id).all()

    items = []
    for ind in indicators:
        latest = db.query(AnalyticsMetricDaily).filter(
            AnalyticsMetricDaily.indicator_id == ind.id,
            AnalyticsMetricDaily.dimension_key == "all",
        ).order_by(AnalyticsMetricDaily.date.desc()).first()

        items.append({
            "code": ind.code,
            "name": ind.name,
            "category": ind.category,
            "unit": ind.unit,
            "value": float(latest.value) if latest and latest.value is not None else None,
            "date": latest.date.isoformat() if latest else None,
            "updated_at": latest.updated_at.isoformat() if latest else None,
        })

    device_total = db.query(Device).count()
    device_online = db.query(Device).filter(Device.status == "online").count()
    return {
        "indicators": items,
        "device_total": device_total,
        "device_online": device_online,
    }


@router.get("/indicators")
async def list_indicators(
    category: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """指标字典列表。"""
    query = db.query(AnalyticsIndicator)
    if category:
        query = query.filter(AnalyticsIndicator.category == category)
    rows = query.order_by(AnalyticsIndicator.id).all()
    return [
        {
            "id": r.id,
            "code": r.code,
            "name": r.name,
            "category": r.category,
            "data_source": r.data_source,
            "unit": r.unit,
            "granularity": r.granularity,
            "description": r.description,
            "is_active": r.is_active,
            "expression": r.expression,
        }
        for r in rows
    ]


@router.get("/indicators/{code}")
async def get_indicator_series(
    code: str,
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """单指标时序：返回最近 N 天的聚合序列，按日期升序。"""
    indicator = db.query(AnalyticsIndicator).filter(AnalyticsIndicator.code == code).first()
    if not indicator:
        raise HTTPException(status_code=404, detail="指标不存在")

    rows = db.query(AnalyticsMetricDaily).filter(
        AnalyticsMetricDaily.indicator_id == indicator.id,
        AnalyticsMetricDaily.dimension_key == "all",
    ).order_by(AnalyticsMetricDaily.date.desc()).limit(days).all()

    return {
        "code": code,
        "name": indicator.name,
        "unit": indicator.unit,
        "series": [
            {
                "date": r.date.isoformat(),
                "value": float(r.value) if r.value is not None else None,
                "sample_count": r.sample_count,
            }
            for r in reversed(rows)
        ],
    }


@router.get("/trend")
async def trend_compare(
    codes: str = Query(..., description="逗号分隔的指标 code"),
    days: int = Query(14, ge=1, le=180),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """多指标趋势对比：返回每个指标最近 N 天的序列。"""
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    if not code_list:
        raise HTTPException(status_code=422, detail="codes 不能为空")

    result = []
    for code in code_list:
        ind = db.query(AnalyticsIndicator).filter(AnalyticsIndicator.code == code).first()
        if not ind:
            continue
        rows = db.query(AnalyticsMetricDaily).filter(
            AnalyticsMetricDaily.indicator_id == ind.id,
            AnalyticsMetricDaily.dimension_key == "all",
        ).order_by(AnalyticsMetricDaily.date.desc()).limit(days).all()
        result.append({
            "code": code,
            "name": ind.name,
            "unit": ind.unit,
            "series": [
                {"date": r.date.isoformat(), "value": float(r.value) if r.value is not None else None}
                for r in reversed(rows)
            ],
        })
    return result


# ===== 数据采集 =====

@router.post("/ingest")
async def ingest_event(
    payload: AnalyticsEventIngest,
    request: Request,
    db: Session = Depends(get_db),
):
    """外部 Agent / 系统接入事件，使用 X-Device-Token 鉴权。"""
    token = request.headers.get("X-Device-Token")
    if not token:
        raise HTTPException(status_code=401, detail="缺少设备 Token")
    device_token = db.query(DeviceToken).filter(
        DeviceToken.token == token, DeviceToken.is_active == True  # noqa: E712
    ).first()
    if not device_token:
        raise HTTPException(status_code=401, detail="设备 Token 无效")

    event = AnalyticsEvent(
        event_type=payload.event_type,
        source=payload.source,
        device_id=payload.device_id or device_token.device_id,
        occurred_at=payload.occurred_at or datetime.now(),
        payload=payload.payload,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return {"ok": True, "id": event.id}


@router.post("/manual")
async def manual_event(
    payload: AnalyticsEventManual,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """前端手动录入事件。"""
    event = AnalyticsEvent(
        event_type=payload.event_type,
        source="manual",
        device_id=payload.device_id,
        occurred_at=payload.occurred_at or datetime.now(),
        payload=payload.payload,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return {"ok": True, "id": event.id}


@router.post("/compute/{code}")
async def compute_indicator_now(
    code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """即时计算指标当前值（不走日聚合缓存），调试用。"""
    ind = db.query(AnalyticsIndicator).filter(AnalyticsIndicator.code == code).first()
    if not ind:
        raise HTTPException(status_code=404, detail="指标不存在")
    if not ind.expression:
        raise HTTPException(status_code=422, detail="指标未配置表达式")
    try:
        value = compute_indicator(db, ind.expression)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算失败: {e}")
    return {"code": code, "value": value, "unit": ind.unit}


# ===== 站内通知 =====

@router.get("/notifications")
async def list_notifications(
    unread_only: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """当前用户的站内通知。"""
    query = db.query(AnalyticsNotification).filter(
        AnalyticsNotification.user_id == current_user.id
    )
    if unread_only:
        query = query.filter(AnalyticsNotification.is_read == False)  # noqa: E712
    rows = query.order_by(AnalyticsNotification.created_at.desc()).limit(100).all()
    return [
        {
            "id": r.id,
            "title": r.title,
            "content": r.content,
            "category": r.category,
            "ref_type": r.ref_type,
            "ref_id": r.ref_id,
            "is_read": r.is_read,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.put("/notifications/{nid}/read")
async def mark_notification_read(
    nid: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    n = db.query(AnalyticsNotification).filter(
        AnalyticsNotification.id == nid,
        AnalyticsNotification.user_id == current_user.id,
    ).first()
    if not n:
        raise HTTPException(status_code=404, detail="通知不存在")
    n.is_read = True
    db.commit()
    return {"ok": True}
