"""巡航成果媒体浏览接口。"""

import json
import mimetypes
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from starlette.responses import StreamingResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import PatrolTask, User


router = APIRouter(prefix="/api/patrol-results", tags=["巡航成果"])

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".avi", ".mkv"}
AI_ANALYSIS_DIR = DATA_DIR / "ai_analysis"
TIMESTAMP_PATTERN = re.compile(r"(?P<date>\d{8})_(?P<time>\d{6})(?:$|[_-])")


def _media_type(path: Path) -> Literal["image", "video"] | None:
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    return None


def _captured_at(path: Path) -> datetime:
    match = TIMESTAMP_PATTERN.search(path.stem)
    if match:
        try:
            return datetime.strptime(
                f"{match.group('date')}{match.group('time')}",
                "%Y%m%d%H%M%S",
            )
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime)


def _device_name(path: Path) -> str:
    match = TIMESTAMP_PATTERN.search(path.stem)
    if not match:
        return path.stem
    return path.stem[:match.start()].rstrip("_-") or path.stem


def _parse_datetime(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value)
        except (OSError, OverflowError, ValueError):
            return fallback
    if isinstance(value, str) and value.strip():
        normalized = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
            return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
        except ValueError:
            pass
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y%m%d_%H%M%S"):
            try:
                return datetime.strptime(normalized, pattern)
            except ValueError:
                continue
    return fallback


def _safe_preview_path(value: Any, result_file: Path) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    data_root = DATA_DIR.resolve()
    candidates = [DATA_DIR / value, result_file.parent / value]
    for candidate in candidates:
        resolved = candidate.resolve()
        try:
            resolved.relative_to(data_root)
        except ValueError:
            continue
        if resolved.is_file() and _media_type(resolved) == "image":
            return resolved.relative_to(data_root).as_posix()
    return None


