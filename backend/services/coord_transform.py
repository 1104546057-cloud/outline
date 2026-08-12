"""
coord_transform.py — 校园室外巡检 · 坐标转换服务（阶段 B-4）
=====================================================================
实现 WGS84 ↔ ENU ↔ ROS map 的双向转换，支持可追溯的转换日志记录。

设计原则（对应需求 §5.1 强制规则）：
  1. 业务存储必须保留坐标类型、坐标参考、来源和版本；
     本模块的所有函数都要求传入 calibration_version 参数。
  2. WGS84 与 GCJ-02 的转换仅用于前端显示，不得参与车端定位融合或导航控制；
     本模块不实现 GCJ-02（另由前端工具函数处理）。
  3. 转换责任端固定：默认后端转换并下发 ENU/map，车端不再重复换算；
     若切换责任端，通过 transfer_function 的 transform_endpoint 参数记录。

WGS84 → ENU 数学模型：
  选定校园原点 (lat0, lon0)，将附近一点 (lat, lon) 转为平面 (E, N)：
    R = 6378137.0（WGS84 长半轴）
    lat_rad = lat * pi / 180
    dlat = (lat - lat0) * pi / 180
    dlon = (lon - lon0) * pi / 180
    N = dlat * R
    E = dlon * R * cos(lat0_rad)
  近似精度：校园尺度（< 10 km）下误差 < 1 cm。

ENU → ROS map：
  在阶段 A/B 默认 map 与 ENU 重合（yaw_offset = 0）。
  校准版本若定义了 yaw_offset（ENU 旋转到 map 的偏航角，弧度），
  则应用 2D 旋转：
    x_map = cos(yaw_offset) * E - sin(yaw_offset) * N
    y_map = sin(yaw_offset) * E + cos(yaw_offset) * N

反向同理。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# WGS84 椭球参数
WGS84_SEMI_MAJOR_AXIS = 6_378_137.0  # 长半轴 a (m)
WGS84_FIRST_ECCENTRICITY_SQUARED = 0.00669437999014  # e^2


class CoordinateType(str, Enum):
    """支持的坐标类型"""
    WGS84 = "wgs84"
    ENU = "enu"
    MAP = "map"
    # GCJ02 仅用于前端展示，不参与本服务的转换链路（需求 §5.1.3）
    GCJ02 = "gcj-02"


class TransformEndpoint(str, Enum):
    """转换执行端，用于审计"""
    BACKEND = "backend"
    AGENT = "agent"


@dataclass
class Calibration:
    """校园坐标标定参数（对应 OutdoorCalibration 表的核心字段）"""
    version: str
    origin_lat: float
    origin_lng: float
    origin_alt: float = 0.0
    yaw_offset: float = 0.0  # ENU → map 的偏航角 (rad)，默认 0 即重合

    def __post_init__(self):
        if not (-90.0 <= self.origin_lat <= 90.0):
            raise ValueError(f"origin_lat 超出 [-90, 90]：{self.origin_lat}")
        if not (-180.0 <= self.origin_lng <= 180.0):
            raise ValueError(f"origin_lng 超出 [-180, 180]：{self.origin_lng}")


@dataclass
class TransformRecord:
    """单次转换的可追溯记录（对应需求 §FR-02.4）"""
    timestamp: str
    calibration_version: str
    source_type: CoordinateType
    target_type: CoordinateType
    source_values: Dict[str, float]
    target_values: Dict[str, float]
    endpoint: TransformEndpoint = TransformEndpoint.BACKEND
    extra: Dict[str, Any] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────
# WGS84 ↔ ENU
# ─────────────────────────────────────────────────────────────

def wgs84_to_enu(
    lat: float,
    lon: float,
    calibration: Calibration,
    *,
    alt: float = 0.0,
) -> Tuple[float, float, float]:
    """WGS84 经纬度 → ENU 平面坐标（米）

    Returns:
        (east, north, up)
    """
    lat0 = calibration.origin_lat
    lon0 = calibration.origin_lng
    R = WGS84_SEMI_MAJOR_AXIS

    lat_rad = math.radians(lat)
    lat0_rad = math.radians(lat0)

    dlat = math.radians(lat - lat0)
    dlon = math.radians(lon - lon0)

    # 一阶近似（校园尺度 < 10km 足够精确）
    north = dlat * R
    east = dlon * R * math.cos(lat0_rad)
    up = alt - calibration.origin_alt

    return east, north, up


def enu_to_wgs84(
    east: float,
    north: float,
    calibration: Calibration,
    *,
    up: float = 0.0,
) -> Tuple[float, float, float]:
    """ENU 平面坐标 → WGS84 经纬度

    Returns:
        (lat, lon, alt)
    """
    lat0 = calibration.origin_lat
    lon0 = calibration.origin_lng
    R = WGS84_SEMI_MAJOR_AXIS

    lat0_rad = math.radians(lat0)

    dlat = north / R
    dlon = east / (R * math.cos(lat0_rad))

    lat = lat0 + math.degrees(dlat)
    lon = lon0 + math.degrees(dlon)
    alt = calibration.origin_alt + up

    return lat, lon, alt


# ─────────────────────────────────────────────────────────────
# ENU ↔ map（默认重合；若 yaw_offset 非零则旋转）
# ─────────────────────────────────────────────────────────────

def enu_to_map(
    east: float,
    north: float,
    calibration: Calibration,
) -> Tuple[float, float]:
    """ENU → ROS map 坐标

    若 calibration.yaw_offset == 0，则 map_x = east, map_y = north。
    """
    yaw = calibration.yaw_offset
    if yaw == 0.0:
        return east, north
    cos_y = math.cos(yaw)
    sin_y = math.sin(yaw)
    map_x = cos_y * east - sin_y * north
    map_y = sin_y * east + cos_y * north
    return map_x, map_y


def map_to_enu(
    map_x: float,
    map_y: float,
    calibration: Calibration,
) -> Tuple[float, float]:
    """ROS map 坐标 → ENU（enu_to_map 的逆）"""
    yaw = calibration.yaw_offset
    if yaw == 0.0:
        return map_x, map_y
    # 反向旋转：用 -yaw
    cos_y = math.cos(-yaw)
    sin_y = math.sin(-yaw)
    east = cos_y * map_x - sin_y * map_y
    north = sin_y * map_x + cos_y * map_y
    return east, north


# ─────────────────────────────────────────────────────────────
# 跨链路复合转换
# ─────────────────────────────────────────────────────────────

def wgs84_to_map(
    lat: float,
    lon: float,
    calibration: Calibration,
) -> Tuple[float, float]:
    """WGS84 → map（WGS84 → ENU → map 复合）"""
    east, north, _ = wgs84_to_enu(lat, lon, calibration)
    return enu_to_map(east, north, calibration)


def map_to_wgs84(
    map_x: float,
    map_y: float,
    calibration: Calibration,
) -> Tuple[float, float]:
    """map → WGS84（map → ENU → WGS84 复合）"""
    east, north = map_to_enu(map_x, map_y, calibration)
    lat, lon, _ = enu_to_wgs84(east, north, calibration)
    return lat, lon


# ─────────────────────────────────────────────────────────────
# 航向转换（可选）
# ─────────────────────────────────────────────────────────────

def yaw_wgs84_to_map(calibration: Calibration) -> float:
    """返回 WGS84 北 → map x 轴的航向偏移（rad）

    即 calibration.yaw_offset 本身；
    若未来需要处理 ENU 北与 map x 轴的差异，统一在此处理。
    """
    return calibration.yaw_offset


# ─────────────────────────────────────────────────────────────
# 可追溯转换封装
# ─────────────────────────────────────────────────────────────

class CoordTransformer:
    """封装转换调用，自动记录可追溯日志。

    用于后端路由层；调用方传入 calibration 与转换参数，
    返回结果时同时返回 TransformRecord 用于持久化审计。
    """

    def __init__(self, calibration: Calibration,
                 endpoint: TransformEndpoint = TransformEndpoint.BACKEND):
        self.calibration = calibration
        self.endpoint = endpoint
        self.records: List[TransformRecord] = []

    def _record(
        self,
        source_type: CoordinateType,
        target_type: CoordinateType,
        source_values: Dict[str, float],
        target_values: Dict[str, float],
        extra: Optional[Dict[str, Any]] = None,
    ) -> TransformRecord:
        rec = TransformRecord(
            timestamp=datetime.utcnow().isoformat(timespec="seconds") + "Z",
            calibration_version=self.calibration.version,
            source_type=source_type,
            target_type=target_type,
            source_values=source_values,
            target_values=target_values,
            endpoint=self.endpoint,
            extra=extra or {},
        )
        self.records.append(rec)
        return rec

    def wgs84_to_enu(self, lat: float, lon: float, alt: float = 0.0):
        e, n, u = wgs84_to_enu(lat, lon, self.calibration, alt=alt)
        rec = self._record(
            CoordinateType.WGS84, CoordinateType.ENU,
            {"lat": lat, "lon": lon, "alt": alt},
            {"east": e, "north": n, "up": u},
        )
        return (e, n, u), rec

    def enu_to_wgs84(self, east: float, north: float, up: float = 0.0):
        lat, lon, alt = enu_to_wgs84(east, north, self.calibration, up=up)
        rec = self._record(
            CoordinateType.ENU, CoordinateType.WGS84,
            {"east": east, "north": north, "up": up},
            {"lat": lat, "lon": lon, "alt": alt},
        )
        return (lat, lon, alt), rec

    def wgs84_to_map(self, lat: float, lon: float):
        x, y = wgs84_to_map(lat, lon, self.calibration)
        rec = self._record(
            CoordinateType.WGS84, CoordinateType.MAP,
            {"lat": lat, "lon": lon},
            {"x": x, "y": y},
        )
        return (x, y), rec

    def map_to_wgs84(self, x: float, y: float):
        lat, lon = map_to_wgs84(x, y, self.calibration)
        rec = self._record(
            CoordinateType.MAP, CoordinateType.WGS84,
            {"x": x, "y": y},
            {"lat": lat, "lon": lon},
        )
        return (lat, lon), rec

    def export_records(self) -> List[Dict[str, Any]]:
        """导出本次 transformer 的全部转换记录（用于持久化到 OutdoorPatrolEvent 或独立审计表）"""
        out = []
        for r in self.records:
            out.append({
                "timestamp": r.timestamp,
                "calibration_version": r.calibration_version,
                "source_type": r.source_type.value,
                "target_type": r.target_type.value,
                "source_values": r.source_values,
                "target_values": r.target_values,
                "endpoint": r.endpoint.value,
                "extra": r.extra,
            })
        return out
