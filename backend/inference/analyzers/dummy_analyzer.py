"""空行为分析器：不产出任何事件。

默认仅用于验证管线流转；通过 emit_every 可在联调时周期性造一条
低等级事件，用于端到端验证事件归集链路。
"""

from __future__ import annotations

from inference.base import BaseAnalyzer, BehaviorEvent, Frame, Track
from inference.registry import analyzer_registry


@analyzer_registry.register("dummy")
class DummyAnalyzer(BaseAnalyzer):
    """不分析行为；可选地每 N 帧产出一条 info 级 dummy 事件。"""

    def __init__(self, emit_every: int = 0, **kwargs) -> None:  # noqa: ARG002
        self._emit_every = max(0, int(emit_every))
        self._frame_idx = 0

    def analyze(self, tracks: list[Track], frame: Frame) -> list[BehaviorEvent]:
        self._frame_idx += 1
        if self._emit_every > 0 and self._frame_idx % self._emit_every == 0:
            return [
                BehaviorEvent(
                    event_type="dummy",
                    track_ids=[],
                    confidence=1.0,
                    description="dummy 管线联调事件",
                    severity="info",
                    frame_idx=self._frame_idx,
                )
            ]
        return []
