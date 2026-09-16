"""Proxy the dedicated outdoor recognition camera (not the vehicle depth camera)."""

import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import HTTPException

from config import RECOGNITION_REQUEST_TIMEOUT

_DEVICES_FILE = Path(__file__).with_name("vision_devices.json")


def load_registry():
    if not _DEVICES_FILE.exists():
        return {}, None
    with _DEVICES_FILE.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    devices = {item["id"]: item for item in data.get("devices", [])}
    default_id = data.get("default_device_id") or (next(iter(devices)) if devices else None)
    return devices, default_id


def resolve_device(device_id=None):
    devices, default_id = load_registry()
    target_id = device_id or default_id
    if not target_id or target_id not in devices:
        raise HTTPException(status_code=404, detail=f"recognition device not found: {target_id}")
    return devices[target_id]


def join_url(base_url, path):
    return base_url.rstrip("/") + "/" + path.lstrip("/")


def public_device(device):
    inference_node = device.get("inference_node") or {}
    camera_base_url = (device.get("camera_base_url") or "").strip()
    return {
        "id": device["id"],
        "name": device.get("name", device["id"]),
        "role": device.get("role", "recognition_camera"),
        "configured": bool(camera_base_url),
        "camera_base_url": camera_base_url,
        "stream_url": f"/api/recognition/stream?device_id={device['id']}",
        "inference_node": {
            "id": inference_node.get("id"),
            "name": inference_node.get("name"),
            "base_url": inference_node.get("base_url"),
            "detect_path": inference_node.get("detect_path", "/detect"),
            "report_target": inference_node.get("report_target"),
        },
    }


def list_recognition_devices():
    devices, default_id = load_registry()
    return {
        "default_device_id": default_id,
        "devices": [public_device(device) for device in devices.values()],
    }


def request_json(url, method="GET", payload=None, timeout=None):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout or RECOGNITION_REQUEST_TIMEOUT) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=error.code, detail=detail or str(error)) from error
    except (URLError, TimeoutError, OSError) as error:
        raise HTTPException(status_code=503, detail=f"recognition service unavailable: {error}") from error
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=502, detail="recognition service returned non-JSON data") from error


def get_camera_status(device_id=None):
    device = resolve_device(device_id)
    camera_base_url = (device.get("camera_base_url") or "").strip()
    if not camera_base_url:
        return {
            "configured": False,
            "online": False,
            "message": "专用识别摄像头尚未接入，不使用车上深度相机",
        }
    status = request_json(join_url(camera_base_url, device.get("status_path", "/status")))
    status["configured"] = True
    return status


def get_camera_detections(device_id=None):
    device = resolve_device(device_id)
    camera_base_url = (device.get("camera_base_url") or "").strip()
    if not camera_base_url:
        raise HTTPException(status_code=409, detail="专用识别摄像头尚未接入")
    detections = request_json(join_url(camera_base_url, device.get("detections_path", "/detections")))
    detections["device_id"] = device["id"]
    detections["source"] = "camera"
    return detections


def capture_camera(device_id=None, payload=None):
    device = resolve_device(device_id)
    camera_base_url = (device.get("camera_base_url") or "").strip()
    if not camera_base_url:
        raise HTTPException(status_code=409, detail="专用识别摄像头尚未接入")
    capture_payload = dict(payload or {})
    capture_payload.setdefault("device_id", device["id"])
    result = request_json(
        join_url(camera_base_url, device.get("capture_path", "/capture")),
        method="POST",
        payload=capture_payload,
    )
    result["device_id"] = device["id"]
    return result


def open_camera_stream(device_id=None):
    device = resolve_device(device_id)
    camera_base_url = (device.get("camera_base_url") or "").strip()
    if not camera_base_url:
        raise HTTPException(status_code=409, detail="专用识别摄像头尚未接入")
    stream_url = join_url(camera_base_url, device.get("stream_path", "/stream"))
    request = Request(
        stream_url,
        headers={
            "Accept": "multipart/x-mixed-replace,image/*,*/*",
            "Cache-Control": "no-cache",
        },
        method="GET",
    )
    try:
        return urlopen(request, timeout=RECOGNITION_REQUEST_TIMEOUT)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise HTTPException(status_code=503, detail=f"unable to open recognition stream: {error}") from error
