"""检测器插件包。导入本包即触发内置检测器注册。"""

from inference.detectors.dummy_detector import DummyDetector  # noqa: F401
from inference.detectors.yolo_detector import YoloDetector  # noqa: F401

__all__ = ["DummyDetector", "YoloDetector"]