def _normalize_labels(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return []
    labels = []
    for item in value:
        if isinstance(item, str):
            labels.append(item)
        elif isinstance(item, dict):
            label = item.get("label") or item.get("name") or item.get("class")
            if label:
                labels.append(str(label))
    return labels[:12]


def _load_ai_results() -> list[dict]:
    AI_ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for path in AI_ANALYSIS_DIR.rglob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue

        if isinstance(payload, list):
            records = payload
        elif isinstance(payload, dict) and isinstance(payload.get("results"), list):
            records = payload["results"]
        else:
            records = [payload]

        fallback_time = datetime.fromtimestamp(path.stat().st_mtime)
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                continue
            captured_at = _parse_datetime(
                record.get("captured_at") or record.get("timestamp") or record.get("created_at"),
                fallback_time,
            )
            title = str(record.get("title") or record.get("name") or record.get("event_type") or "AI分析结果")
            summary = str(record.get("summary") or record.get("description") or record.get("message") or "AI 分析结果")
            device_name = str(record.get("device_name") or record.get("device") or "未知设备")
            confidence = record.get("confidence")
            try:
                confidence = float(confidence) if confidence is not None else None
            except (TypeError, ValueError):
                confidence = None
            if confidence is not None and confidence <= 1:
                confidence *= 100

            relative_file = path.relative_to(DATA_DIR).as_posix()
            source_directory = path.parent.relative_to(DATA_DIR).as_posix()
            items.append({
                "id": f"ai:{relative_file}:{index}",
                "name": title,
                "type": "ai",
                "device_name": device_name,
                "source": source_directory,
                "captured_at": captured_at.isoformat(),
                "summary": summary,
                "severity": str(record.get("severity") or record.get("level") or "普通"),
                "confidence": round(confidence, 1) if confidence is not None else None,
                "labels": _normalize_labels(record.get("labels") or record.get("detections") or record.get("categories")),
                "preview_path": _safe_preview_path(
                    record.get("preview_path") or record.get("image") or record.get("image_path"),
                    path,
                ),
            })
    return items


def _load_track_results(db: Session) -> list[dict]:
    items = []
    tasks = db.query(PatrolTask).order_by(PatrolTask.id.desc()).all()
    for task in tasks:
        points = [
            point for point in (task.gps_track or [])
            if isinstance(point, dict) and point.get("lng") is not None and point.get("lat") is not None
        ]
        if not points:
            continue
        captured_at = task.ended_at or task.started_at or task.updated_at or task.created_at or datetime.now()
        items.append({
            "id": f"track:{task.id}",
            "name": task.name,
            "type": "track",
            "device_name": task.device.name if task.device else "未绑定设备",
            "source": task.route.name if task.route else "未绑定线路",
            "captured_at": captured_at.isoformat(),
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "ended_at": task.ended_at.isoformat() if task.ended_at else None,
            "status": task.status,
            "point_count": len(points),
            "gps_track": points,
            "task_id": task.id,
        })
    return items


def _resolve_media_path(relative_path: str) -> Path:
    data_root = DATA_DIR.resolve()
    candidate = (data_root / relative_path).resolve()
    try:
        candidate.relative_to(data_root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="媒体文件不存在") from exc

    if not candidate.is_file() or _media_type(candidate) is None:
        raise HTTPException(status_code=404, detail="媒体文件不存在")
    return candidate


def _parse_byte_range(range_header: str, file_size: int) -> tuple[int, int]:
    """解析单段 HTTP Range，返回包含首尾字节的位置。"""
    if not range_header.startswith("bytes=") or "," in range_header:
        raise ValueError("不支持的 Range 请求")
    range_value = range_header.removeprefix("bytes=").strip()
    start_text, separator, end_text = range_value.partition("-")
    if not separator:
        raise ValueError("无效的 Range 请求")

    if start_text:
        start = int(start_text)
        end = int(end_text) if end_text else file_size - 1
    else:
        suffix_length = int(end_text)
        if suffix_length <= 0:
            raise ValueError("无效的 Range 请求")
        start = max(file_size - suffix_length, 0)
        end = file_size - 1

    if start < 0 or start >= file_size or end < start:
        raise ValueError("Range 超出文件范围")
    return start, min(end, file_size - 1)


def _iter_file_range(path: Path, start: int, end: int, chunk_size: int = 1024 * 1024):
    """按指定字节范围分块读取文件，避免将整个视频载入内存。"""
    remaining = end - start + 1
    with path.open("rb") as file:
        file.seek(start)
        while remaining > 0:
            chunk = file.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get("")
async def list_patrol_results(
    query: str = Query(default="", max_length=100),
    result_type: Literal["all", "image", "video", "track", "ai"] = "all",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """聚合 data 媒体、巡检任务轨迹和 AI 分析结果。"""
    del current_user
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    normalized_query = query.strip().casefold()
    items = []
    counts = {"image": 0, "video": 0, "track": 0, "ai": 0}

    for path in DATA_DIR.rglob("*"):
        if not path.is_file():
            continue
        item_type = _media_type(path)
        if item_type is None:
            continue

        relative_path = path.relative_to(DATA_DIR).as_posix()
        relative_parts = Path(relative_path).parts
        if relative_path.startswith("ai_analysis/") or any(part.startswith(".") for part in relative_parts):
            continue
        device_name = _device_name(path)
        captured_at = _captured_at(path)
        items.append({
            "id": f"media:{relative_path}",
            "name": path.name,
            "relative_path": relative_path,
            "type": item_type,
            "device_name": device_name,
            "source": path.parent.relative_to(DATA_DIR).as_posix(),
            "size": path.stat().st_size,
            "captured_at": captured_at.isoformat(),
        })

    items.extend(_load_track_results(db))
    items.extend(_load_ai_results())

    for item in items:
        counts[item["type"]] += 1

    if normalized_query:
        items = [
            item for item in items
            if normalized_query in " ".join([
                str(item.get("name", "")),
                str(item.get("device_name", "")),
                str(item.get("source", "")),
                str(item.get("summary", "")),
                " ".join(item.get("labels", [])),
            ]).casefold()
        ]
    if result_type != "all":
        items = [item for item in items if item["type"] == result_type]

    items.sort(key=lambda item: item["captured_at"], reverse=True)
    return {
        "items": items,
        "total": len(items),
        "counts": {
            "all": sum(counts.values()),
            **counts,
        },
    }


@router.get("/media/{relative_path:path}")
async def get_patrol_result_media(
    relative_path: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """以内联方式返回 data 目录中的图片或视频文件。"""
    del current_user
    path = _resolve_media_path(relative_path)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if _media_type(path) != "video":
        return FileResponse(path, media_type=media_type)

    file_size = path.stat().st_size
    range_header = request.headers.get("range")
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=300",
        "Content-Disposition": "inline",
    }

    if range_header:
        try:
            start, end = _parse_byte_range(range_header, file_size)
        except (TypeError, ValueError):
            return Response(
                status_code=416,
                headers={"Content-Range": f"bytes */{file_size}", "Accept-Ranges": "bytes"},
            )
        headers.update({
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(end - start + 1),
        })
        return StreamingResponse(
            _iter_file_range(path, start, end),
            status_code=206,
            media_type=media_type,
            headers=headers,
        )

    headers["Content-Length"] = str(file_size)
    return StreamingResponse(
        _iter_file_range(path, 0, file_size - 1),
        media_type=media_type,
        headers=headers,
    )

