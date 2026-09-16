"""Talk to the dai YOLO service over ZeroTier, same protocol as indoor."""

from __future__ import annotations

import json
import time
from threading import Lock
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from fastapi import HTTPException

from config import DETECTOR_TIMEOUT, DETECTOR_URL
from recognition_client import resolve_device


_CACHE_LOCK = Lock()
_LAST_DETECTIONS: dict = {
    "detections": [],
    "source": "detector",
    "last_detection_time": 0,
}
_LAST_BY_DEVICE: dict = {}
_INFERENCE_CONTROL: dict = {}


def _control_key(device_id=None):
    return str(device_id) if device_id is not None else "_default"


def set_inference_control(device_id, payload):
    payload = payload if isinstance(payload, dict) else {}
    enabled = bool(payload.get("enabled"))
    record = {
        "enabled": enabled,
        "pid": payload.get("pid") or (payload.get("service") or {}).get("main_pid"),
        "state": payload.get("state") or (payload.get("service") or {}).get("active_state"),
        "gpu_ready": bool(payload.get("gpu_ready") or payload.get("ready")),
        "gpu_released": bool(payload.get("gpu_released")),
        "error": payload.get("error") or "",
        "video_preserved": payload.get("video_preserved", True),
        "updated_at": time.time(),
    }
    with _CACHE_LOCK:
        _INFERENCE_CONTROL[_control_key(device_id)] = record
        if device_id is not None:
            _INFERENCE_CONTROL["_default"] = record
        caches = [_LAST_DETECTIONS]
        if device_id is not None and str(device_id) in _LAST_BY_DEVICE:
            caches.append(_LAST_BY_DEVICE[str(device_id)])
        for cache in caches:
            cache["live"] = bool(enabled)
            cache["stale"] = not enabled
    return record


def get_inference_control(device_id=None):
    with _CACHE_LOCK:
        return dict(
            _INFERENCE_CONTROL.get(_control_key(device_id))
            or _INFERENCE_CONTROL.get("_default")
            or {}
        )


def detector_base_urls(device_id=None):
    urls = []
    if DETECTOR_URL:
        urls.append(DETECTOR_URL.rstrip("/"))
    try:
        device = resolve_device(device_id)
    except HTTPException:
        device = None
    if device:
        inference = device.get("inference_node") or {}
        base = (inference.get("base_url") or "").rstrip("/")
        if base and base not in urls:
            urls.append(base)
    return urls


def _request(url, method="GET", payload=None, timeout=None):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout or DETECTOR_TIMEOUT) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=error.code, detail=detail or str(error)) from error
    except (URLError, TimeoutError, OSError) as error:
        raise HTTPException(status_code=503, detail=f"detector unavailable: {error}") from error
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=502, detail="detector returned non-JSON data") from error


