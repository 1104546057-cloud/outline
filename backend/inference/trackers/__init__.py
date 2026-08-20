"""追踪器插件包。导入本包即触发内置追踪器注册。"""

from inference.trackers.bytetrack_tracker import ByteTrackTracker  # noqa: F401
from inference.trackers.dummy_tracker import DummyTracker  # noqa: F401

__all__ = ["ByteTrackTracker", "DummyTracker"]
