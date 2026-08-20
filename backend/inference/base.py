"""推理模块抽象基类与通用数据结构。

所有检测器 / 追踪器 / 行为分析器都实现统一接口，框架据此装配推理管线。
数据结构为纯 Python（不依赖 numpy），保证框架在未安装图像库时也可加载。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# frame 参数约定：安装 cv2+numpy 时传入 BGR ndarray，否则传入原始 JPEG bytes。
# 各实现应宽容处理 frame，仅当确实需要像素内容时再解码。
Frame = Any


@dataclass
class Detection:
    """单帧检测框结果。"""

    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2
    confidence: float
    class_name: str
    class_id: int = -1


@dataclass
class Track:
    """跨帧追踪目标。"""

    track_id: int
    bbox: tuple[float, float, float, float]
    confidence: float
    class_name: str
    frame_idx: int


@dataclass
class BehaviorEvent:
    """行为分析产出的事件（fall / crowd / run 等）。"""

    event_type: str
    track_ids: list[int] = field(default_factory=list)
    confidence: float = 0.0
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    description: str = ""
    severity: str = "medium"  # info / low / medium / high / critical
    frame_idx: int | None = None
    occurred_at: datetime | None = None

    def to_payload(self, device_id: int) -> dict[str, Any]:
        """序列化为 analytics_event 的 payload。"""
        return {
            "event_type": self.event_type,
            "device_id": device_id,
            "track_ids": self.track_ids,
            "confidence": round(float(self.confidence), 4),
            "bbox": [round(float(v), 2) for v in self.bbox],
            "severity": self.severity,
            "description": self.description,
        }


class BaseDetector(ABC):
    """目标检测器抽象基类。"""

    def setup(self) -> None:
        """可选初始化钩子（加载模型等）。"""

    def teardown(self) -> None:
        """可选清理钩子。"""

    @abstractmethod
    def detect(self, frame: Frame) -> list[Detection]:
        """对单帧执行检测，返回检测结果列表。"""
        raise NotImplementedError


class BaseTracker(ABC):
    """多目标追踪器抽象基类。"""

    def setup(self) -> None:
        """可选初始化钩子。"""

    def teardown(self) -> None:
        """可选清理钩子。"""

    @abstractmethod
    def update(self, detections: list[Detection], frame: Frame) -> list[Track]:
        """用当前帧检测结果更新追踪状态，返回活跃 track 列表。"""
        raise NotImplementedError


class BaseAnalyzer(ABC):
    """行为分析器抽象基类。"""

    def setup(self) -> None:
        """可选初始化钩子。"""

    def teardown(self) -> None:
        """可选清理钩子。"""

    @abstractmethod
    def analyze(self, tracks: list[Track], frame: Frame) -> list[BehaviorEvent]:
        """基于追踪结果分析异常行为，返回事件列表。"""
        raise NotImplementedError
