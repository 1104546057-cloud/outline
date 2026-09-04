import math
import threading
import time
from typing import Callable, Dict, List, Optional


EARTH_RADIUS_M = 6378137.0
SUCCESS_LABELS = {"SUCCEEDED"}
FAILURE_LABELS = {"ABORTED", "REJECTED", "RECALLED", "LOST"}


def haversine_m(first: dict, second: dict) -> float:
    lat1 = math.radians(float(first["latitude"]))
    lat2 = math.radians(float(second["latitude"]))
    delta_lat = lat2 - lat1
    delta_lng = math.radians(float(second["longitude"]) - float(first["longitude"]))
    value = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2.0) ** 2
    )
    return EARTH_RADIUS_M * 2.0 * math.atan2(math.sqrt(value), math.sqrt(1.0 - value))


def route_yaw(point: dict, next_point: dict) -> float:
    mean_latitude = math.radians((float(point["latitude"]) + float(next_point["latitude"])) / 2.0)
    east = (float(next_point["longitude"]) - float(point["longitude"])) * math.cos(mean_latitude)
    north = float(next_point["latitude"]) - float(point["latitude"])
    return math.atan2(north, east)


def angle_difference(first: float, second: float) -> float:
    return abs((second - first + math.pi) % (2.0 * math.pi) - math.pi)


def route_turn_angle_deg(points: List[dict], index: int, window_m: float = 0.75) -> float:
    if index <= 0 or index >= len(points) - 1:
        return 0.0
    window = max(0.1, float(window_m))
    before = index - 1
    while before > 0 and haversine_m(points[before], points[index]) < window:
        before -= 1
    after = index + 1
    while after < len(points) - 1 and haversine_m(points[index], points[after]) < window:
        after += 1
    incoming = route_yaw(points[before], points[index])
    outgoing = route_yaw(points[index], points[after])
    return math.degrees(angle_difference(incoming, outgoing))


def sample_route_points(
    points: List[dict],
    straight_spacing_m: float = 3.0,
    turn_spacing_m: float = 1.0,
    turn_threshold_deg: float = 12.0,
    turn_window_m: float = 0.75,
) -> List[dict]:
    if not points:
        return []
    if len(points) == 1:
        return [dict(points[0])]
    straight_spacing = max(0.1, float(straight_spacing_m))
    turn_spacing = min(straight_spacing, max(0.1, float(turn_spacing_m)))
    threshold = max(0.0, float(turn_threshold_deg))
    sampled = [dict(points[0])]
    for index, point in enumerate(points[1:-1], start=1):
        turning = route_turn_angle_deg(points, index, turn_window_m) >= threshold
        required_spacing = turn_spacing if turning else straight_spacing
        if haversine_m(sampled[-1], point) >= required_spacing:
            sampled.append(dict(point))
    if haversine_m(sampled[-1], points[-1]) > 0.01:
        sampled.append(dict(points[-1]))
    return sampled


def distance_to_route_m(position: dict, route: List[dict]) -> float:
    if not route:
        return float("inf")
    latitude = float(position["latitude"])
    longitude = float(position["longitude"])
    cosine = max(0.01, math.cos(math.radians(latitude)))

    def local_xy(point: dict):
        return (
            EARTH_RADIUS_M * math.radians(float(point["longitude"]) - longitude) * cosine,
            EARTH_RADIUS_M * math.radians(float(point["latitude"]) - latitude),
        )

    if len(route) == 1:
        return math.hypot(*local_xy(route[0]))
    best = float("inf")
    for first, second in zip(route, route[1:]):
        ax, ay = local_xy(first)
        bx, by = local_xy(second)
        dx = bx - ax
        dy = by - ay
        length_sq = dx * dx + dy * dy
        if length_sq <= 1e-9:
            distance = math.hypot(ax, ay)
        else:
            projection = max(0.0, min(1.0, -(ax * dx + ay * dy) / length_sq))
            distance = math.hypot(ax + projection * dx, ay + projection * dy)
        best = min(best, distance)
    return best


