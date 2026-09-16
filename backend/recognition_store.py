"""Persist outdoor recognition events as JSON, without indoor inspection tables."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_FILE = DATA_DIR / "recognition_events.json"
AI_DIR = DATA_DIR / "ai_analysis" / "recognition"
_LOCK = threading.Lock()
_LAST_SIGNATURE = {}


def _read():
    if not DATA_FILE.exists():
        return []
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def _write(events):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")


def _confidence_pct(value):
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0
    if number <= 1:
        number *= 100
    return round(number)


def _parse_event_time(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value)
    text = str(value or "").strip()
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], pattern)
        except ValueError:
            continue
    return None


def _signature(device_id, detections):
    parts = []
    for item in detections or []:
        box = item.get("bbox") or {}
        parts.append(
            (
                str(item.get("label") or item.get("class_name") or ""),
                round(float(item.get("confidence") or 0), 2),
                int(float(box.get("x") or 0) / 8),
                int(float(box.get("y") or 0) / 8),
            )
        )
    return (str(device_id), tuple(parts))


def save_preview_jpeg(jpeg_bytes, event_id):
    if not jpeg_bytes:
        return None
    AI_DIR.mkdir(parents=True, exist_ok=True)
    relative = f"ai_analysis/recognition/{event_id}.jpg"
    path = DATA_DIR / relative
    path.write_bytes(jpeg_bytes)
    return relative


def record_detections(
    detections,
    *,
    source="detector",
    device_id=None,
    device_name=None,
    image_url=None,
    jpeg_bytes=None,
    latency_ms=None,
    recognized_at=None,
):
    events = []
    now = datetime.now()
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    if recognized_at:
        parsed = _parse_event_time(recognized_at)
        if parsed:
            stamp = parsed.strftime("%Y-%m-%d %H:%M:%S")
    items = [item for item in (detections or []) if isinstance(item, dict)]
    if not items:
        return []
    signature = _signature(device_id, items)
    with _LOCK:
        previous = _LAST_SIGNATURE.get(str(device_id))
        if previous and previous[0] == signature and time.time() - previous[1] < 30:
            return []
        _LAST_SIGNATURE[str(device_id)] = (signature, time.time())
    for index, detection in enumerate(items):
        label = detection.get("label") or detection.get("class_name") or "目标"
        confidence = _confidence_pct(detection.get("confidence"))
        event_id = f"R-{now.strftime('%Y%m%d')}-{uuid4().hex[:8]}-{index}"
        image = image_url
        if index == 0 and jpeg_bytes:
            image = save_preview_jpeg(jpeg_bytes, event_id) or image
        bbox = detection.get("bbox") or {}
        event = {
            "id": event_id,
            "category": "target",
            "title": "YOLO目标检测",
            "subject": label,
            "identity": "目标识别",
            "device_id": device_id,
            "device": device_name or device_id or "dai",
            "device_name": device_name or device_id or "dai",
            "map": "室外巡检",
            "time": stamp,
            "recognized_at": stamp,
            "confidence": confidence,
            "bbox": bbox,
            "image": image,
            "latency_ms": latency_ms if latency_ms is not None else detection.get("latency_ms"),
            "status": "已识别" if confidence else "待复核",
            "detail": f"bbox={bbox}",
            "source": source,
            "raw": detection,
        }
        events.append(event)
        AI_DIR.mkdir(parents=True, exist_ok=True)
        sidecar = {
            "title": f"{label} · {confidence}%",
            "summary": f"{device_name or device_id or '室外巡检车'} 识别到 {label}，置信度 {confidence}%",
            "device": event["device_name"],
            "device_name": event["device_name"],
            "device_id": device_id,
            "timestamp": stamp,
            "captured_at": stamp,
            "confidence": confidence,
            "labels": [label],
            "detections": [detection],
            "image": image,
            "preview_path": image,
            "severity": "普通",
            "latency_ms": event["latency_ms"],
            "source": source,
        }
        (AI_DIR / f"{event_id}.json").write_text(
            json.dumps(sidecar, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    with _LOCK:
        stored = events + _read()
        _write(stored[:500])
    return events


def list_events(limit=50, category=None, device_id=None, since=None, until=None):
    with _LOCK:
        events = _read()
    if category and category != "all":
        events = [item for item in events if item.get("category") == category]
    if device_id not in (None, "", "all"):
        wanted = str(device_id)
        events = [
            item
            for item in events
            if str(item.get("device_id") or "") == wanted or str(item.get("device") or "") == wanted
        ]
    since_at = _parse_event_time(since) if since else None
    until_at = _parse_event_time(until) if until else None
    if since_at or until_at:
        filtered = []
        for item in events:
            event_at = _parse_event_time(item.get("recognized_at") or item.get("time"))
            if event_at is None:
                continue
            if since_at and event_at < since_at:
                continue
            if until_at and event_at > until_at:
                continue
            filtered.append(item)
        events = filtered
    return events[: max(1, min(int(limit or 50), 200))]


def latest_event():
    events = list_events(limit=1)
    return events[0] if events else None


def summary():
    events = list_events(limit=200)
    total = len(events)
    pending = len([item for item in events if "待" in str(item.get("status") or "")])
    return {
        "total": total,
        "normal": total - pending,
        "abnormal": pending,
        "pendingReview": pending,
        "successRate": round((total - pending) / total * 100, 1) if total else 0,
    }
