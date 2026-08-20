"""
outdoor_patrol.py — 校园室外巡检路由（阶段 B/C）
=====================================================================
本路由模块与既有 routers/patrol.py（室内 SLAM）严格分离，独立挂载在
/api/outdoor-patrol 前缀下，避免坐标类型混用污染室内流程（需求 §5.1）。

阶段 C-2 当前交付范围：
  - POST /api/outdoor-patrol/precheck       启动预检（mock 实现，完整契约）
  - GET  /api/outdoor-patrol/calibrations   标定版本列表（用于前端下拉）
  - GET  /api/outdoor-patrol/routes         路线列表（用于前端下拉）

后续阶段将逐步接入：
  - POST /tasks              创建任务
  - POST /tasks/{id}/start   启动任务（依赖 precheck 通过）
  - POST /tasks/{id}/pause   暂停
  - POST /tasks/{id}/resume  恢复（重新预检）
  - POST /tasks/{id}/cancel  取消
  - POST /tasks/{id}/estop   紧急停止（最高优先级）
  - GET  /tasks/{id}/events  事件审计
  - GET  /tasks/{id}/track   轨迹回放
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import (
    Device,
    OutdoorCalibration,
    OutdoorPatrolEvent,
    OutdoorPatrolTask,
    OutdoorRoute,
    OutdoorWaypoint,
    User,
)
from services.coord_transform import (
    Calibration as CalibrationParams,
    wgs84_to_enu,
)
from schemas import (
    OutdoorCalibrationCreate,
    OutdoorCalibrationUpdate,
    OutdoorPatrolTaskCreate,
    OutdoorPrecheckRequest,
    OutdoorPrecheckResponse,
    OutdoorRouteCreate,
    OutdoorRouteUpdate,
    OutdoorWaypointCreate,
    OutdoorWaypointUpdate,
)


router = APIRouter(prefix="/api/outdoor-patrol", tags=["校园室外巡检"])


# ─────────────────────────────────────────────────────────────
# 预检实现
# ─────────────────────────────────────────────────────────────

# 预检项的固定清单（对应需求 FR-04.2）
PRECHECK_ITEMS = [
    "device_online",
    "control_channel",
    "localization_healthy",
    "calibration_consistent",
    "obstacle_sensor_available",
    "battery_sufficient",
    "route_valid",
    "fence_valid",
]


class PrecheckResult:
    """单次预检的内部结果聚合"""

    def __init__(self):
        self.checks: List[Dict[str, Any]] = []
        self._idx = {name: i for i, name in enumerate(PRECHECK_ITEMS)}

    def add(self, item: str, passed: bool, reason: Optional[str] = None,
            detail: Optional[Dict[str, Any]] = None):
        if item not in self._idx:
            raise ValueError(f"未知预检项: {item}")
        entry = {"item": item, "passed": passed, "reason": reason}
        if detail:
            entry["detail"] = detail
        self.checks.append(entry)

    @property
    def ok(self) -> bool:
        return all(c["passed"] for c in self.checks)

    def to_response(self) -> Dict[str, Any]:
        return {"ok": self.ok, "checks": self.checks}


# ─────────────────────────────────────────────────────────────
# 预检：单项实现（当前为 mock，阶段 C 接入真实状态读取）
# ─────────────────────────────────────────────────────────────

def _check_device_online(device: Optional[Device]) -> Dict[str, Any]:
    if device is None:
        return {"passed": False, "reason": "设备不存在"}
    if device.status != "online":
        return {"passed": False, "reason": f"设备状态为 {device.status}，需要 online"}
    return {"passed": True, "reason": None}


def _check_control_channel(device: Optional[Device]) -> Dict[str, Any]:
    """阶段 C 将通过 agent_gateway 心跳判定；当前阶段返回 mock 通过"""
    if device is None:
        return {"passed": False, "reason": "设备不存在"}
    # TODO(C): 接入 agent_gateway.send_command(robot_id, {"type": "ping"}, ...)
    return {"passed": True, "reason": "mock: 控制通道检测待接入 agent_gateway"}


def _check_localization_healthy(device: Optional[Device]) -> Dict[str, Any]:
    """阶段 C 将读取车端 /localization/health 话题缓存；当前返回 mock 未通过（避免误启动）"""
    # TODO(C): 通过 telemetry.extra_json.localizationHealthy 判定
    return {
        "passed": False,
        "reason": "mock: 定位健康度检测待接入车端上报；阶段 A GNSS 恢复后开启",
    }


def _check_calibration_consistent(
    task: Optional[OutdoorPatrolTask],
    route: Optional[OutdoorRoute],
    active_calibration: Optional[OutdoorCalibration],
) -> Dict[str, Any]:
    """校验任务的标定版本与当前 active 标定一致"""
    if route is None or active_calibration is None:
        return {"passed": False, "reason": "路线或标定版本不存在"}
    if route.calibration_id != active_calibration.id:
        return {
            "passed": False,
            "reason": f"路线标定ID={route.calibration_id} 与当前 active={active_calibration.id} 不一致",
        }
    if active_calibration.status != "active":
        return {"passed": False, "reason": f"标定版本状态为 {active_calibration.status}，需要 active"}
    return {"passed": True, "reason": None}


def _check_obstacle_sensor(device: Optional[Device]) -> Dict[str, Any]:
    """阶段 C 将读取车端激光雷达/深度相机话题状态；当前返回 mock 通过"""
    # TODO(C): 通过 agent_gateway 查询 /scan 或深度话题的最近数据年龄
    return {"passed": True, "reason": "mock: 避障传感器检测待接入车端"}


def _check_battery(device: Optional[Device], threshold: int = 20) -> Dict[str, Any]:
    if device is None or device.battery is None:
        return {"passed": False, "reason": "电量未知"}
    if device.battery < threshold:
        return {"passed": False, "reason": f"电量 {device.battery}% 低于阈值 {threshold}%"}
    return {"passed": True, "reason": None}


def _check_route_valid(route: Optional[OutdoorRoute]) -> Dict[str, Any]:
    if route is None:
        return {"passed": False, "reason": "路线不存在"}
    if route.status not in ("published", "frozen"):
        return {"passed": False, "reason": f"路线状态为 {route.status}，需要 published 或 frozen"}
    if not route.waypoints:
        return {"passed": False, "reason": "路线无航点"}
    return {"passed": True, "reason": None}


def _check_fence_valid(route: Optional[OutdoorRoute]) -> Dict[str, Any]:
    if route is None:
        return {"passed": False, "reason": "路线不存在"}
    if route.fence_geojson is None:
        return {"passed": False, "reason": "路线未配置电子围栏"}
    # TODO(C): 解析 GeoJSON 校验几何合法性（多边形闭合、最小面积等）
    return {"passed": True, "reason": None}


# ─────────────────────────────────────────────────────────────
# 接口实现
# ─────────────────────────────────────────────────────────────

@router.post("/precheck", response_model=OutdoorPrecheckResponse)
async def precheck(
    req: OutdoorPrecheckRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """任务启动预检（FR-04.2）

    按 PRECHECK_ITEMS 顺序执行 8 项检查；任一未通过即返回 ok=false。
    当前为 mock 实现：device_online / battery / route / fence 已可用真实数据，
    localization_healthy 强制未通过（避免误启动），其它返回 mock 通过。
    """
    task = db.query(OutdoorPatrolTask).filter_by(id=req.task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status not in ("pending", "paused"):
        raise HTTPException(
            status_code=409,
            detail=f"任务当前状态 {task.status}，仅 pending/paused 可预检",
        )

    route = db.query(OutdoorRoute).filter_by(id=task.route_id).first()
    device = db.query(Device).filter_by(id=task.device_id).first() if task.device_id else None
    active_cal = (
        db.query(OutdoorCalibration)
        .filter_by(status="active")
        .order_by(OutdoorCalibration.updated_at.desc())
        .first()
    )

    result = PrecheckResult()

    r = _check_device_online(device);          result.add("device_online", **r)
    r = _check_control_channel(device);        result.add("control_channel", **r)
    r = _check_localization_healthy(device);   result.add("localization_healthy", **r)
    r = _check_calibration_consistent(task, route, active_cal)
    result.add("calibration_consistent", **r)
    r = _check_obstacle_sensor(device);        result.add("obstacle_sensor_available", **r)
    r = _check_battery(device);                result.add("battery_sufficient", **r)
    r = _check_route_valid(route);             result.add("route_valid", **r)
    r = _check_fence_valid(route);             result.add("fence_valid", **r)

    # 把预检结果回写到任务
    task.precheck_result = result.to_response()
    task.updated_at = datetime.now()
    db.commit()

    # 记录事件审计
    event_type = "precheck_passed" if result.ok else "precheck_failed"
    event = OutdoorPatrolEvent(
        task_id=task.id,
        event_type=event_type,
        severity="info" if result.ok else "warn",
        reason=",".join([
            f"{c['item']}={c['reason'] or 'ok'}"
            for c in result.checks if not c["passed"]
        ]) or "all checks passed",
        detail={"checks": result.checks},
        operator_id=current_user.id,
        occurred_at=datetime.now(),
    )
    db.add(event)
    db.commit()

    return result.to_response()


@router.get("/calibrations")
async def list_calibrations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出所有标定版本（用于前端下拉选择）"""
    cals = db.query(OutdoorCalibration).order_by(
        OutdoorCalibration.created_at.desc()
    ).all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "version": c.version,
            "origin_lng": float(c.origin_lng),
            "origin_lat": float(c.origin_lat),
            "origin_yaw": float(c.origin_yaw),
            "status": c.status,
            "verified_at": c.verified_at.isoformat() if c.verified_at else None,
        }
        for c in cals
    ]


