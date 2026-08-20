"""空检测器：开发联调用，不产生任何检测结果。

接入真实模型（YOLOv8 等）前，用它验证管线装配与帧流转是否正常。
"""

from __future__ import annotations

from inference.base import BaseDetector, Detection, Frame
from inference.registry import detector_registry


@detector_registry.register("dummy")
class DummyDetector(BaseDetector):
    """不做任何检测，始终返回空列表。"""

    def __init__(self, **kwargs) -> None:  # noqa: ARG002
        pass

    def detect(self, frame: Frame) -> list[Detection]:
        return []
