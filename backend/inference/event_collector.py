"""事件归集：把推理产出的事件写入 analytics_event（明细）+ SecurityAlert（需处置）。

设计原则（见 docs/plans/video-analysis-module-plan.md §3.5）：
- 所有事件统一写入 analytics_event（source='inference'），供研判与回看；
- 仅 high / critical 等级的事件同时写入 SecurityAlert（source_type='video_inference'）；
- 告警事件可选抓取证据截图（裁剪 bbox → data/video_evidence/），写入 media_path；
- 告警写入后通过 notify.publish_video_alert 推送给浏览器 WS 订阅者；
- emit 在推理工作线程中调用，默认自建数据库会话，不依赖请求上下文。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from database import SessionLocal
from models import AnalyticsEvent, SecurityAlert
from inference.base import BehaviorEvent
from inference.notify import publish_video_alert
from inference.utils.decode import decode_jpeg, is_ndarray

# analytics_event 明细的来源标识
SOURCE_TYPE = "inference"
# SecurityAlert 的来源类型（与前端筛选 source_type.startswith('video_') 对齐）
ALERT_SOURCE_TYPE = "video_inference"
ALERT_SEVERITIES = {"high", "critical"}

# 证据截图目录（repo 根 /data/video_evidence，与 camera_snapshots 并列）
EVIDENCE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "video_evidence"
BASE_DIR = EVIDENCE_DIR.parent.parent
_EVIDENCE_MARGIN = 20  # 裁剪框外扩像素


def build_event_type(event: BehaviorEvent) -> str:
    """把行为事件类型映射为 analytics_event.event_type（加 video_ 前缀）。"""
    return f"video_{event.event_type}"


def capture_evidence(frame: Any, event: BehaviorEvent, device_id: int) -> str | None:
    """裁剪目标区域保存为 JPEG，返回相对 repo 根目录的路径；失败返回 None。"""
    if not is_ndarray(frame):
        frame = decode_jpeg(frame)
    if not is_ndarray(frame):
        return None
    try:
        import cv2
    except Exception:  # noqa: BLE001 - 未安装 cv2 时跳过截图
        return None

    height, width = frame.shape[:2]
    x1, y1, x2, y2 = (int(round(v)) for v in event.bbox)
    x1 = max(0, x1 - _EVIDENCE_MARGIN)
    y1 = max(0, y1 - _EVIDENCE_MARGIN)
    x2 = min(width, x2 + _EVIDENCE_MARGIN)
    y2 = min(height, y2 + _EVIDENCE_MARGIN)
    if x2 <= x1 or y2 <= y1:
        return None

    crop = frame[y1:y2, x1:x2]
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{device_id}_{event.event_type}_{timestamp}.jpg"
    filepath = EVIDENCE_DIR / filename
    if not cv2.imwrite(str(filepath), crop):
        return None
    # 统一为 URL 风格的前向斜杠路径
    return filepath.relative_to(BASE_DIR).as_posix()


def emit(event: BehaviorEvent, device_id: int, db: Any = None, frame: Any = None) -> int:
    """写入事件明细（并视等级写入告警 + 截图 + 推送），返回 analytics_event.id。

    db 参数用于测试注入；为 None 时自建会话并在结束时提交/关闭。
    frame 为已解码图像（用于抓取证据截图），可为 None。
    """
    event_type = build_event_type(event)
    occurred_at = event.occurred_at or datetime.now()
    owns_session = db is None
    db = db or SessionLocal()
    try:
        analytics_event = AnalyticsEvent(
            event_type=event_type,
            source=SOURCE_TYPE,
            device_id=device_id,
            occurred_at=occurred_at,
            payload=event.to_payload(device_id),
        )
        db.add(analytics_event)
        db.flush()

        if event.severity in ALERT_SEVERITIES:
            media_path = capture_evidence(frame, event, device_id) if frame is not None else None
            alert = SecurityAlert(
                alert_type=event_type,
                severity=event.severity,
                title=f"视频识别告警：{event.event_type}",
                description=event.description,
                device_id=device_id,
                source_type=ALERT_SOURCE_TYPE,
                source_id=str(analytics_event.id),
                media_path=media_path,
                occurred_at=occurred_at,
            )
            db.add(alert)
            db.flush()

        if owns_session:
            db.commit()

        if event.severity in ALERT_SEVERITIES:
            # 提交后广播（alert.id 已可用）
            publish_video_alert(
                {
                    "type": "video_alert",
                    "payload": {
                        "id": alert.id,
                        "alert_type": alert.alert_type,
                        "severity": alert.severity,
                        "title": alert.title,
                        "description": alert.description,
                        "device_id": device_id,
                        "media_path": alert.media_path,
                        "occurred_at": occurred_at.isoformat(),
                    },
                }
            )
        return analytics_event.id
    except Exception:
        if owns_session:
            db.rollback()
        raise
    finally:
        if owns_session:
            db.close()
