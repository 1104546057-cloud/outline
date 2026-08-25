"""Pure RTK health and jump-detection logic (no ROS dependency)."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Optional


EARTH_RADIUS_M = 6378137.0


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return the great-circle distance in metres."""
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    d_lat = lat2_r - lat1_r
    d_lng = math.radians(lng2 - lng1)
    a = (
        math.sin(d_lat / 2.0) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(d_lng / 2.0) ** 2
    )
    return EARTH_RADIUS_M * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


@dataclass(frozen=True)
class RtkThresholds:
    stale_sec: float = 2.0
    gga_stale_sec: float = 2.0
    min_jump_m: float = 1.0
    max_jump_speed_mps: float = 3.0
    recovery_fixes: int = 3


class RtkHealthTracker:
    """Tracks G70 fixes; only NMEA quality 4 is accepted as RTK Fixed."""

    def __init__(self, thresholds: Optional[RtkThresholds] = None):
        self.thresholds = thresholds or RtkThresholds()
        self._lock = threading.Lock()
        self._raw_fix = None
        self._accepted_fix = None
        self._quality = None
        self._quality_time = 0.0
        self._jump_latched = False
        self._jump_distance_m = 0.0
        self._jump_speed_mps = 0.0
        self._recovery_count = 0

    def update_gga(self, quality: int, received_at: Optional[float] = None) -> None:
        with self._lock:
            self._quality = int(quality)
            self._quality_time = received_at if received_at is not None else time.time()

    def update_fix(
        self,
        latitude: float,
        longitude: float,
        altitude: float = 0.0,
        covariance_x: Optional[float] = None,
        covariance_y: Optional[float] = None,
        nav_status: Optional[int] = None,
        received_at: Optional[float] = None,
    ) -> bool:
        now = received_at if received_at is not None else time.time()
        latitude = float(latitude)
        longitude = float(longitude)
        if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
            raise ValueError("GNSS 经纬度超出合法范围")
        if not all(math.isfinite(value) for value in (latitude, longitude, altitude)):
            raise ValueError("GNSS 数据包含非有限数值")

        candidate = {
            "latitude": latitude,
            "longitude": longitude,
            "altitude": float(altitude),
            "covarianceX": covariance_x,
            "covarianceY": covariance_y,
            "navStatus": nav_status,
            "receivedAt": now,
        }
        with self._lock:
            self._raw_fix = candidate
            previous = self._accepted_fix
            is_jump = False
            if previous is not None:
                elapsed = now - previous["receivedAt"]
                if elapsed > 0.0:
                    distance = haversine_m(
                        previous["latitude"],
                        previous["longitude"],
                        latitude,
                        longitude,
                    )
                    speed = distance / elapsed
                    is_jump = (
                        distance >= self.thresholds.min_jump_m
                        and speed > self.thresholds.max_jump_speed_mps
                    )
                    self._jump_distance_m = distance
                    self._jump_speed_mps = speed
            if is_jump:
                self._jump_latched = True
                self._recovery_count = 0
                return False

            self._accepted_fix = candidate
            if self._jump_latched:
                self._recovery_count += 1
                if self._recovery_count >= self.thresholds.recovery_fixes:
                    self._jump_latched = False
                    self._jump_distance_m = 0.0
                    self._jump_speed_mps = 0.0
            return True

    def snapshot(self, now: Optional[float] = None) -> dict:
        current_time = now if now is not None else time.time()
        with self._lock:
            fix = dict(self._accepted_fix) if self._accepted_fix else None
            raw_fix = dict(self._raw_fix) if self._raw_fix else None
            quality = self._quality
            quality_time = self._quality_time
            jump_latched = self._jump_latched
            jump_distance = self._jump_distance_m
            jump_speed = self._jump_speed_mps
            recovery_count = self._recovery_count

        fix_age = current_time - fix["receivedAt"] if fix else None
        gga_age = current_time - quality_time if quality_time else None
        fresh = fix_age is not None and 0.0 <= fix_age <= self.thresholds.stale_sec
        quality_fresh = gga_age is not None and 0.0 <= gga_age <= self.thresholds.gga_stale_sec
        fixed = quality == 4 and quality_fresh
        valid = bool(fix and fresh and fixed and not jump_latched)

        if fix is None:
            error = "尚未收到 /gps/fix"
        elif not fresh:
            error = "GNSS 定位数据已过期"
        elif not quality_fresh:
            error = "尚未收到新鲜的 /gnss/gpgga 定位质量"
        elif quality != 4:
            error = "RTK 尚未达到 Fixed（gps_qual 必须为 4）"
        elif jump_latched:
            error = "检测到 GNSS 跳点，等待连续稳定数据恢复"
        else:
            error = ""

        return {
            "valid": valid,
            "fixed": fixed,
            "quality": quality,
            "qualityLabel": {
                0: "invalid",
                1: "single",
                2: "differential",
                4: "fixed",
                5: "float",
            }.get(quality, "unknown"),
            "fresh": fresh,
            "qualityFresh": quality_fresh,
            "fixAge": fix_age,
            "qualityAge": gga_age,
            "position": fix or {},
            "rawPosition": raw_fix or {},
            "jump": {
                "active": jump_latched,
                "distanceM": jump_distance,
                "speedMps": jump_speed,
                "recoveryCount": recovery_count,
                "recoveryRequired": self.thresholds.recovery_fixes,
            },
            "lastError": error,
        }