@router.get("/routes")
async def list_routes(
    calibration_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出所有路线（可按标定ID过滤）"""
    q = db.query(OutdoorRoute)
    if calibration_id is not None:
        q = q.filter_by(calibration_id=calibration_id)
    routes = q.order_by(OutdoorRoute.created_at.desc()).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "version": r.version,
            "calibration_id": r.calibration_id,
            "status": r.status,
            "waypoint_count": len(r.waypoints),
            "max_speed_ms": float(r.max_speed_ms) if r.max_speed_ms else None,
            "fence_type": r.fence_type,
        }
        for r in routes
    ]


@router.get("/tasks/{task_id}/events")
async def list_task_events(
    task_id: int,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出任务的事件审计记录（FR-06.2）"""
    task = db.query(OutdoorPatrolTask).filter_by(id=task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    events = (
        db.query(OutdoorPatrolEvent)
        .filter_by(task_id=task_id)
        .order_by(OutdoorPatrolEvent.occurred_at.desc())
        .limit(min(limit, 500))
        .all()
    )
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "severity": e.severity,
            "reason": e.reason,
            "detail": e.detail,
            "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
            "loc_lng": float(e.loc_lng) if e.loc_lng else None,
            "loc_lat": float(e.loc_lat) if e.loc_lat else None,
            "loc_health": e.loc_health,
        }
        for e in events
    ]


