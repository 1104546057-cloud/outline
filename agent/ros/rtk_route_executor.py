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


def sample_route_points(points: List[dict], spacing_m: float) -> List[dict]:
    if not points:
        return []
    if len(points) == 1:
        return [dict(points[0])]
    spacing = max(0.1, float(spacing_m))
    sampled = [dict(points[0])]
    for point in points[1:-1]:
        if haversine_m(sampled[-1], point) >= spacing:
            sampled.append(dict(point))
    if haversine_m(sampled[-1], points[-1]) > 0.01:
        sampled.append(dict(points[-1]))
    return sampled


class RtkRouteExecutor:
    def __init__(
        self,
        send_goal: Callable[[float, float, float], dict],
        read_goal_status: Callable[[], dict],
        read_health: Callable[[], dict],
        cancel_goal: Callable[[], None],
        hard_stop: Callable[[], None],
        waypoint_spacing_m: float = 2.0,
        waypoint_timeout_sec: float = 45.0,
        poll_interval_sec: float = 0.1,
    ):
        self._send_goal = send_goal
        self._read_goal_status = read_goal_status
        self._read_health = read_health
        self._cancel_goal = cancel_goal
        self._hard_stop = hard_stop
        self._waypoint_spacing_m = max(0.1, float(waypoint_spacing_m))
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
        points = sample_route_points(path, self._waypoint_spacing_m)
        if len(points) < 2:
            raise ValueError("路线压缩后有效节点少于2个")
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
                "startedAt": now,
                "updatedAt": now,
                "finishedAt": None,
                "error": "",
            }
            thread = threading.Thread(
                target=self._run,
                args=(points,),
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

    def _run(self, points: List[dict]) -> None:
        try:
            index = 0
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
