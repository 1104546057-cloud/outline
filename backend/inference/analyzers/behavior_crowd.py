"""聚集检测：局部区域目标数持续达到阈值。

基于中心点距离的连通聚类，见 docs/plans/video-analysis-module-plan.md §3.4.1。
"""

from __future__ import annotations

import math

from inference.analyzers.base import BaseBehaviorAnalyzer
from inference.base import BehaviorEvent, Frame, Track
from inference.registry import analyzer_registry


@analyzer_registry.register("behavior_crowd")
class CrowdAnalyzer(BaseBehaviorAnalyzer):
    """基于中心点距离聚类的聚集检测。"""

    def __init__(
        self,
        min_targets: int = 5,
        distance_threshold: float = 50.0,
        duration_frames: int = 30,
        cooldown_frames: int = 0,
        **kwargs,
    ) -> None:
        super().__init__(cooldown_frames=cooldown_frames, **kwargs)
        self.min_targets = max(2, int(min_targets))
        self.distance_threshold = float(distance_threshold)
        self.duration_frames = max(1, int(duration_frames))
        self._crowd_streak = 0

    def _analyze(self, tracks: list[Track], frame: Frame) -> list[BehaviorEvent]:
        persons = [t for t in tracks if t.class_name == "person"]
        for t in persons:
            self._touch(t.track_id)

        max_cluster_size = 0
        largest_cluster_ids: list[int] = []
        if len(persons) >= self.min_targets:
            clusters = self._cluster(persons)
            if clusters:
                largest = max(clusters, key=len)
                max_cluster_size = len(largest)
                largest_cluster_ids = [persons[i].track_id for i in largest]

        if max_cluster_size >= self.min_targets:
            self._crowd_streak += 1
        else:
            self._crowd_streak = 0

        events: list[BehaviorEvent] = []
        if self._crowd_streak >= self.duration_frames and self._can_emit("crowd"):
            events.append(
                BehaviorEvent(
                    event_type="crowd",
                    track_ids=largest_cluster_ids,
                    confidence=min(1.0, max_cluster_size / (self.min_targets * 2)),
                    bbox=(0.0, 0.0, 0.0, 0.0),
                    severity="high",
                    description=f"疑似人群聚集（{max_cluster_size} 人）",
                    frame_idx=self._frame_idx,
                )
            )
            self._crowd_streak = 0
        return events

    def _cluster(self, persons: list[Track]) -> list[list[int]]:
        """按中心点距离做连通聚类，返回每个簇的人员下标列表。"""
        centers = [
            ((t.bbox[0] + t.bbox[2]) / 2.0, (t.bbox[1] + t.bbox[3]) / 2.0)
            for t in persons
        ]
        n = len(persons)
        visited = [False] * n
        clusters: list[list[int]] = []
        for i in range(n):
            if visited[i]:
                continue
            stack = [i]
            visited[i] = True
            cluster: list[int] = []
            while stack:
                cur = stack.pop()
                cluster.append(cur)
                cx, cy = centers[cur]
                for j in range(n):
                    if visited[j]:
                        continue
                    ox, oy = centers[j]
                    if math.hypot(cx - ox, cy - oy) < self.distance_threshold:
                        visited[j] = True
                        stack.append(j)
            clusters.append(cluster)
        return clusters