# ─────────────────────────────────────────────────────────────
# 标定版本 CRUD
# ─────────────────────────────────────────────────────────────

@router.post("/calibrations")
async def create_calibration(
    data: OutdoorCalibrationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建校园坐标标定（FR-02.1）

    新建标定默认状态为 draft；必须经现场对点验证后才能转为 active。
    """
    existing = db.query(OutdoorCalibration).filter_by(version=data.version).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"标定版本号 {data.version} 已存在")
    cal = OutdoorCalibration(
        name=data.name,
        version=data.version,
        description=data.description,
        origin_lng=data.origin_lng,
        origin_lat=data.origin_lat,
        origin_alt=data.origin_alt,
        origin_yaw=data.origin_yaw,
        status="draft",
    )
    db.add(cal)
    db.commit()
    db.refresh(cal)
    return {
        "id": cal.id,
        "name": cal.name,
        "version": cal.version,
        "status": cal.status,
        "message": "已创建为 draft；完成现场对点验证后通过 PUT /calibrations/{id} 改为 active",
    }


@router.get("/calibrations/{calibration_id}")
async def get_calibration(
    calibration_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取标定详情"""
    cal = db.query(OutdoorCalibration).filter_by(id=calibration_id).first()
    if cal is None:
        raise HTTPException(status_code=404, detail="标定不存在")
    return {
        "id": cal.id,
        "name": cal.name,
        "version": cal.version,
        "description": cal.description,
        "origin_lng": float(cal.origin_lng),
        "origin_lat": float(cal.origin_lat),
        "origin_alt": float(cal.origin_alt) if cal.origin_alt is not None else None,
        "origin_yaw": float(cal.origin_yaw),
        "status": cal.status,
        "verification_geojson": cal.verification_geojson,
        "verified_by": cal.verified_by,
        "verified_at": cal.verified_at.isoformat() if cal.verified_at else None,
        "created_at": cal.created_at.isoformat() if cal.created_at else None,
        "updated_at": cal.updated_at.isoformat() if cal.updated_at else None,
    }


@router.put("/calibrations/{calibration_id}")
async def update_calibration(
    calibration_id: int,
    data: OutdoorCalibrationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新标定（FR-02.2）

    状态机：draft → verified → active → deprecated
    原点修改仅允许在 draft 状态下进行；转为 active 时会自动把原 active 标定降级为 deprecated。
    """
    cal = db.query(OutdoorCalibration).filter_by(id=calibration_id).first()
    if cal is None:
        raise HTTPException(status_code=404, detail="标定不存在")

    # 原点修改仅在 draft 时允许
    origin_fields = ("origin_lng", "origin_lat", "origin_alt", "origin_yaw")
    if cal.status != "draft" and any(getattr(data, f, None) is not None for f in origin_fields):
        raise HTTPException(
            status_code=409,
            detail=f"标定状态为 {cal.status}，原点不可修改；请新建版本",
        )

    # 应用非空字段
    for f in ("name", "description", "origin_lng", "origin_lat",
              "origin_alt", "origin_yaw", "status",
              "verification_geojson", "verified_by"):
        v = getattr(data, f, None)
        if v is not None:
            setattr(cal, f, v)

    # 状态转 active 时降级原 active
    if data.status == "active":
        if cal.status != "verified" and not cal.verification_geojson:
            raise HTTPException(
                status_code=422,
                detail="转为 active 前需先完成对点验证（提交 verification_geojson）",
            )
        existing_active = (
            db.query(OutdoorCalibration)
            .filter(OutdoorCalibration.status == "active",
                    OutdoorCalibration.id != calibration_id)
            .all()
        )
        for o in existing_active:
            o.status = "deprecated"
        if data.verified_by and not cal.verified_at:
            cal.verified_at = datetime.now()

    db.commit()
    db.refresh(cal)
    return {"id": cal.id, "status": cal.status, "message": "更新成功"}


@router.delete("/calibrations/{calibration_id}")
async def delete_calibration(
    calibration_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """软删除标定（转为 deprecated，不真正删除）

    active 状态的标定禁止删除；引用此标定的路线存在时也禁止。
    """
    cal = db.query(OutdoorCalibration).filter_by(id=calibration_id).first()
    if cal is None:
        raise HTTPException(status_code=404, detail="标定不存在")
    if cal.status == "active":
        raise HTTPException(status_code=409, detail="active 标定不可删除，请先切换其它版本")
    routes_using = db.query(OutdoorRoute).filter_by(calibration_id=calibration_id).count()
    if routes_using > 0:
        raise HTTPException(
            status_code=409,
            detail=f"有 {routes_using} 条路线引用此标定，不可删除",
        )
    cal.status = "deprecated"
    db.commit()
    return {"id": cal.id, "status": cal.status, "message": "已转为 deprecated"}


# ─────────────────────────────────────────────────────────────
# 路线 CRUD（含航点）
# ─────────────────────────────────────────────────────────────

def _serialize_waypoint(w: OutdoorWaypoint) -> Dict[str, Any]:
    return {
        "id": w.id,
        "seq_order": w.seq_order,
        "name": w.name,
        "geo_lng": float(w.geo_lng),
        "geo_lat": float(w.geo_lat),
        "enu_x": float(w.enu_x) if w.enu_x is not None else None,
        "enu_y": float(w.enu_y) if w.enu_y is not None else None,
        "yaw": float(w.yaw) if w.yaw is not None else None,
        "arrival_radius_m": float(w.arrival_radius_m),
        "dwell_seconds": w.dwell_seconds,
        "action": w.action,
        "action_params": w.action_params,
        "timeout_seconds": w.timeout_seconds,
        "is_enabled": w.is_enabled,
    }


def _serialize_route(r: OutdoorRoute, include_waypoints: bool = False) -> Dict[str, Any]:
    out = {
        "id": r.id,
        "name": r.name,
        "description": r.description,
        "calibration_id": r.calibration_id,
        "calibration_version": r.calibration.version if r.calibration else None,
        "version": r.version,
        "parent_id": r.parent_id,
        "fence_type": r.fence_type,
        "fence_geojson": r.fence_geojson,
        "fence_buffer_m": float(r.fence_buffer_m) if r.fence_buffer_m is not None else None,
        "max_speed_ms": float(r.max_speed_ms) if r.max_speed_ms is not None else None,
        "applicable_device_types": r.applicable_device_types,
        "status": r.status,
        "waypoint_count": len(r.waypoints),
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }
    if include_waypoints:
        out["waypoints"] = [_serialize_waypoint(w) for w in
                            sorted(r.waypoints, key=lambda x: x.seq_order)]
    return out


def _compute_enu_for_waypoints(db: Session, route: OutdoorRoute,
                               waypoints_data: List[OutdoorWaypointCreate]):
    """根据 route.calibration 计算 ENU 坐标，回填到 waypoint 行"""
    cal = route.calibration
    if cal is None:
        return
    cal_params = CalibrationParams(
        version=cal.version,
        origin_lat=float(cal.origin_lat),
        origin_lng=float(cal.origin_lng),
        origin_alt=float(cal.origin_alt) if cal.origin_alt is not None else 0.0,
        yaw_offset=float(cal.origin_yaw),
    )
    for i, wp_data in enumerate(waypoints_data):
        e, n, _ = wgs84_to_enu(wp_data.geo_lat, wp_data.geo_lng, cal_params)
        if i < len(route.waypoints):
            route.waypoints[i].enu_x = e
            route.waypoints[i].enu_y = n


@router.post("/routes")
async def create_route(
    data: OutdoorRouteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建路线（FR-03.1）

    新建路线默认状态为 draft，版本号 v1；提交航点时自动计算 ENU 坐标。
    """
    cal = db.query(OutdoorCalibration).filter_by(id=data.calibration_id).first()
    if cal is None:
        raise HTTPException(status_code=404, detail=f"标定 {data.calibration_id} 不存在")

    route = OutdoorRoute(
        name=data.name,
        description=data.description,
        calibration_id=data.calibration_id,
        version=1,
        fence_type=data.fence_type,
        fence_geojson=data.fence_geojson,
        fence_buffer_m=data.fence_buffer_m,
        max_speed_ms=data.max_speed_ms,
        applicable_device_types=data.applicable_device_types,
        status="draft",
    )
    db.add(route)
    db.flush()  # 拿到 route.id

    for i, wp_data in enumerate(data.waypoints, start=1):
        wp = OutdoorWaypoint(
            route_id=route.id,
            seq_order=wp_data.seq_order or i,
            name=wp_data.name,
            geo_lng=wp_data.geo_lng,
            geo_lat=wp_data.geo_lat,
            yaw=wp_data.yaw,
            arrival_radius_m=wp_data.arrival_radius_m,
            dwell_seconds=wp_data.dwell_seconds,
            action=wp_data.action,
            action_params=wp_data.action_params,
            timeout_seconds=wp_data.timeout_seconds,
            is_enabled=wp_data.is_enabled,
        )
        db.add(wp)
    db.flush()
    _compute_enu_for_waypoints(db, route, data.waypoints)
    db.commit()
    db.refresh(route)
    return _serialize_route(route, include_waypoints=True)


@router.get("/routes/{route_id}")
async def get_route(
    route_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取路线详情（含航点序列）"""
    route = db.query(OutdoorRoute).filter_by(id=route_id).first()
    if route is None:
        raise HTTPException(status_code=404, detail="路线不存在")
    return _serialize_route(route, include_waypoints=True)


@router.put("/routes/{route_id}")
async def update_route(
    route_id: int,
    data: OutdoorRouteUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新路线

    关键规则（FR-03.5）：
      - draft 状态可原地修改
      - published/frozen 状态修改会**创建新版本**（parent_id 指向原版本，新版本为 draft）
      - deprecated 状态禁止修改
    """
    route = db.query(OutdoorRoute).filter_by(id=route_id).first()
    if route is None:
        raise HTTPException(status_code=404, detail="路线不存在")
    if route.status == "deprecated":
        raise HTTPException(status_code=409, detail="deprecated 路线不可修改")

    needs_new_version = route.status in ("published", "frozen") and (
        data.name is not None or data.description is not None
        or data.fence_type is not None or data.fence_geojson is not None
        or data.fence_buffer_m is not None or data.max_speed_ms is not None
        or data.applicable_device_types is not None or data.waypoints is not None
    )

    if needs_new_version:
        # 创建新版本
        new_route = OutdoorRoute(
            name=data.name or route.name,
            description=data.description if data.description is not None else route.description,
            calibration_id=route.calibration_id,
            version=route.version + 1,
            parent_id=route.id,
            fence_type=data.fence_type or route.fence_type,
            fence_geojson=data.fence_geojson if data.fence_geojson is not None else route.fence_geojson,
            fence_buffer_m=data.fence_buffer_m if data.fence_buffer_m is not None else route.fence_buffer_m,
            max_speed_ms=data.max_speed_ms if data.max_speed_ms is not None else route.max_speed_ms,
            applicable_device_types=(
                data.applicable_device_types if data.applicable_device_types is not None
                else route.applicable_device_types
            ),
            status="draft",
        )
        db.add(new_route)
        db.flush()

        # 复制或更新航点
        if data.waypoints is not None:
            for i, wp_data in enumerate(data.waypoints, start=1):
                wp = OutdoorWaypoint(
                    route_id=new_route.id,
                    seq_order=wp_data.seq_order or i,
                    name=wp_data.name,
                    geo_lng=wp_data.geo_lng,
                    geo_lat=wp_data.geo_lat,
                    yaw=wp_data.yaw,
                    arrival_radius_m=wp_data.arrival_radius_m,
                    dwell_seconds=wp_data.dwell_seconds,
                    action=wp_data.action,
                    action_params=wp_data.action_params,
                    timeout_seconds=wp_data.timeout_seconds,
                    is_enabled=wp_data.is_enabled,
                )
                db.add(wp)
        else:
            # 复制原路线航点
            for wp in route.waypoints:
                new_wp = OutdoorWaypoint(
                    route_id=new_route.id,
                    seq_order=wp.seq_order,
                    name=wp.name,
                    geo_lng=wp.geo_lng,
                    geo_lat=wp.geo_lat,
                    enu_x=wp.enu_x,
                    enu_y=wp.enu_y,
                    yaw=wp.yaw,
                    arrival_radius_m=wp.arrival_radius_m,
                    dwell_seconds=wp.dwell_seconds,
                    action=wp.action,
                    action_params=wp.action_params,
                    timeout_seconds=wp.timeout_seconds,
                    is_enabled=wp.is_enabled,
                )
                db.add(new_wp)
        db.flush()
        _compute_enu_for_waypoints(db, new_route,
                                   [OutdoorWaypointCreate(**{
                                       "seq_order": w.seq_order,
                                       "name": w.name,
                                       "geo_lng": float(w.geo_lng),
                                       "geo_lat": float(w.geo_lat),
                                       "yaw": float(w.yaw) if w.yaw is not None else None,
                                       "arrival_radius_m": float(w.arrival_radius_m),
                                       "dwell_seconds": w.dwell_seconds,
                                       "action": w.action,
                                       "action_params": w.action_params,
                                       "timeout_seconds": w.timeout_seconds,
                                       "is_enabled": w.is_enabled,
                                   }) for w in new_route.waypoints])
        db.commit()
        db.refresh(new_route)
        return {
            "id": new_route.id,
            "version": new_route.version,
            "parent_id": new_route.parent_id,
            "status": new_route.status,
            "message": f"已基于 v{route.version} 创建新版本 v{new_route.version}",
        }

    # draft 状态原地修改
    for f in ("name", "description", "fence_type", "fence_geojson",
              "fence_buffer_m", "max_speed_ms", "applicable_device_types", "status"):
        v = getattr(data, f, None)
        if v is not None:
            setattr(route, f, v)

    if data.waypoints is not None:
        # 删除原航点，重建
        for wp in route.waypoints:
            db.delete(wp)
        db.flush()
        for i, wp_data in enumerate(data.waypoints, start=1):
            wp = OutdoorWaypoint(
                route_id=route.id,
                seq_order=wp_data.seq_order or i,
                name=wp_data.name,
                geo_lng=wp_data.geo_lng,
                geo_lat=wp_data.geo_lat,
                yaw=wp_data.yaw,
                arrival_radius_m=wp_data.arrival_radius_m,
                dwell_seconds=wp_data.dwell_seconds,
                action=wp_data.action,
                action_params=wp_data.action_params,
                timeout_seconds=wp_data.timeout_seconds,
                is_enabled=wp_data.is_enabled,
            )
            db.add(wp)
        db.flush()
        _compute_enu_for_waypoints(db, route, data.waypoints)

    db.commit()
    db.refresh(route)
    return {"id": route.id, "version": route.version, "status": route.status, "message": "更新成功"}


@router.post("/routes/{route_id}/publish")
async def publish_route(
    route_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """把 draft 路线发布为 published（FR-03.5）"""
    route = db.query(OutdoorRoute).filter_by(id=route_id).first()
    if route is None:
        raise HTTPException(status_code=404, detail="路线不存在")
    if route.status != "draft":
        raise HTTPException(status_code=409, detail=f"仅 draft 可发布，当前为 {route.status}")
    if not route.waypoints:
        raise HTTPException(status_code=422, detail="路线无航点，不可发布")
    route.status = "published"
    db.commit()
    return {"id": route.id, "status": route.status, "message": "已发布"}


@router.post("/routes/{route_id}/freeze")
async def freeze_route(
    route_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """把 published 路线冻结为 frozen（FR-03.5）

    冻结后任务启动时可锁定此版本，编辑会强制生成新版本。
    """
    route = db.query(OutdoorRoute).filter_by(id=route_id).first()
    if route is None:
        raise HTTPException(status_code=404, detail="路线不存在")
    if route.status != "published":
        raise HTTPException(status_code=409, detail=f"仅 published 可冻结，当前为 {route.status}")
    route.status = "frozen"
    db.commit()
    return {"id": route.id, "status": route.status, "message": "已冻结"}


@router.delete("/routes/{route_id}")
async def delete_route(
    route_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """软删除路线（转为 deprecated）"""
    route = db.query(OutdoorRoute).filter_by(id=route_id).first()
    if route is None:
        raise HTTPException(status_code=404, detail="路线不存在")
    if route.status == "deprecated":
        return {"id": route.id, "status": route.status, "message": "已经是 deprecated"}
    route.status = "deprecated"
    db.commit()
    return {"id": route.id, "status": route.status, "message": "已转为 deprecated"}


# ─────────────────────────────────────────────────────────────
# 任务 CRUD（最小骨架）
# ─────────────────────────────────────────────────────────────

@router.get("/tasks")
async def list_tasks(
    status: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出任务"""
    q = db.query(OutdoorPatrolTask)
    if status:
        q = q.filter_by(status=status)
    tasks = q.order_by(OutdoorPatrolTask.created_at.desc()).limit(min(limit, 500)).all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "route_id": t.route_id,
            "device_id": t.device_id,
            "schedule_type": t.schedule_type,
            "status": t.status,
            "current_waypoint_seq": t.current_waypoint_seq,
            "started_at": t.started_at.isoformat() if t.started_at else None,
            "ended_at": t.ended_at.isoformat() if t.ended_at else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in tasks
    ]


@router.post("/tasks")
async def create_task(
    data: OutdoorPatrolTaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建任务（FR-04.1）

    任务创建时不立刻冻结路线快照；启动预检通过后才在 start 阶段生成快照。
    """
    route = db.query(OutdoorRoute).filter_by(id=data.route_id).first()
    if route is None:
        raise HTTPException(status_code=404, detail="路线不存在")
    if route.status not in ("published", "frozen"):
        raise HTTPException(
            status_code=409,
            detail=f"路线状态为 {route.status}，需要 published 或 frozen 才能创建任务",
        )
    task = OutdoorPatrolTask(
        name=data.name,
        description=data.description,
        route_id=data.route_id,
        device_id=data.device_id,
        schedule_type=data.schedule_type,
        scheduled_at=data.scheduled_at,
        status="pending",
        created_by=current_user.id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return {
        "id": task.id,
        "name": task.name,
        "status": task.status,
        "message": "任务已创建为 pending；启动前需通过 POST /precheck",
    }
