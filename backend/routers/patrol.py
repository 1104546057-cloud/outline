"""
巡检系统路由

提供巡检区域、巡检点位、巡检线路、巡检任务的完整 CRUD 和任务控制接口。
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import (
    User, Device,
    PatrolArea, PatrolPoint, PatrolRoute, PatrolRoutePoint, PatrolTask,
)
from schemas import (
    PatrolAreaCreate, PatrolAreaUpdate,
    PatrolPointCreate, PatrolPointUpdate,
    PatrolRouteCreate, PatrolRouteUpdate,
    PatrolTaskCreate, PatrolTrackAppend,
)
from auth import get_current_user

router = APIRouter(prefix="/api/patrol", tags=["巡检系统"])


# ===== 巡检区域 API =====

@router.get("/areas")
async def list_patrol_areas(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取所有巡检区域列表"""
    areas = db.query(PatrolArea).order_by(PatrolArea.id.asc()).all()
    result = []
    for a in areas:
        result.append({
            "id": a.id,
            "name": a.name,
            "description": a.description,
            "manager": a.manager,
            "boundary": a.boundary,
            "center_lng": float(a.center_lng) if a.center_lng else None,
            "center_lat": float(a.center_lat) if a.center_lat else None,
            "area_sqm": a.area_sqm,
            "point_count": len(a.points),
            "route_count": len(a.routes),
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "updated_at": a.updated_at.isoformat() if a.updated_at else None,
        })
    return result


