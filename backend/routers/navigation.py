"""ROS navigation controls forwarded through the vehicle agent."""

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from agent_gateway import agent_gateway
from auth import get_current_user
from database import get_db
from models import User
from robot_tcp import require_device
from schemas import (
    MappingActionRequest,
    MappingMapRequest,
    NavigationGoalRequest,
    NavigationInitialPoseRequest,
    NavigationLocalizationRequest,
    NavigationMapPreviewRequest,
    NavigationStartRequest,
    NavigationStopRequest,
)


router = APIRouter(prefix="/api/navigation", tags=["巡检导航"])


async def send_navigation_command(
    robot_id: int,
    payload: dict[str, Any],
    expected_type: str,
    timeout: float = 8.0,
) -> dict[str, Any]:
    response = await agent_gateway.send_command(robot_id, payload, timeout=timeout)
    if response.get("type") != expected_type:
        raise HTTPException(status_code=502, detail="无人车返回了非预期导航响应")
    return response


def touch_device_online(robot_id: int, db: Session) -> None:
    device = require_device(robot_id, db)
    device.status = "online"
    device.last_seen = datetime.now()
    db.commit()


def require_robot_id(robot_id: Optional[int]) -> int:
    if robot_id is None:
        raise HTTPException(status_code=422, detail="请选择一个设备")
    return robot_id


@router.get("/status")
async def navigation_status(
    robotId: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(robot_id, {"type": "nav_status"}, "nav_status")
    touch_device_online(robot_id, db)
    return {"ok": True, "response": response}


@router.get("/maps")
async def navigation_maps(
    robotId: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(robot_id, {"type": "nav_maps"}, "nav_maps")
    touch_device_online(robot_id, db)
    return {"ok": True, "maps": response.get("maps", []), "mapDir": response.get("mapDir")}


@router.post("/map-preview")
async def navigation_map_preview(
    req: NavigationMapPreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(req.robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(
        robot_id,
        {"type": "nav_map_preview", "mapName": req.mapName},
        "nav_map_preview",
        timeout=15.0,
    )
    touch_device_online(robot_id, db)
    return {"ok": True, "preview": response}


@router.post("/start")
async def navigation_start(
    req: NavigationStartRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(req.robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(
        robot_id,
        {"type": "nav_start", "mapName": req.mapName},
        "nav_status",
        timeout=10.0,
    )
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "response": response}


@router.post("/goal")
async def navigation_goal(
    req: NavigationGoalRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(req.robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(
        robot_id,
        {"type": "nav_goal", "x": req.x, "y": req.y, "yaw": req.yaw},
        "ack",
    )
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "response": response}


@router.post("/stop")
async def navigation_stop(
    req: NavigationStopRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(req.robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(robot_id, {"type": "nav_stop"}, "nav_status")
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "response": response}


@router.post("/initial-pose")
async def navigation_initial_pose(
    req: NavigationInitialPoseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(req.robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(
        robot_id,
        {"type": "nav_initial_pose", "x": req.x, "y": req.y, "yaw": req.yaw},
        "localization_status",
    )
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "response": response}


@router.post("/global-localization")
async def navigation_global_localization(
    req: NavigationLocalizationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(req.robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(
        robot_id,
        {"type": "nav_global_localization"},
        "localization_status",
    )
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "response": response}


@router.post("/global-localization/stop")
async def navigation_global_localization_stop(
    req: NavigationLocalizationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(req.robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(
        robot_id,
        {"type": "nav_global_localization_stop"},
        "localization_status",
    )
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "response": response}


@router.get("/mapping/status")
async def mapping_status(
    robotId: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(robot_id, {"type": "map_status"}, "map_status")
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "response": response}


@router.post("/mapping/start")
async def mapping_start(
    req: MappingActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(req.robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(robot_id, {"type": "map_start"}, "map_status", timeout=12.0)
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "response": response}


@router.post("/mapping/pause")
async def mapping_pause(
    req: MappingActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(req.robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(robot_id, {"type": "map_pause"}, "map_status")
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "response": response}


@router.post("/mapping/discard")
async def mapping_discard(
    req: MappingActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(req.robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(robot_id, {"type": "map_discard"}, "map_status")
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "response": response}


@router.get("/mapping/live-preview")
async def mapping_live_preview(
    robotId: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(
        robot_id, {"type": "map_live_preview"}, "map_live_preview", timeout=12.0
    )
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "preview": response}


@router.post("/mapping/save")
async def mapping_save(
    req: MappingMapRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(req.robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(
        robot_id, {"type": "map_save", "mapName": req.mapName}, "map_saved", timeout=30.0
    )
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "response": response}


@router.post("/maps/delete")
async def navigation_map_delete(
    req: MappingMapRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(req.robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(
        robot_id, {"type": "map_delete", "mapName": req.mapName}, "map_deleted"
    )
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "response": response}
