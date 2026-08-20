"""空追踪器：不做跨帧关联，检测结果原样丢弃（返回空列表）。"""

from __future__ import annotations

from inference.base import BaseTracker, Detection, Frame, Track
from inference.registry import tracker_registry


@tracker_registry.register("dummy")
class DummyTracker(BaseTracker):
    """不追踪，始终返回空列表。"""

    def __init__(self, **kwargs) -> None:  # noqa: ARG002
        pass

    def update(self, detections: list[Detection], frame: Frame) -> list[Track]:
        return []
