"""轨迹元数据持久化与管线运行日志（规划 §3.3.3 / §3.5.4）。

- upsert_track_history：把当前活跃轨迹按 (device_id, track_id) 更新/插入
  video_track_history，调用方持有 row_cache（track_id → 行 id）避免每帧查询；
- log_run_event：写入 inference_run_log（start/stop/error/stats）。

两者默认自建数据库会话（供推理工作线程调用）；db 参数用于测试注入。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from database import SessionLocal
from models import InferenceRunLog, VideoTrackHistory


def upsert_track_history(
    device_id: int,
    tracks: list,
    row_cache: dict[int, int],
    db: Any = None,
    frames_delta: int = 1,
) -> None:
    """把 tracks 的元数据写入 video_track_history（存在则更新，否则插入）。"""
    owns_session = db is None
    db = db or SessionLocal()
    now = datetime.now()
    delta = max(1, int(frames_delta))
    try:
        active_ids: set[int] = set()
        for t in tracks:
            active_ids.add(t.track_id)
            row_id = row_cache.get(t.track_id)
            if row_id is None:
                row = VideoTrackHistory(
                    device_id=device_id,
                    track_id=t.track_id,
                    global_track_id=str(t.track_id),
                    class_name=t.class_name,
                    bbox=list(t.bbox),
                    first_seen=now,
                    last_seen=now,
                    frame_count=delta,
                )
                db.add(row)
                db.flush()
                row_cache[t.track_id] = row.id
            else:
                row = db.query(VideoTrackHistory).filter(VideoTrackHistory.id == row_id).first()
                if row is None:
                    row_cache.pop(t.track_id, None)
                    continue
                row.class_name = t.class_name
                row.bbox = list(t.bbox)
                row.last_seen = now
                row.frame_count = (row.frame_count or 0) + delta

        # 已消失的轨迹从缓存移除（其行保留在历史表中供查询）
        for track_id in [k for k in row_cache if k not in active_ids]:
            row_cache.pop(track_id, None)

        if owns_session:
            db.commit()
    except Exception:
        if owns_session:
            db.rollback()
        raise
    finally:
        if owns_session:
            db.close()


def log_run_event(
    device_id: int,
    action: str,
    detail: dict[str, Any] | None = None,
    db: Any = None,
) -> int | None:
    """写入一条推理管线运行日志，返回日志 id。"""
    owns_session = db is None
    db = db or SessionLocal()
    try:
        row = InferenceRunLog(
            device_id=device_id,
            action=action,
            detail=detail,
            occurred_at=datetime.now(),
        )
        db.add(row)
        if owns_session:
            db.commit()
            return row.id
        db.flush()
        return row.id
    except Exception:
        if owns_session:
            db.rollback()
        raise
    finally:
        if owns_session:
            db.close()
