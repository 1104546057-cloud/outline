"""摔倒检测：人体 bbox 宽高比持续超阈值（侧卧/倒地时 w/h 显著变大）。

见 docs/plans/video-analysis-module-plan.md §3.4.1。
"""

from __future__ import annotations

from collections import deque

import numpy as np

from inference.analyzers.base import BaseBehaviorAnalyzer
from inference.base import BehaviorEvent, Frame, Track
from inference.registry import analyzer_registry


@analyzer_registry.register("behavior_fall")
class FallAnalyzer(BaseBehaviorAnalyzer):
    """基于滑动窗口宽高比均值的摔倒检测。"""

    def __init__(
        self,
        aspect_ratio_threshold: float = 1.2,
        duration_frames: int = 15,
        min_confidence: float = 0.0,
        cooldown_frames: int = 0,
        **kwargs,
    ) -> None:
        super().__init__(cooldown_frames=cooldown_frames, **kwargs)
        self.aspect_ratio_threshold = float(aspect_ratio_threshold)
        self.duration_frames = max(1, int(duration_frames))
        self.min_confidence = float(min_confidence)
        self._history: dict[int, deque] = {}

    def _analyze(self, tracks: list[Track], frame: Frame) -> list[BehaviorEvent]:
        events: list[BehaviorEvent] = []
        for t in tracks:
            if t.class_name != "person" or t.confidence < self.min_confidence:
                continue
            self._touch(t.track_id)
            x1, y1, x2, y2 = t.bbox
            width = x2 - x1
            height = y2 - y1
            ratio = width / max(height, 1e-6)

            hist = self._history.setdefault(t.track_id, deque(maxlen=self.duration_frames))
            hist.append(ratio)

            if len(hist) >= self.duration_frames and np.mean(hist) > self.aspect_ratio_threshold:
                if self._can_emit(("fall", t.track_id)):
                    mean_ratio = float(np.mean(hist))
                    events.append(
                        BehaviorEvent(
                            event_type="fall",
                            track_ids=[t.track_id],
                            confidence=min(1.0, mean_ratio / (self.aspect_ratio_threshold * 2)),
                            bbox=t.bbox,
                            severity="high",
                            description=f"疑似摔倒（宽高比 {mean_ratio:.2f}）",
                            frame_idx=self._frame_idx,
                        )
                    )
        self._prune(self._history)
        return events
