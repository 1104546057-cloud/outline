"""视频识别分析 · 推理管线管理 API。

权限约定：
- 管理操作（start/stop/config/reload）需 analyst 或 admin 角色；
- 查询操作（状态/配置/事件）登录用户均可访问。

规划见 docs/plans/video-analysis-module-plan.md §5。
"""

from __future__ import annotations

import asyncio
import queue

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from auth import get_current_user, require_role
from database import get_db
from inference.config import inference_config
from inference.event_collector import SOURCE_TYPE
from inference.manager import inference_manager
from models import AnalyticsEvent, Device, InferenceRunLog, User, VideoTrackHistory

router = APIRouter(prefix="/api/inference", tags=["视频识别分析"])

_MJPEG_BOUNDARY = b"--boundarydonotcross"


def _mjpeg_chunk(jpeg: bytes) -> bytes:
    return (
        _MJPEG_BOUNDARY
        + b"\r\nContent-Type: image/jpeg\r\n"
        + f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii")
        + jpeg
        + b"\r\n"
    )


def _ensure_device_exists(device_id: int, db: Session) -> Device:
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    return device


# ===== 管线启停 =====

@router.post("/pipelines/{device_id}/start")
async def start_pipeline(
    device_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("analyst", "admin")),
):
    """启动某设备的推理管线（需 analyst/admin）。"""
    _ensure_device_exists(device_id, db)
    return await inference_manager.start(device_id)


@router.post("/pipelines/{device_id}/stop")
async def stop_pipeline(
    device_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("analyst", "admin")),
):
    """停止某设备的推理管线（需 analyst/admin）。"""
    _ensure_device_exists(device_id, db)
    return await inference_manager.stop(device_id)


# ===== 状态查询 =====

@router.get("/pipelines")
async def list_pipelines(current_user: User = Depends(get_current_user)):
    """列出所有正在运行的管线状态。"""
    return {"pipelines": inference_manager.status_all()}


@router.get("/pipelines/{device_id}/status")
async def pipeline_status(
    device_id: int,
    current_user: User = Depends(get_current_user),
):
    """单设备推理状态（fps、延迟、处理帧数、最近错误）。"""
    return inference_manager.get_status(device_id)


@router.get("/{device_id}/tracks")
async def current_tracks(
    device_id: int,
    current_user: User = Depends(get_current_user),
):
    """当前活跃追踪目标列表（最近一帧的 track）。"""
    bus = inference_manager.get_bus(device_id)
    if bus is None or not bus.is_running():
        raise HTTPException(status_code=409, detail="该设备的推理管线未在运行")
    return {"device_id": device_id, "tracks": bus.latest_tracks()}


@router.get("/{device_id}/track-history")
async def track_history(
    device_id: int,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """设备最近的追踪轨迹元数据（video_track_history）。"""
    rows = (
        db.query(VideoTrackHistory)
        .filter(VideoTrackHistory.device_id == device_id)
        .order_by(VideoTrackHistory.last_seen.desc(), VideoTrackHistory.id.desc())
        .limit(limit)
        .all()
    )
    return {
        "device_id": device_id,
        "items": [
            {
                "id": r.id,
                "track_id": r.track_id,
                "global_track_id": r.global_track_id,
                "class_name": r.class_name,
                "bbox": r.bbox,
                "first_seen": r.first_seen.isoformat() if r.first_seen else None,
                "last_seen": r.last_seen.isoformat() if r.last_seen else None,
                "frame_count": r.frame_count,
            }
            for r in rows
        ],
    }


@router.get("/{device_id}/run-logs")
async def run_logs(
    device_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """设备推理管线运行日志（inference_run_log，start/stop/error/stats）。"""
    query = db.query(InferenceRunLog).filter(InferenceRunLog.device_id == device_id)
    total = query.count()
    rows = (
        query.order_by(InferenceRunLog.occurred_at.desc(), InferenceRunLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": r.id,
                "action": r.action,
                "detail": r.detail,
                "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
            }
            for r in rows
        ],
    }


@router.get("/{device_id}/annotated-stream")
async def annotated_stream(
    device_id: int,
    current_user: User = Depends(get_current_user),
):
    """标注 MJPEG 流：叠加检测/追踪框的画面（需管线 annotate=true 且在运行）。"""
    bus = inference_manager.get_bus(device_id)
    if bus is None or not bus.is_running():
        raise HTTPException(status_code=409, detail="该设备的推理管线未在运行")
    annotated_queue = bus.annotated_queue
    if annotated_queue is None:
        raise HTTPException(status_code=409, detail="该设备管线未启用标注输出")

    async def stream_generator():
        while True:
            try:
                jpeg = await asyncio.to_thread(annotated_queue.get, timeout=15)
            except queue.Empty:
                if not bus.is_running():
                    return
                continue
            yield _mjpeg_chunk(jpeg)

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


# ===== 配置 =====

@router.get("/config")
async def get_config(current_user: User = Depends(get_current_user)):
    """返回当前推理配置。"""
    return inference_config.snapshot()


@router.put("/config")
async def update_config(
    payload: dict,
    current_user: User = Depends(require_role("analyst", "admin")),
):
    """整体更新推理配置并热加载（持久化到 YAML 文件）。"""
    try:
        return inference_config.update(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/reload")
async def reload_config(current_user: User = Depends(require_role("analyst", "admin"))):
    """从磁盘重新加载配置文件（热更新，无需重启）。"""
    return inference_config.reload()


# ===== 事件查询 =====

@router.get("/events")
async def list_events(
    device_id: int | None = Query(None),
    event_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询视频推理事件（分页，可按设备/类型筛选）。"""
    query = db.query(AnalyticsEvent).filter(AnalyticsEvent.source == SOURCE_TYPE)
    if device_id is not None:
        query = query.filter(AnalyticsEvent.device_id == device_id)
    if event_type:
        query = query.filter(AnalyticsEvent.event_type == event_type)

    total = query.count()
    rows = (
        query.order_by(AnalyticsEvent.occurred_at.desc(), AnalyticsEvent.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": r.id,
                "event_type": r.event_type,
                "device_id": r.device_id,
                "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
                "payload": r.payload,
            }
            for r in rows
        ],
    }
