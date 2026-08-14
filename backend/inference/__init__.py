"""视频识别分析模块（M1：模块化推理框架）。

只暴露纯框架组件；event_collector / frame_bus / manager 会引入
agent_gateway 与 database，按需单独 import，避免纯单元测试被数据库依赖拖累。
"""

from inference.base import (
    BaseAnalyzer,
    BaseDetector,
    BaseTracker,
    BehaviorEvent,
    Detection,
    Frame,
    Track,
)
from inference.config import InferenceConfig, inference_config
from inference.pipeline import InferencePipeline, build_pipeline
from inference.registry import (
    DuplicatePluginError,
    PluginNotFoundError,
    PluginRegistry,
    analyzer_registry,
    detector_registry,
    tracker_registry,
)

# 导入内置插件包以触发注册
from inference import analyzers, detectors, trackers  # noqa: F401

__all__ = [
    "BaseAnalyzer",
    "BaseDetector",
    "BaseTracker",
    "BehaviorEvent",
    "Detection",
    "Frame",
    "Track",
    "InferenceConfig",
    "inference_config",
    "InferencePipeline",
    "build_pipeline",
    "DuplicatePluginError",
    "PluginNotFoundError",
    "PluginRegistry",
    "analyzer_registry",
    "detector_registry",
    "tracker_registry",
]
