"""Outdoor target recognition APIs. Camera is dedicated; inference runs on dai."""

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from agent_gateway import agent_gateway
from auth import get_current_user
from database import get_db
from detector_client import detect_image, get_detector_status, last_detections, set_inference_control
from models import User
from robot_tcp import require_device
from sqlalchemy.orm import Session
from recognition_client import (
    capture_camera,
    get_camera_detections,
    get_camera_status,
    list_recognition_devices,
    open_camera_stream,
    public_device,
    resolve_device,
)
from recognition_store import latest_event, list_events, record_detections, summary

router = APIRouter(prefix="/api/recognition", tags=["目标识别"])


@router.post("/inference")
async def recognition_inference(
    payload: dict = Body(default_factory=dict),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start/stop the vehicle-side gun detector without affecting motion."""
    robot_id = payload.get("robotId") or payload.get("device_id")
    if robot_id is None:
        raise HTTPException(status_code=422, detail="请选择一个设备")
    try:
        robot_id = int(robot_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="设备编号无效") from exc
    require_device(robot_id, db)
    enabled = bool(payload.get("enabled"))
    try:
        response = await agent_gateway.send_command(
            robot_id,
            {"type": "recognition_control", "enabled": enabled},
            timeout=75.0,
        )
    except HTTPException as exc:
        if exc.status_code == 504:
            raise HTTPException(
                status_code=504,
                detail="DAI 启动或停止超时，请确认 10.139.91.78:9100 TensorRT 服务后重试",
            ) from exc
        raise
    control = set_inference_control(robot_id, {**response, "enabled": enabled and bool(response.get("ok", True))})
    return {
        "ok": bool(response.get("ok", True)),
        "enabled": bool(control.get("enabled")),
        "response": {**response, **control},
    }


def _status_payload(device_id=None):
    device = public_device(resolve_device(device_id))
    live = last_detections(device_id)
    camera = get_camera_status(device_id)
    inference = get_detector_status(device_id)
    if live.get("camera") == "gun" or live.get("source") == "camera":
        camera = {
            **camera,
            "configured": True,
            "online": True if camera.get("online") or live.get("camera") else camera.get("online"),
            "source": live.get("camera") or camera.get("source") or "gun",
            "message": "",
        }
        device = {**device, "configured": True}
    return {
        "device": device,
        "camera": camera,
        "inference": inference,
        "last_result": {
            "detections": live.get("detections") or [],
            "stale": bool(inference.get("stale") or live.get("stale")),
            "live": bool(inference.get("live")),
            "updated_at": live.get("last_detection_time") or live.get("updated_at"),
            "latency_ms": live.get("latency_ms") or (live.get("detector") or {}).get("latency_ms"),
        },
    }


@router.get("/devices")
def recognition_devices(current_user: User = Depends(get_current_user)):
    return list_recognition_devices()


@router.get("/status")
def recognition_status(
    device_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
):
    return _status_payload(device_id)


@router.get("/detections")
def recognition_detections(
    device_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
):
    try:
        return get_camera_detections(device_id)
    except HTTPException as error:
        if error.status_code != 409:
            raise
        cached = last_detections(device_id)
        cached["camera_configured"] = bool(cached.get("source") == "camera")
        cached["stale"] = bool(cached.get("stale") or get_detector_status(device_id).get("stale"))
        cached["live"] = bool(get_detector_status(device_id).get("live"))
        return cached


@router.post("/detect")
def recognition_detect(
    payload: dict = Body(default_factory=dict),
    current_user: User = Depends(get_current_user),
):
    image_b64 = payload.get("image_b64") or payload.get("image")
    if not image_b64:
        raise HTTPException(status_code=400, detail="缺少 image_b64")
    device_id = payload.get("device_id") or payload.get("deviceId")
    result = detect_image(image_b64, device_id=device_id, extra=payload)
    events = record_detections(
        result.get("detections") or [],
        source="detector",
        device_id=device_id or (result.get("device_id")),
    )
    result["events"] = events
    return result


@router.post("/capture")
def recognition_capture(
    payload: dict = Body(default_factory=dict),
    current_user: User = Depends(get_current_user),
):
    device_id = payload.get("deviceId") or payload.get("device_id")
    return capture_camera(device_id, payload)


@router.get("/stream")
def recognition_stream(
    device_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
):
    source = open_camera_stream(device_id)

    def iter_stream():
        try:
            while True:
                chunk = source.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            source.close()

    return StreamingResponse(
        iter_stream(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/results")
def recognition_results(
    limit: int = 50,
    category: str | None = None,
    device_id: str | None = Query(default=None),
    since: str | None = Query(default=None),
    until: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
):
    return {
        "results": list_events(
            limit=limit,
            category=category,
            device_id=device_id,
            since=since,
            until=until,
        )
    }


@router.post("/results")
def create_recognition_result(
    payload: dict = Body(default_factory=dict),
    current_user: User = Depends(get_current_user),
):
    detections = payload.get("detections")
    if not detections:
        detections = [
            {
                "label": payload.get("targetName") or payload.get("value") or "目标",
                "confidence": payload.get("confidence") or 0,
                "bbox": payload.get("bbox") or {},
            }
        ]
    events = record_detections(
        detections or [],
        source=payload.get("source") or "report",
        device_id=payload.get("robotId") or payload.get("device_id"),
        device_name=payload.get("device_name") or payload.get("deviceName"),
        image_url=payload.get("imageUrl") or payload.get("image_url"),
        latency_ms=payload.get("latency_ms"),
    )
    return {"message": "识别结果已入库", "results": events}


@router.get("/latest")
def recognition_latest(current_user: User = Depends(get_current_user)):
    return {"result": latest_event()}


@router.get("/summary")
def recognition_summary(current_user: User = Depends(get_current_user)):
    return summary()