def get_detector_status(device_id=None):
    cached = last_detections(device_id)
    age = time.time() - float(cached.get("last_detection_time") or 0)
    detector = cached.get("detector") if isinstance(cached.get("detector"), dict) else {}
    control = get_inference_control(device_id)
    last_result_at = cached.get("last_detection_time") or None
    live_ingest = bool(
        cached.get("source") == "camera"
        and last_result_at
        and age < 12
        and detector.get("enabled", False)
    )
    if control:
        enabled = bool(control.get("enabled"))
        live = bool(enabled and (control.get("gpu_ready") or live_ingest))
        return {
            "online": live,
            "enabled": enabled,
            "live": live,
            "stale": bool((cached.get("detections") or []) and not live),
            "stopped": not enabled,
            "pid": control.get("pid"),
            "state": control.get("state"),
            "gpu_ready": bool(control.get("gpu_ready")),
            "gpu_released": bool(control.get("gpu_released")),
            "video_preserved": control.get("video_preserved", True),
            "base_url": detector.get("url") or "",
            "source": "camera",
            "age": round(age, 2) if last_result_at else None,
            "last_result_at": last_result_at,
            "latency_ms": detector.get("latency_ms"),
            "error": control.get("error") or detector.get("error") or cached.get("error") or "",
            "message": "推理已停止" if not enabled else ("推理在线" if live else "推理启动中"),
            "count": len(cached.get("detections") or []),
        }
    if live_ingest:
        return {
            "online": True,
            "enabled": True,
            "live": True,
            "stale": False,
            "stopped": False,
            "base_url": detector.get("url") or "",
            "source": "camera",
            "age": round(age, 2),
            "last_result_at": last_result_at,
            "latency_ms": detector.get("latency_ms"),
            "error": detector.get("error") or cached.get("error") or "",
            "message": "推理在线",
            "count": len(cached.get("detections") or []),
        }
    return {
        "online": False,
        "enabled": bool(detector.get("enabled", False)),
        "live": False,
        "stale": bool(cached.get("detections")),
        "stopped": not bool(detector.get("enabled", False)),
        "base_url": detector.get("url") or "",
        "source": "camera",
        "age": round(age, 2) if last_result_at else None,
        "last_result_at": last_result_at,
        "latency_ms": detector.get("latency_ms"),
        "error": detector.get("error") or cached.get("error") or "waiting for vehicle detections",
        "message": "等待推理节点",
        "count": len(cached.get("detections") or []),
    }


def detect_image(image_b64, device_id=None, extra=None):
    payload = {
        "image_b64": image_b64,
        "timestamp": time.time(),
        **(extra or {}),
    }
    errors = []
    for base in detector_base_urls(device_id):
        detect_path = "/detect"
        try:
            device = resolve_device(device_id)
            detect_path = (device.get("inference_node") or {}).get("detect_path") or "/detect"
        except HTTPException:
            pass
        try:
            result = _request(urljoin(base + "/", detect_path.lstrip("/")), method="POST", payload=payload)
            cached = {
                "detections": result.get("detections") or [],
                "detection": result.get("detection"),
                "source": "detector",
                "base_url": base,
                "last_detection_time": time.time(),
                "device_id": device_id,
            }
            with _CACHE_LOCK:
                _LAST_DETECTIONS.clear()
                _LAST_DETECTIONS.update(cached)
            return cached
        except HTTPException as error:
            errors.append(f"{base}: {error.detail}")
    raise HTTPException(status_code=503, detail="；".join(errors) or "detector unavailable")


def last_detections(device_id=None):
    with _CACHE_LOCK:
        if device_id is not None and str(device_id) in _LAST_BY_DEVICE:
            cached = dict(_LAST_BY_DEVICE[str(device_id)])
        else:
            cached = dict(_LAST_DETECTIONS)
    if device_id:
        cached["device_id"] = device_id
    return cached


def ingest_detections(payload, device_id=None):
    detector = payload.get("detector") if isinstance(payload.get("detector"), dict) else {}
    control = get_inference_control(device_id)
    enabled = bool(control.get("enabled")) if control else bool(detector.get("enabled"))
    cached = {
        "detections": payload.get("detections") or [],
        "detection": payload.get("detection"),
        "source": payload.get("source") or "camera",
        "camera": payload.get("camera") or "gun",
        "source_width": payload.get("source_width"),
        "source_height": payload.get("source_height"),
        "updated_at": payload.get("updated_at") or time.time(),
        "last_detection_time": time.time(),
        "error": payload.get("error") or detector.get("error") or "",
        "detector": detector,
        "device_id": device_id,
        "live": enabled,
        "stale": not enabled,
        "latency_ms": detector.get("latency_ms") or payload.get("latency_ms"),
    }
    with _CACHE_LOCK:
        _LAST_DETECTIONS.clear()
        _LAST_DETECTIONS.update(cached)
        if device_id is not None:
            _LAST_BY_DEVICE[str(device_id)] = dict(cached)
    return cached
