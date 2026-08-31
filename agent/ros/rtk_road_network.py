#!/usr/bin/env python3
"""RTK road survey persistence, graph building and read-only route planning."""

import heapq
import json
import math
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


EARTH_RADIUS_M = 6378137.0
SAFE_ID = re.compile(r"^[a-z0-9-]+$")


def haversine_m(first: dict, second: dict) -> float:
    lat1 = math.radians(float(first["latitude"]))
    lat2 = math.radians(float(second["latitude"]))
    delta_lat = lat2 - lat1
    delta_lon = math.radians(float(second["longitude"]) - float(first["longitude"]))
    value = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2.0) ** 2
    )
    return EARTH_RADIUS_M * 2.0 * math.atan2(math.sqrt(value), math.sqrt(max(0.0, 1.0 - value)))


def bearing_deg(first: dict, second: dict) -> float:
    latitude_1 = math.radians(float(first["latitude"]))
    latitude_2 = math.radians(float(second["latitude"]))
    delta_longitude = math.radians(float(second["longitude"]) - float(first["longitude"]))
    east = math.sin(delta_longitude) * math.cos(latitude_2)
    north = (
        math.cos(latitude_1) * math.sin(latitude_2)
        - math.sin(latitude_1) * math.cos(latitude_2) * math.cos(delta_longitude)
    )
    return math.degrees(math.atan2(east, north))


def heading_delta_deg(first: dict, middle: dict, last: dict) -> float:
    delta = abs(bearing_deg(middle, last) - bearing_deg(first, middle)) % 360.0
    return min(delta, 360.0 - delta)


def utc_iso(timestamp: Optional[float] = None) -> str:
    value = time.time() if timestamp is None else float(timestamp)
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def preview_points(points: List[dict], limit: int) -> List[dict]:
    if len(points) <= limit:
        return [dict(point) for point in points]
    stride = max(1, int(math.ceil(len(points) / float(limit))))
    preview = [dict(point) for point in points[::stride]]
    if preview[-1] != points[-1]:
        preview.append(dict(points[-1]))
    return preview


def sample_by_distance(points: List[dict], spacing_m: float) -> List[dict]:
    if not points:
        return []
    sampled = [points[0]]
    for point in points[1:-1]:
        if haversine_m(sampled[-1], point) >= spacing_m:
            sampled.append(point)
    if len(points) > 1 and points[-1] is not sampled[-1]:
        sampled.append(points[-1])
    return sampled