class RtkRouteExecutor:
    def __init__(
        self,
        send_goal: Callable[[float, float, float], dict],
        read_goal_status: Callable[[], dict],
        read_health: Callable[[], dict],
        cancel_goal: Callable[[], None],
        hard_stop: Callable[[], None],
        straight_spacing_m: float = 3.0,
        turn_spacing_m: float = 1.0,
        turn_threshold_deg: float = 12.0,
        turn_window_m: float = 0.75,
        max_cross_track_error_m: float = 1.2,
        deviation_grace_sec: float = 1.0,
        start_skip_distance_m: float = 1.0,
        waypoint_timeout_sec: float = 45.0,
        poll_interval_sec: float = 0.1,
        waypoint_spacing_m: Optional[float] = None,
    ):
        self._send_goal = send_goal
        self._read_goal_status = read_goal_status
        self._read_health = read_health
        self._cancel_goal = cancel_goal
        self._hard_stop = hard_stop
        if waypoint_spacing_m is not None:
            straight_spacing_m = waypoint_spacing_m
            turn_spacing_m = waypoint_spacing_m
        self._straight_spacing_m = max(0.1, float(straight_spacing_m))
        self._turn_spacing_m = min(
            self._straight_spacing_m,
            max(0.1, float(turn_spacing_m)),
        )
        self._turn_threshold_deg = max(0.0, float(turn_threshold_deg))
        self._turn_window_m = max(0.1, float(turn_window_m))
        self._max_cross_track_error_m = max(0.1, float(max_cross_track_error_m))
        self._deviation_grace_sec = max(0.0, float(deviation_grace_sec))
        self._start_skip_distance_m = max(0.0, float(start_skip_distance_m))
        self._waypoint_timeout_sec = max(1.0, float(waypoint_timeout_sec))
        self._poll_interval_sec = max(0.01, float(poll_interval_sec))
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()
        self._failure_reason = ""
        self._state = self._idle_state()

    @staticmethod
    def _idle_state() -> dict:
        return {
            "active": False,
            "paused": False,
            "state": "idle",
            "networkId": None,
            "distanceM": 0.0,
            "originalPointCount": 0,
            "pointCount": 0,
            "currentIndex": 0,
            "completedPoints": 0,
            "progressPct": 0.0,
            "currentGoal": None,
            "crossTrackErrorM": None,
            "maxCrossTrackErrorM": 0.0,
            "deviationLimitM": None,
            "startedAt": None,
            "updatedAt": time.time(),
            "finishedAt": None,
            "error": "",
        }

    def status(self) -> dict:
        with self._lock:
            return dict(self._state)

    def start(self, plan: dict) -> dict:
        path = list(plan.get("path") or [])
        if len(path) < 2:
            raise ValueError("规划路径有效节点少于2个")
        points = sample_route_points(
            path,
            self._straight_spacing_m,
            self._turn_spacing_m,
            self._turn_threshold_deg,
            self._turn_window_m,
        )
        health = self._read_health() or {}
        start_position = health.get("position") or {}
        reference_route = [dict(point) for point in path]
        if "longitude" in start_position and "latitude" in start_position:
            start_point = {
                "longitude": float(start_position["longitude"]),
                "latitude": float(start_position["latitude"]),
            }
            if haversine_m(start_point, reference_route[0]) > 0.01:
                reference_route.insert(0, start_point)
            while len(points) > 1 and haversine_m(start_point, points[0]) <= self._start_skip_distance_m:
                points.pop(0)
        if not points:
            raise ValueError("路线压缩后没有可执行节点")
        with self._lock:
            if self._state.get("active"):
                raise RuntimeError("已有自动驾驶路线正在执行")
            self._cancel_event = threading.Event()
            self._pause_event = threading.Event()
            self._failure_reason = ""
            now = time.time()
            self._state = {
                "active": True,
                "paused": False,
                "state": "starting",
                "networkId": plan.get("networkId"),
                "distanceM": float(plan.get("distanceM") or 0.0),
                "originalPointCount": len(path),
                "pointCount": len(points),
                "currentIndex": 0,
                "completedPoints": 0,
                "progressPct": 0.0,
                "currentGoal": None,
                "crossTrackErrorM": 0.0,
                "maxCrossTrackErrorM": 0.0,
                "deviationLimitM": self._max_cross_track_error_m,
                "startedAt": now,
                "updatedAt": now,
                "finishedAt": None,
                "error": "",
            }
            thread = threading.Thread(
                target=self._run,
                args=(points, reference_route),
                name="rtk-route-executor",
                daemon=True,
            )
            self._thread = thread
            thread.start()
        return self.status()

    def pause(self) -> dict:
        with self._lock:
            if not self._state.get("active"):
                raise RuntimeError("当前没有正在执行的自动驾驶路线")
            if self._state.get("paused"):
                return dict(self._state)
            self._pause_event.set()
            self._state.update({"paused": True, "state": "paused", "updatedAt": time.time()})
        self._cancel_goal()
        self._hard_stop()
        return self.status()

    def resume(self) -> dict:
        with self._lock:
            if not self._state.get("active"):
                raise RuntimeError("当前没有可继续的自动驾驶路线")
            if not self._state.get("paused"):
                return dict(self._state)
            self._pause_event.clear()
            self._state.update({"paused": False, "state": "driving", "updatedAt": time.time()})
        return self.status()

    def stop(self, reason: str = "人工停止") -> dict:
        with self._lock:
            active = bool(self._state.get("active"))
            if active:
                self._cancel_event.set()
                self._state.update({"state": "stopping", "updatedAt": time.time(), "error": reason})
        self._cancel_goal()
        self._hard_stop()
        if not active:
            with self._lock:
                self._state.update({
                    "active": False,
                    "paused": False,
                    "state": "stopped",
                    "updatedAt": time.time(),
                    "finishedAt": time.time(),
                    "error": reason,
                })
        return self.status()

    def emergency_stop(self, reason: str) -> dict:
        with self._lock:
            self._failure_reason = str(reason or "安全门触发停车")
            self._cancel_event.set()
            self._state.update({
                "state": "failed",
                "error": self._failure_reason,
                "updatedAt": time.time(),
            })
        self._cancel_goal()
        self._hard_stop()
        return self.status()

    def _update(self, **changes) -> None:
        changes["updatedAt"] = time.time()
        with self._lock:
            self._state.update(changes)

    def _finish(self, state: str, error: str = "") -> None:
        now = time.time()
        with self._lock:
            self._state.update({
                "active": False,
                "paused": False,
                "state": state,
                "updatedAt": now,
                "finishedAt": now,
                "error": error,
            })

    def _wait_while_paused(self) -> bool:
        while self._pause_event.is_set() and not self._cancel_event.is_set():
            time.sleep(self._poll_interval_sec)
        return not self._cancel_event.is_set()

    def _run(self, points: List[dict], reference_route: List[dict]) -> None:
        try:
            index = 0
            deviation_since = None
            while index < len(points):
                if self._cancel_event.is_set():
                    break
                if not self._wait_while_paused():
                    break
                point = points[index]
                if index + 1 < len(points):
                    yaw = route_yaw(point, points[index + 1])
                else:
                    yaw = route_yaw(points[index - 1], point)
                self._send_goal(float(point["longitude"]), float(point["latitude"]), yaw)
                self._update(
                    state="driving",
                    currentIndex=index,
                    currentGoal={
                        "longitude": float(point["longitude"]),
                        "latitude": float(point["latitude"]),
                    },
                )
                sent_at = time.monotonic()
                resend_current = False
                while True:
                    if self._cancel_event.is_set():
                        break
                    if self._pause_event.is_set():
                        self._cancel_goal()
                        self._hard_stop()
                        self._update(paused=True, state="paused")
                        if not self._wait_while_paused():
                            break
                        self._update(paused=False, state="driving")
                        resend_current = True
                        break
                    health = self._read_health() or {}
                    if not health.get("valid"):
                        raise RuntimeError(
                            "RTK定位失效: " + str(health.get("lastError") or "等待Fixed")
                        )
                    position = health.get("position") or {}
                    if "longitude" in position and "latitude" in position:
                        cross_track = distance_to_route_m(position, reference_route)
                        current_max = float(self.status().get("maxCrossTrackErrorM") or 0.0)
                        self._update(
                            crossTrackErrorM=round(cross_track, 3),
                            maxCrossTrackErrorM=round(max(current_max, cross_track), 3),
                        )
                        if cross_track > self._max_cross_track_error_m:
                            if deviation_since is None:
                                deviation_since = time.monotonic()
                            if time.monotonic() - deviation_since >= self._deviation_grace_sec:
                                raise RuntimeError(
                                    "路线横向偏离 %.2f 米，超过安全上限 %.2f 米"
                                    % (cross_track, self._max_cross_track_error_m)
                                )
                        else:
                            deviation_since = None
                    goal_status = self._read_goal_status() or {}
                    label = str(goal_status.get("label") or "").upper()
                    if label in SUCCESS_LABELS:
                        index += 1
                        completed = index
                        self._update(
                            completedPoints=completed,
                            progressPct=round(completed * 100.0 / len(points), 1),
                        )
                        break
                    if label in FAILURE_LABELS:
                        raise RuntimeError(
                            "导航节点执行失败: " + str(goal_status.get("text") or label)
                        )
                    if time.monotonic() - sent_at > self._waypoint_timeout_sec:
                        raise RuntimeError("导航节点执行超时")
                    time.sleep(self._poll_interval_sec)
                if self._cancel_event.is_set():
                    break
                if resend_current:
                    continue
            if self._cancel_event.is_set():
                reason = self._failure_reason
                self._finish("failed" if reason else "stopped", reason or "人工停止")
            else:
                self._hard_stop()
                self._finish("completed")
        except Exception as exc:
            self._cancel_goal()
            self._hard_stop()
            self._finish("failed", str(exc))
