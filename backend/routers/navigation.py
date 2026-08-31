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
    RtkNavigationGoalRequest,
    RtkRoadActionRequest,
    RtkRoadCollectionStartRequest,
    RtkRoadNetworkBuildRequest,
    RtkRoadPlanRequest,
    RtkRouteStartRequest,
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


@router.get("/rtk/status")
async def rtk_navigation_status(
    robotId: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(
        robot_id, {"type": "rtk_nav_status"}, "rtk_nav_status"
    )
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "response": response}


@router.post("/rtk/start")
async def rtk_navigation_start(
    req: NavigationStopRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(req.robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(
        robot_id, {"type": "rtk_nav_start"}, "rtk_nav_status", timeout=12.0
    )
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "response": response}


@router.post("/rtk/goal")
async def rtk_navigation_goal(
    req: RtkNavigationGoalRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(req.robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(
        robot_id,
        {
            "type": "rtk_nav_goal",
            "longitude": req.longitude,
            "latitude": req.latitude,
            "yaw": req.yaw,
        },
        "rtk_nav_ack",
    )
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "response": response}


@router.post("/rtk/stop")
async def rtk_navigation_stop(
    req: NavigationStopRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(req.robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(
        robot_id, {"type": "rtk_nav_stop"}, "rtk_nav_status"
    )
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "response": response}


@router.post("/rtk/route/start")
async def rtk_route_start(
    req: RtkRouteStartRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(req.robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(
        robot_id,
        {
            "type": "rtk_route_start",
            "networkId": req.networkId,
            "goalLongitude": req.goalLongitude,
            "goalLatitude": req.goalLatitude,
            "maxSnapM": req.maxSnapM,
        },
        "rtk_nav_status",
        timeout=35.0,
    )
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "response": response}


async def send_rtk_route_action(
    req: RtkRoadActionRequest,
    command_type: str,
    db: Session,
) -> dict[str, Any]:
    robot_id = require_robot_id(req.robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(
        robot_id, {"type": command_type}, "rtk_nav_status", timeout=12.0
    )
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "response": response}


@router.post("/rtk/route/pause")
async def rtk_route_pause(
    req: RtkRoadActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await send_rtk_route_action(req, "rtk_route_pause", db)


@router.post("/rtk/route/resume")
async def rtk_route_resume(
    req: RtkRoadActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await send_rtk_route_action(req, "rtk_route_resume", db)


@router.post("/rtk/route/stop")
async def rtk_route_stop(
    req: RtkRoadActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await send_rtk_route_action(req, "rtk_route_stop", db)


@router.get("/rtk/roads/status")
async def rtk_road_collection_status(
    robotId: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(
        robot_id, {"type": "rtk_road_status"}, "rtk_road_status"
    )
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "response": response}


@router.post("/rtk/roads/start")
async def rtk_road_collection_start(
    req: RtkRoadCollectionStartRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(req.robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(
        robot_id,
        {"type": "rtk_road_start", "name": req.name},
        "rtk_road_status",
    )
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "response": response}


async def send_rtk_road_action(
    req: RtkRoadActionRequest,
    command_type: str,
    expected_type: str,
    db: Session,
) -> dict[str, Any]:
    robot_id = require_robot_id(req.robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(
        robot_id, {"type": command_type}, expected_type, timeout=12.0
    )
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "response": response}


@router.post("/rtk/roads/pause")
async def rtk_road_collection_pause(
    req: RtkRoadActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await send_rtk_road_action(req, "rtk_road_pause", "rtk_road_status", db)


@router.post("/rtk/roads/resume")
async def rtk_road_collection_resume(
    req: RtkRoadActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await send_rtk_road_action(req, "rtk_road_resume", "rtk_road_status", db)


@router.post("/rtk/roads/stop")
async def rtk_road_collection_stop(
    req: RtkRoadActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await send_rtk_road_action(req, "rtk_road_stop", "rtk_road_saved", db)


@router.post("/rtk/roads/discard")
async def rtk_road_collection_discard(
    req: RtkRoadActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await send_rtk_road_action(req, "rtk_road_discard", "rtk_road_status", db)


@router.get("/rtk/roads/tracks")
async def rtk_road_tracks(
    robotId: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(
        robot_id, {"type": "rtk_road_tracks"}, "rtk_road_tracks"
    )
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "tracks": response.get("tracks", [])}


@router.get("/rtk/roads/tracks/{track_id}")
async def rtk_road_track(
    track_id: str,
    robotId: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(
        robot_id,
        {"type": "rtk_road_track", "trackId": track_id},
        "rtk_road_track",
        timeout=12.0,
    )
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "track": response.get("track"), "response": response}


@router.post("/rtk/roads/networks/build")
async def rtk_road_network_build(
    req: RtkRoadNetworkBuildRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(req.robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(
        robot_id,
        {"type": "rtk_road_network_build", "name": req.name, "trackIds": req.trackIds},
        "rtk_road_network",
        timeout=20.0,
    )
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "network": response.get("network"), "response": response}


@router.get("/rtk/roads/networks")
async def rtk_road_networks(
    robotId: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(
        robot_id, {"type": "rtk_road_networks"}, "rtk_road_networks"
    )
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "networks": response.get("networks", [])}


@router.get("/rtk/roads/networks/{network_id}")
async def rtk_road_network(
    network_id: str,
    robotId: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(
        robot_id,
        {"type": "rtk_road_network", "networkId": network_id},
        "rtk_road_network",
        timeout=12.0,
    )
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "network": response.get("network"), "response": response}


@router.post("/rtk/roads/plan")
async def rtk_road_plan(
    req: RtkRoadPlanRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    robot_id = require_robot_id(req.robotId)
    require_device(robot_id, db)
    response = await send_navigation_command(
        robot_id,
        {
            "type": "rtk_road_plan",
            "networkId": req.networkId,
            "goalLongitude": req.goalLongitude,
            "goalLatitude": req.goalLatitude,
            "maxSnapM": req.maxSnapM,
        },
        "rtk_road_plan",
        timeout=15.0,
    )
    touch_device_online(robot_id, db)
    return {"ok": bool(response.get("ok")), "plan": response.get("plan"), "response": response}


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