class RoadWorkspace:
    """Thread-safe vehicle-side store for WGS-84 survey tracks and road graphs."""

    def __init__(
        self,
        root: Path,
        preview_limit: int = 500,
        min_record_spacing_m: float = 1.0,
        turn_record_spacing_m: float = 0.5,
        turn_threshold_deg: float = 12.0,
        network_spacing_m: float = 0.25,
        merge_radius_m: float = 0.75,
    ) -> None:
        self.root = Path(root)
        self.track_dir = self.root / "tracks"
        self.network_dir = self.root / "networks"
        self.active_dir = self.root / "active"
        self.preview_limit = max(20, int(preview_limit))
        self.min_record_spacing_m = max(0.0, float(min_record_spacing_m))
        self.turn_record_spacing_m = min(
            self.min_record_spacing_m,
            max(0.0, float(turn_record_spacing_m)),
        )
        self.turn_threshold_deg = max(1.0, min(90.0, float(turn_threshold_deg)))
        self.network_spacing_m = max(0.05, float(network_spacing_m))
        self.merge_radius_m = max(0.1, float(merge_radius_m))
        self._lock = threading.RLock()
        self._active = None
        self.track_dir.mkdir(parents=True, exist_ok=True)
        self.network_dir.mkdir(parents=True, exist_ok=True)
        self.active_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _display_name(value: str, fallback: str) -> str:
        cleaned = " ".join(str(value or "").strip().split())
        return cleaned[:80] or fallback

    @staticmethod
    def _new_id(prefix: str) -> str:
        return "%s-%s-%s" % (
            prefix,
            datetime.now().strftime("%Y%m%d-%H%M%S"),
            uuid.uuid4().hex[:6],
        )

    @staticmethod
    def _require_id(value: str) -> str:
        item_id = str(value or "").strip().lower()
        if not SAFE_ID.fullmatch(item_id):
            raise ValueError("道路数据ID格式不合法")
        return item_id

    def _active_log_path(self, track_id: str) -> Path:
        return self.active_dir / (track_id + ".jsonl")

    def _active_meta_path(self, track_id: str) -> Path:
        return self.active_dir / (track_id + ".json")

    def _track_path(self, track_id: str) -> Path:
        return self.track_dir / (self._require_id(track_id) + ".json")

    def _network_path(self, network_id: str) -> Path:
        return self.network_dir / (self._require_id(network_id) + ".json")

    def start(self, name: str, health: dict) -> dict:
        with self._lock:
            if self._active is not None:
                raise RuntimeError("已有道路采集会话，请先停止或放弃")
            if not bool(health.get("valid")):
                raise RuntimeError("RTK 尚未达到 Fixed，不能开始道路采集")
            now = time.time()
            track_id = self._new_id("track")
            self._active = {
                "id": track_id,
                "name": self._display_name(name, "RTK道路采集 " + datetime.now().strftime("%m-%d %H:%M")),
                "state": "recording",
                "coordinateSystem": "WGS-84",
                "startedAt": utc_iso(now),
                "startedTimestamp": now,
                "manualPaused": False,
                "qualityPaused": False,
                "points": [],
                "rawFixes": 0,
                "skippedInvalid": 0,
                "skippedDistance": 0,
                "distanceM": 0.0,
                "lastError": "",
            }
            self._active_log_path(track_id).write_text("", encoding="utf-8")
            self._write_active_meta()
            return self.status()

    def _write_active_meta(self) -> None:
        if self._active is None:
            return
        active = self._active
        write_json_atomic(
            self._active_meta_path(active["id"]),
            {
                "id": active["id"],
                "name": active["name"],
                "state": active["state"],
                "coordinateSystem": active["coordinateSystem"],
                "startedAt": active["startedAt"],
                "manualPaused": active["manualPaused"],
                "qualityPaused": active["qualityPaused"],
                "pointCount": len(active["points"]),
                "rawFixes": active["rawFixes"],
                "skippedInvalid": active["skippedInvalid"],
                "skippedDistance": active["skippedDistance"],
                "distanceM": active["distanceM"],
                "lastError": active["lastError"],
                "updatedAt": utc_iso(),
            },
        )

    def pause(self) -> dict:
        with self._lock:
            if self._active is None:
                raise RuntimeError("当前没有道路采集会话")
            self._active["manualPaused"] = True
            self._active["state"] = "paused"
            self._write_active_meta()
            return self.status()

    def resume(self, health: dict) -> dict:
        with self._lock:
            if self._active is None:
                raise RuntimeError("当前没有道路采集会话")
            if not bool(health.get("valid")):
                raise RuntimeError("RTK 尚未恢复 Fixed，不能继续采集")
            self._active["manualPaused"] = False
            self._active["qualityPaused"] = False
            self._active["state"] = "recording"
            self._active["lastError"] = ""
            self._write_active_meta()
            return self.status()

    def add_fix(
        self,
        longitude: float,
        latitude: float,
        altitude: Optional[float],
        status_code: Optional[int],
        covariance_x: Optional[float],
        covariance_y: Optional[float],
        health: dict,
        timestamp: Optional[float] = None,
    ) -> bool:
        with self._lock:
            active = self._active
            if active is None or active["manualPaused"]:
                return False
            active["rawFixes"] += 1
            if not bool(health.get("valid")):
                active["qualityPaused"] = True
                active["skippedInvalid"] += 1
                active["lastError"] = str(health.get("lastError") or "RTK质量门未通过")
                if active["skippedInvalid"] % 10 == 1:
                    self._write_active_meta()
                return False
            values = (float(longitude), float(latitude))
            if not all(math.isfinite(value) for value in values):
                active["skippedInvalid"] += 1
                active["lastError"] = "收到非法经纬度"
                return False
            if not (-180.0 <= values[0] <= 180.0 and -90.0 <= values[1] <= 90.0):
                active["skippedInvalid"] += 1
                active["lastError"] = "经纬度超出范围"
                return False
            active["qualityPaused"] = False
            active["lastError"] = ""
            now = time.time() if timestamp is None else float(timestamp)
            point = {
                "sequence": len(active["points"]),
                "timestamp": now,
                "recordedAt": utc_iso(now),
                "longitude": values[0],
                "latitude": values[1],
                "altitude": float(altitude) if altitude is not None and math.isfinite(float(altitude)) else None,
                "quality": health.get("quality"),
                "status": status_code,
                "covarianceX": covariance_x,
                "covarianceY": covariance_y,
            }
            previous = active["points"][-1] if active["points"] else None
            distance = haversine_m(previous, point) if previous else 0.0
            required_spacing = self.min_record_spacing_m
            if previous and len(active["points"]) >= 2:
                turn_angle = heading_delta_deg(active["points"][-2], previous, point)
                if turn_angle >= self.turn_threshold_deg:
                    required_spacing = self.turn_record_spacing_m
            if previous and distance < required_spacing:
                active["skippedDistance"] += 1
                return False
            active["points"].append(point)
            active["distanceM"] += distance
            with self._active_log_path(active["id"]).open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(point, ensure_ascii=False, separators=(",", ":")) + "\n")
            if len(active["points"]) % 10 == 0:
                self._write_active_meta()
            return True

    def status(self) -> dict:
        with self._lock:
            if self._active is None:
                return {
                    "active": False,
                    "state": "idle",
                    "coordinateSystem": "WGS-84",
                    "pointCount": 0,
                    "preview": [],
                }
            active = self._active
            return {
                "active": True,
                "id": active["id"],
                "name": active["name"],
                "state": "paused" if active["manualPaused"] else "recording",
                "coordinateSystem": active["coordinateSystem"],
                "startedAt": active["startedAt"],
                "manualPaused": active["manualPaused"],
                "qualityPaused": active["qualityPaused"],
                "pointCount": len(active["points"]),
                "rawFixes": active["rawFixes"],
                "skippedInvalid": active["skippedInvalid"],
                "skippedDistance": active["skippedDistance"],
                "distanceM": active["distanceM"],
                "lastError": active["lastError"],
                "recordSpacingM": self.min_record_spacing_m,
                "turnRecordSpacingM": self.turn_record_spacing_m,
                "turnThresholdDeg": self.turn_threshold_deg,
                "preview": preview_points(active["points"], self.preview_limit),
            }

    def stop(self) -> dict:
        with self._lock:
            if self._active is None:
                raise RuntimeError("当前没有道路采集会话")
            active = self._active
            if len(active["points"]) < 2:
                raise RuntimeError("有效RTK轨迹点少于2个，请继续采集或选择放弃")
            stopped_at = utc_iso()
            payload = {
                "version": 1,
                "id": active["id"],
                "name": active["name"],
                "coordinateSystem": "WGS-84",
                "startedAt": active["startedAt"],
                "stoppedAt": stopped_at,
                "statistics": {
                    "pointCount": len(active["points"]),
                    "rawFixes": active["rawFixes"],
                    "skippedInvalid": active["skippedInvalid"],
                    "skippedDistance": active["skippedDistance"],
                    "distanceM": active["distanceM"],
                },
                "points": active["points"],
            }
            write_json_atomic(self._track_path(active["id"]), payload)
            result = self._track_summary(payload)
            self._cleanup_active(active["id"])
            self._active = None
            return result

    def discard(self) -> dict:
        with self._lock:
            if self._active is None:
                raise RuntimeError("当前没有道路采集会话")
            track_id = self._active["id"]
            self._cleanup_active(track_id)
            self._active = None
            return self.status()

    def _cleanup_active(self, track_id: str) -> None:
        for path in (self._active_log_path(track_id), self._active_meta_path(track_id)):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _track_summary(payload: dict) -> dict:
        return {
            "id": payload["id"],
            "name": payload["name"],
            "coordinateSystem": payload.get("coordinateSystem", "WGS-84"),
            "startedAt": payload.get("startedAt"),
            "stoppedAt": payload.get("stoppedAt"),
            "statistics": payload.get("statistics", {}),
        }

    def list_tracks(self) -> List[dict]:
        tracks = []
        for path in sorted(self.track_dir.glob("track-*.json"), reverse=True):
            try:
                tracks.append(self._track_summary(read_json(path)))
            except (OSError, ValueError, KeyError):
                continue
        return tracks

    def get_track(self, track_id: str) -> dict:
        path = self._track_path(track_id)
        if not path.is_file():
            raise FileNotFoundError("道路采集轨迹不存在")
        return read_json(path)

    def build_network(self, name: str, track_ids: List[str]) -> dict:
        selected_ids = list(dict.fromkeys(self._require_id(item) for item in track_ids))
        if not selected_ids:
            raise ValueError("至少选择一条道路采集轨迹")
        tracks = [self.get_track(track_id) for track_id in selected_ids]
        network_id = self._new_id("network")
        graph = self._tracks_to_graph(tracks)
        payload = {
            "version": 1,
            "id": network_id,
            "name": self._display_name(name, "校园RTK道路网络 " + datetime.now().strftime("%m-%d")),
            "coordinateSystem": "WGS-84",
            "createdAt": utc_iso(),
            "sourceTrackIds": selected_ids,
            "settings": {
                "networkSpacingM": self.network_spacing_m,
                "mergeRadiusM": self.merge_radius_m,
            },
            "statistics": {
                "trackCount": len(selected_ids),
                "nodeCount": len(graph["nodes"]),
                "edgeCount": len(graph["edges"]),
                "distanceM": sum(edge["distanceM"] for edge in graph["edges"]),
            },
            "nodes": graph["nodes"],
            "edges": graph["edges"],
        }
        write_json_atomic(self._network_path(network_id), payload)
        return payload

    def _tracks_to_graph(self, tracks: List[dict]) -> dict:
        all_points = [point for track in tracks for point in track.get("points", [])]
        if len(all_points) < 2:
            raise ValueError("轨迹有效点不足，无法生成道路网络")
        origin_lat = sum(float(point["latitude"]) for point in all_points) / len(all_points)
        origin_lon = sum(float(point["longitude"]) for point in all_points) / len(all_points)
        cosine = max(0.01, math.cos(math.radians(origin_lat)))
        nodes = []
        buckets = {}
        edge_distances = {}

        def local_xy(point: dict) -> Tuple[float, float]:
            x_value = EARTH_RADIUS_M * math.radians(float(point["longitude"]) - origin_lon) * cosine
            y_value = EARTH_RADIUS_M * math.radians(float(point["latitude"]) - origin_lat)
            return x_value, y_value

        def find_or_create(point: dict) -> int:
            x_value, y_value = local_xy(point)
            cell_x = int(math.floor(x_value / self.merge_radius_m))
            cell_y = int(math.floor(y_value / self.merge_radius_m))
            best_id = None
            best_distance = self.merge_radius_m
            for x_offset in (-1, 0, 1):
                for y_offset in (-1, 0, 1):
                    for node_id in buckets.get((cell_x + x_offset, cell_y + y_offset), []):
                        node = nodes[node_id]
                        distance = math.hypot(x_value - node["_x"], y_value - node["_y"])
                        if distance <= best_distance:
                            best_id = node_id
                            best_distance = distance
            if best_id is not None:
                return best_id
            node_id = len(nodes)
            nodes.append({
                "id": node_id,
                "longitude": float(point["longitude"]),
                "latitude": float(point["latitude"]),
                "_x": x_value,
                "_y": y_value,
            })
            buckets.setdefault((cell_x, cell_y), []).append(node_id)
            return node_id

        for track in tracks:
            sampled = sample_by_distance(track.get("points", []), self.network_spacing_m)
            previous_id = None
            for point in sampled:
                node_id = find_or_create(point)
                if previous_id is not None and node_id != previous_id:
                    key = tuple(sorted((previous_id, node_id)))
                    distance = haversine_m(nodes[previous_id], nodes[node_id])
                    current = edge_distances.get(key)
                    if current is None or distance < current:
                        edge_distances[key] = distance
                previous_id = node_id

        public_nodes = [
            {"id": node["id"], "longitude": node["longitude"], "latitude": node["latitude"]}
            for node in nodes
        ]
        edges = [
            {"from": key[0], "to": key[1], "distanceM": distance}
            for key, distance in sorted(edge_distances.items())
        ]
        if not edges:
            raise ValueError("轨迹未形成有效道路边")
        return {"nodes": public_nodes, "edges": edges}

    @staticmethod
    def _network_summary(payload: dict) -> dict:
        return {
            "id": payload["id"],
            "name": payload["name"],
            "coordinateSystem": payload.get("coordinateSystem", "WGS-84"),
            "createdAt": payload.get("createdAt"),
            "sourceTrackIds": payload.get("sourceTrackIds", []),
            "statistics": payload.get("statistics", {}),
        }

    def list_networks(self) -> List[dict]:
        networks = []
        for path in sorted(self.network_dir.glob("network-*.json"), reverse=True):
            try:
                networks.append(self._network_summary(read_json(path)))
            except (OSError, ValueError, KeyError):
                continue
        return networks

    def get_network(self, network_id: str) -> dict:
        path = self._network_path(network_id)
        if not path.is_file():
            raise FileNotFoundError("RTK道路网络不存在")
        return read_json(path)

    @staticmethod
    def _nearest_node(nodes: List[dict], point: dict) -> Tuple[int, float]:
        if not nodes:
            raise ValueError("道路网络没有节点")
        best_node = nodes[0]
        best_distance = haversine_m(best_node, point)
        for node in nodes[1:]:
            distance = haversine_m(node, point)
            if distance < best_distance:
                best_node = node
                best_distance = distance
        return int(best_node["id"]), best_distance

    def plan(
        self,
        network_id: str,
        start_longitude: float,
        start_latitude: float,
        goal_longitude: float,
        goal_latitude: float,
        max_snap_m: float = 5.0,
    ) -> dict:
        network = self.get_network(network_id)
        nodes = network.get("nodes", [])
        node_by_id = {int(node["id"]): node for node in nodes}
        start = {"longitude": float(start_longitude), "latitude": float(start_latitude)}
        goal = {"longitude": float(goal_longitude), "latitude": float(goal_latitude)}
        start_id, start_snap = self._nearest_node(nodes, start)
        goal_id, goal_snap = self._nearest_node(nodes, goal)
        limit = max(0.1, float(max_snap_m))
        if start_snap > limit:
            raise ValueError("车辆距离道路网络 %.2f 米，超过吸附上限 %.2f 米" % (start_snap, limit))
        if goal_snap > limit:
            raise ValueError("目标距离道路网络 %.2f 米，超过吸附上限 %.2f 米" % (goal_snap, limit))

        adjacency = {node_id: [] for node_id in node_by_id}
        for edge in network.get("edges", []):
            first = int(edge["from"])
            second = int(edge["to"])
            distance = float(edge["distanceM"])
            adjacency.setdefault(first, []).append((second, distance))
            adjacency.setdefault(second, []).append((first, distance))

        queue = [(0.0, start_id)]
        cost = {start_id: 0.0}
        previous = {}
        while queue:
            _, current = heapq.heappop(queue)
            if current == goal_id:
                break
            for neighbour, edge_cost in adjacency.get(current, []):
                candidate = cost[current] + edge_cost
                if candidate >= cost.get(neighbour, float("inf")):
                    continue
                cost[neighbour] = candidate
                previous[neighbour] = current
                heuristic = haversine_m(node_by_id[neighbour], node_by_id[goal_id])
                heapq.heappush(queue, (candidate + heuristic, neighbour))
        if goal_id not in cost:
            raise ValueError("车辆与目标不在同一个连通道路网络中")
        path_ids = [goal_id]
        while path_ids[-1] != start_id:
            path_ids.append(previous[path_ids[-1]])
        path_ids.reverse()
        path = [node_by_id[node_id] for node_id in path_ids]
        return {
            "networkId": network["id"],
            "coordinateSystem": "WGS-84",
            "startNodeId": start_id,
            "goalNodeId": goal_id,
            "startSnapDistanceM": start_snap,
            "goalSnapDistanceM": goal_snap,
            "distanceM": cost[goal_id],
            "path": path,
        }
