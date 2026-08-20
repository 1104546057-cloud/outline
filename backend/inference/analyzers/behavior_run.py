"""奔跑检测：追踪目标中心点帧间位移持续超阈值。

注意：speed_threshold 单位为像素/帧（未做相机标定）。换算为真实 m/s
需相机标定与地面投影，超出 M4 范围，见 docs/plans/video-analysis-module-plan.md §3.4.1。
"""

from __future__ import annotations

import math

from inference.analyzers.base import BaseBehaviorAnalyzer
from inference.base import BehaviorEvent, Frame, Track
from inference.registry import analyzer_registry


@analyzer_registry.register("behavior_run")
class RunAnalyzer(BaseBehaviorAnalyzer):
    """基于中心点帧间位移的奔跑检测。"""

    def __init__(
        self,
        speed_threshold: float = 3.0,
        duration_frames: int = 10,
        cooldown_frames: int = 0,
        **kwargs,
    ) -> None:
        super().__init__(cooldown_frames=cooldown_frames, **kwargs)
        self.speed_threshold = float(speed_threshold)
        self.duration_frames = max(1, int(duration_frames))
        self._last_center: dict[int, tuple[float, float]] = {}
        self._run_streak: dict[int, int] = {}

    def _analyze(self, tracks: list[Track], frame: Frame) -> list[BehaviorEvent]:
        events: list[BehaviorEvent] = []
        for t in tracks:
            if t.class_name != "person":
                continue
            self._touch(t.track_id)
            cx = (t.bbox[0] + t.bbox[2]) / 2.0
            cy = (t.bbox[1] + t.bbox[3]) / 2.0

            prev = self._last_center.get(t.track_id)
            self._last_center[t.track_id] = (cx, cy)
            if prev is None:
                continue

            distance = math.hypot(cx - prev[0], cy - prev[1])
            streak = self._run_streak.get(t.track_id, 0)
            if distance > self.speed_threshold:
                streak += 1
            else:
                streak = 0
            self._run_streak[t.track_id] = streak

            if streak >= self.duration_frames and self._can_emit(("run", t.track_id)):
                events.append(
                    BehaviorEvent(
                        event_type="run",
                        track_ids=[t.track_id],
                        confidence=min(1.0, distance / (self.speed_threshold * 4)),
                        bbox=t.bbox,
                        severity="medium",
                        description=f"疑似奔跑（位移 {distance:.1f}px/帧）",
                        frame_idx=self._frame_idx,
                    )
                )
        self._prune(self._last_center)
        self._prune(self._run_streak)
        return events