@router.post("/areas")
async def create_patrol_area(
    data: PatrolAreaCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建巡检区域"""
    area = PatrolArea(
        name=data.name,
        description=data.description,
        manager=data.manager,
        boundary=data.boundary,
        center_lng=data.center_lng,
        center_lat=data.center_lat,
        area_sqm=data.area_sqm,
    )
    db.add(area)
    db.commit()
    db.refresh(area)
    return {
        "id": area.id,
        "name": area.name,
        "description": area.description,
        "manager": area.manager,
        "boundary": area.boundary,
        "center_lng": float(area.center_lng) if area.center_lng else None,
        "center_lat": float(area.center_lat) if area.center_lat else None,
        "area_sqm": area.area_sqm,
        "point_count": 0,
        "route_count": 0,
        "created_at": area.created_at.isoformat() if area.created_at else None,
        "updated_at": area.updated_at.isoformat() if area.updated_at else None,
    }


@router.put("/areas/{area_id}")
async def update_patrol_area(
    area_id: int,
    data: PatrolAreaUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新巡检区域"""
    area = db.query(PatrolArea).filter(PatrolArea.id == area_id).first()
    if not area:
        raise HTTPException(status_code=404, detail="巡检区域不存在")
    if data.name is not None:
        area.name = data.name
    if data.description is not None:
        area.description = data.description
    if data.manager is not None:
        area.manager = data.manager
    if data.boundary is not None:
        area.boundary = data.boundary
    if data.center_lng is not None:
        area.center_lng = data.center_lng
    if data.center_lat is not None:
        area.center_lat = data.center_lat
    if data.area_sqm is not None:
        area.area_sqm = data.area_sqm
    db.commit()
    db.refresh(area)
    return {
        "id": area.id,
        "name": area.name,
        "description": area.description,
        "manager": area.manager,
        "boundary": area.boundary,
        "center_lng": float(area.center_lng) if area.center_lng else None,
        "center_lat": float(area.center_lat) if area.center_lat else None,
        "area_sqm": area.area_sqm,
        "point_count": len(area.points),
        "route_count": len(area.routes),
        "created_at": area.created_at.isoformat() if area.created_at else None,
        "updated_at": area.updated_at.isoformat() if area.updated_at else None,
    }


@router.delete("/areas/{area_id}")
async def delete_patrol_area(
    area_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除巡检区域（级联删除点位和线路）"""
    area = db.query(PatrolArea).filter(PatrolArea.id == area_id).first()
    if not area:
        raise HTTPException(status_code=404, detail="巡检区域不存在")
    db.delete(area)
    db.commit()
    return {"message": f"巡检区域 {area.name} 已删除"}


# ===== 巡检点位 API =====

@router.get("/points")
async def list_patrol_points(
    area_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取巡检点位列表（可按区域筛选）"""
    query = db.query(PatrolPoint)
    if area_id is not None:
        query = query.filter(PatrolPoint.area_id == area_id)
    points = query.order_by(PatrolPoint.id.asc()).all()
    return [{
        "id": p.id,
        "area_id": p.area_id,
        "name": p.name,
        "description": p.description,
        "lng": float(p.lng) if p.lng else None,
        "lat": float(p.lat) if p.lat else None,
        "address": p.address,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    } for p in points]


@router.post("/points")
async def create_patrol_point(
    data: PatrolPointCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建巡检点位"""
    area = db.query(PatrolArea).filter(PatrolArea.id == data.area_id).first()
    if not area:
        raise HTTPException(status_code=404, detail="巡检区域不存在")
    point = PatrolPoint(
        area_id=data.area_id,
        name=data.name,
        description=data.description,
        lng=data.lng,
        lat=data.lat,
        address=data.address,
    )
    db.add(point)
    db.commit()
    db.refresh(point)
    return {
        "id": point.id,
        "area_id": point.area_id,
        "name": point.name,
        "description": point.description,
        "lng": float(point.lng) if point.lng else None,
        "lat": float(point.lat) if point.lat else None,
        "address": point.address,
        "created_at": point.created_at.isoformat() if point.created_at else None,
        "updated_at": point.updated_at.isoformat() if point.updated_at else None,
    }


@router.put("/points/{point_id}")
async def update_patrol_point(
    point_id: int,
    data: PatrolPointUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新巡检点位"""
    point = db.query(PatrolPoint).filter(PatrolPoint.id == point_id).first()
    if not point:
        raise HTTPException(status_code=404, detail="巡检点位不存在")
    if data.name is not None:
        point.name = data.name
    if data.description is not None:
        point.description = data.description
    if data.address is not None:
        point.address = data.address
    db.commit()
    db.refresh(point)
    return {
        "id": point.id,
        "area_id": point.area_id,
        "name": point.name,
        "description": point.description,
        "lng": float(point.lng) if point.lng else None,
        "lat": float(point.lat) if point.lat else None,
        "address": point.address,
        "created_at": point.created_at.isoformat() if point.created_at else None,
        "updated_at": point.updated_at.isoformat() if point.updated_at else None,
    }


@router.delete("/points/{point_id}")
async def delete_patrol_point(
    point_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除巡检点位"""
    point = db.query(PatrolPoint).filter(PatrolPoint.id == point_id).first()
    if not point:
        raise HTTPException(status_code=404, detail="巡检点位不存在")
    db.delete(point)
    db.commit()
    return {"message": f"巡检点位 {point.name} 已删除"}


# ===== 巡检线路 API =====

@router.get("/routes")
async def list_patrol_routes(
    area_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取巡检线路列表（可按区域筛选）"""
    query = db.query(PatrolRoute)
    if area_id is not None:
        query = query.filter(PatrolRoute.area_id == area_id)
    routes = query.order_by(PatrolRoute.id.asc()).all()
    result = []
    for r in routes:
        pts = sorted(r.route_points, key=lambda x: x.seq_order)
        result.append({
            "id": r.id,
            "area_id": r.area_id,
            "name": r.name,
            "description": r.description,
            "distance": r.distance,
            "point_count": len(pts),
            "points": [{
                "id": rp.point.id,
                "name": rp.point.name,
                "lng": float(rp.point.lng),
                "lat": float(rp.point.lat),
                "address": rp.point.address,
                "seq_order": rp.seq_order,
            } for rp in pts],
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        })
    return result


@router.get("/routes/{route_id}")
async def get_patrol_route(
    route_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取巡检线路详情（含点位列表）"""
    r = db.query(PatrolRoute).filter(PatrolRoute.id == route_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="巡检线路不存在")
    pts = sorted(r.route_points, key=lambda x: x.seq_order)
    return {
        "id": r.id,
        "area_id": r.area_id,
        "name": r.name,
        "description": r.description,
        "distance": r.distance,
        "points": [{
            "id": rp.point.id,
            "name": rp.point.name,
            "lng": float(rp.point.lng),
            "lat": float(rp.point.lat),
            "address": rp.point.address,
            "seq_order": rp.seq_order,
        } for rp in pts],
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


@router.post("/routes")
async def create_patrol_route(
    data: PatrolRouteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建巡检线路（含点位顺序）"""
    area = db.query(PatrolArea).filter(PatrolArea.id == data.area_id).first()
    if not area:
        raise HTTPException(status_code=404, detail="巡检区域不存在")
    route = PatrolRoute(
        area_id=data.area_id,
        name=data.name,
        description=data.description,
        distance=data.distance,
    )
    db.add(route)
    db.flush()  # 获取 route.id
    for i, pid in enumerate(data.point_ids):
        rp = PatrolRoutePoint(route_id=route.id, point_id=pid, seq_order=i + 1)
        db.add(rp)
    db.commit()
    db.refresh(route)
    pts = sorted(route.route_points, key=lambda x: x.seq_order)
    return {
        "id": route.id,
        "area_id": route.area_id,
        "name": route.name,
        "description": route.description,
        "distance": route.distance,
        "points": [{
            "id": rp.point.id,
            "name": rp.point.name,
            "lng": float(rp.point.lng),
            "lat": float(rp.point.lat),
            "address": rp.point.address,
            "seq_order": rp.seq_order,
        } for rp in pts],
        "created_at": route.created_at.isoformat() if route.created_at else None,
        "updated_at": route.updated_at.isoformat() if route.updated_at else None,
    }


@router.put("/routes/{route_id}")
async def update_patrol_route(
    route_id: int,
    data: PatrolRouteUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新巡检线路"""
    route = db.query(PatrolRoute).filter(PatrolRoute.id == route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail="巡检线路不存在")
    if data.name is not None:
        route.name = data.name
    if data.description is not None:
        route.description = data.description
    if data.distance is not None:
        route.distance = data.distance
    if data.point_ids is not None:
        # 重置点位关联
        db.query(PatrolRoutePoint).filter(PatrolRoutePoint.route_id == route_id).delete()
        for i, pid in enumerate(data.point_ids):
            rp = PatrolRoutePoint(route_id=route.id, point_id=pid, seq_order=i + 1)
            db.add(rp)
    db.commit()
    db.refresh(route)
    pts = sorted(route.route_points, key=lambda x: x.seq_order)
    return {
        "id": route.id,
        "area_id": route.area_id,
        "name": route.name,
        "description": route.description,
        "distance": route.distance,
        "points": [{
            "id": rp.point.id,
            "name": rp.point.name,
            "lng": float(rp.point.lng),
            "lat": float(rp.point.lat),
            "address": rp.point.address,
            "seq_order": rp.seq_order,
        } for rp in pts],
        "created_at": route.created_at.isoformat() if route.created_at else None,
        "updated_at": route.updated_at.isoformat() if route.updated_at else None,
    }


@router.delete("/routes/{route_id}")
async def delete_patrol_route(
    route_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除巡检线路"""
    route = db.query(PatrolRoute).filter(PatrolRoute.id == route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail="巡检线路不存在")
    db.delete(route)
    db.commit()
    return {"message": f"巡检线路 {route.name} 已删除"}


# ===== 巡检任务 API =====

@router.get("/tasks")
async def list_patrol_tasks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取所有巡检任务列表"""
    tasks = db.query(PatrolTask).order_by(PatrolTask.id.desc()).all()
    result = []
    for t in tasks:
        result.append({
            "id": t.id,
            "name": t.name,
            "status": t.status,
            "route_id": t.route_id,
            "route_name": t.route.name if t.route else None,
            "area_name": t.route.area.name if t.route and t.route.area else None,
            "point_count": len(t.route.route_points) if t.route else 0,
            "route_distance": t.route.distance if t.route else None,
            "device_id": t.device_id,
            "device_name": t.device.name if t.device else None,
            "gps_track": t.gps_track,
            "started_at": t.started_at.isoformat() if t.started_at else None,
            "ended_at": t.ended_at.isoformat() if t.ended_at else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        })
    return result


@router.get("/tasks/{task_id}")
async def get_patrol_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取巡检任务详情（含GPS轨迹和线路信息）"""
    t = db.query(PatrolTask).filter(PatrolTask.id == task_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="巡检任务不存在")
    route_data = None
    if t.route:
        pts = sorted(t.route.route_points, key=lambda x: x.seq_order)
        route_data = {
            "id": t.route.id,
            "name": t.route.name,
            "area_id": t.route.area_id,
            "area_name": t.route.area.name if t.route.area else None,
            "distance": t.route.distance,
            "points": [{
                "id": rp.point.id,
                "name": rp.point.name,
                "lng": float(rp.point.lng),
                "lat": float(rp.point.lat),
                "seq_order": rp.seq_order,
            } for rp in pts],
        }
    return {
        "id": t.id,
        "name": t.name,
        "status": t.status,
        "route_id": t.route_id,
        "route": route_data,
        "device_id": t.device_id,
        "device_name": t.device.name if t.device else None,
        "device_ip": t.device.ip_address if t.device else None,
        "device_port": t.device.port if t.device else None,
        "gps_track": t.gps_track or [],
        "started_at": t.started_at.isoformat() if t.started_at else None,
        "ended_at": t.ended_at.isoformat() if t.ended_at else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


@router.post("/tasks")
async def create_patrol_task(
    data: PatrolTaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建巡检任务"""
    route = db.query(PatrolRoute).filter(PatrolRoute.id == data.route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail="巡检线路不存在")
    if data.device_id:
        device = db.query(Device).filter(Device.id == data.device_id).first()
        if not device:
            raise HTTPException(status_code=404, detail="设备不存在")
    task = PatrolTask(
        route_id=data.route_id,
        device_id=data.device_id,
        name=data.name,
        status="pending",
        gps_track=[],
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return {
        "id": task.id,
        "name": task.name,
        "status": task.status,
        "route_id": task.route_id,
        "device_id": task.device_id,
        "gps_track": task.gps_track,
        "started_at": None,
        "ended_at": None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


@router.put("/tasks/{task_id}/start")
async def start_patrol_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """开始巡检任务（开始记录GPS轨迹）"""
    task = db.query(PatrolTask).filter(PatrolTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="巡检任务不存在")
    if task.status == "running":
        raise HTTPException(status_code=400, detail="任务已在运行中")
    task.status = "running"
    task.started_at = datetime.now()
    task.ended_at = None
    task.gps_track = []
    db.commit()
    return {"message": "任务已开始", "status": "running"}


@router.put("/tasks/{task_id}/pause")
async def pause_patrol_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """暂停巡检任务"""
    task = db.query(PatrolTask).filter(PatrolTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="巡检任务不存在")
    if task.status != "running":
        raise HTTPException(status_code=400, detail="只有运行中的任务才能暂停")
    task.status = "paused"
    db.commit()
    return {"message": "任务已暂停", "status": "paused"}


@router.put("/tasks/{task_id}/resume")
async def resume_patrol_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """恢复巡检任务"""
    task = db.query(PatrolTask).filter(PatrolTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="巡检任务不存在")
    if task.status != "paused":
        raise HTTPException(status_code=400, detail="只有暂停中的任务才能恢复")
    task.status = "running"
    db.commit()
    return {"message": "任务已恢复", "status": "running"}


@router.put("/tasks/{task_id}/stop")
async def stop_patrol_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """停止巡检任务（结束GPS记录）"""
    task = db.query(PatrolTask).filter(PatrolTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="巡检任务不存在")
    if task.status in ("completed", "cancelled"):
        raise HTTPException(status_code=400, detail="任务已结束")
    task.status = "completed"
    task.ended_at = datetime.now()
    db.commit()
    return {"message": "任务已停止", "status": "completed"}


@router.put("/tasks/{task_id}/track")
async def append_gps_track(
    task_id: int,
    data: PatrolTrackAppend,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """追加GPS轨迹点（仅running状态可追加）"""
    task = db.query(PatrolTask).filter(PatrolTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="巡检任务不存在")
    if task.status != "running":
        raise HTTPException(status_code=400, detail="只有运行中的任务才能追加GPS轨迹")
    current_track = list(task.gps_track or [])  # 必须用 list() 创建新列表，否则 SQLAlchemy 检测不到 JSON 字段变更
    current_track.extend(data.points)
    task.gps_track = current_track
    db.commit()
    return {"message": f"已追加 {len(data.points)} 个轨迹点", "total": len(current_track)}


@router.delete("/tasks/{task_id}")
async def delete_patrol_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除巡检任务"""
    task = db.query(PatrolTask).filter(PatrolTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="巡检任务不存在")
    if task.status == "running":
        raise HTTPException(status_code=400, detail="任务运行中，请先停止任务后再删除")
    db.delete(task)
    db.commit()
    return {"message": f"巡检任务 {task.name} 已删除"}
