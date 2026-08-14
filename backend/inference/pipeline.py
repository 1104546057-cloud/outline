"""推理管线编排：帧 → 检测 → 追踪 → 行为分析 → 事件列表。

按配置名从注册表实例化各算法组件，并串起处理流程。
"""

from __future__ import annotations

from typing import Any

from inference.base import BaseAnalyzer, BaseDetector, BaseTracker, BehaviorEvent, Frame
from inference.config import inference_config
from inference.registry import analyzer_registry, detector_registry, tracker_registry


class InferencePipeline:
    """一条推理管线：固定的一对 detector/tracker + 若干 analyzer。"""

    def __init__(
        self,
        detector: BaseDetector,
        tracker: BaseTracker,
        analyzers: list[BaseAnalyzer],
        annotate: bool = False,
        name: str = "default",
    ) -> None:
        self.name = name
        self.detector = detector
        self.tracker = tracker
        self.analyzers = analyzers
        self.annotate = annotate

    def setup(self) -> None:
        self.detector.setup()
        self.tracker.setup()
        for analyzer in self.analyzers:
            analyzer.setup()

    def teardown(self) -> None:
        for analyzer in self.analyzers:
            analyzer.teardown()
        self.tracker.teardown()
        self.detector.teardown()

    def run(self, frame: Frame) -> tuple[list, list, list[BehaviorEvent]]:
        """处理单帧，返回 (detections, tracks, events) 三元组。"""
        detections = self.detector.detect(frame)
        tracks = self.tracker.update(detections, frame)
        events: list[BehaviorEvent] = []
        for analyzer in self.analyzers:
            events.extend(analyzer.analyze(tracks, frame))
        return detections, tracks, events

    def process(self, frame: Frame) -> list[BehaviorEvent]:
        """处理单帧，仅返回行为事件（兼容旧调用）。"""
        return self.run(frame)[2]


def build_pipeline(pipeline_cfg: dict[str, Any]) -> InferencePipeline:
    """按配置构建推理管线。

    pipeline_cfg 支持可选 *_params 字段透传给组件构造函数：
      detector_params / tracker_params / analyzer_params.<name>
    """
    detector_name = pipeline_cfg.get("detector", "dummy")
    tracker_name = pipeline_cfg.get("tracker", "dummy")
    analyzer_names = pipeline_cfg.get("analyzers", ["dummy"])

    detector_cls = detector_registry.get(detector_name)
    tracker_cls = tracker_registry.get(tracker_name)

    detector_params = dict(pipeline_cfg.get("detector_params") or {})
    # 把插件名透传给检测器（YOLO 用它定位 models.<name> 权重配置）
    detector_params.setdefault("model_name", detector_name)
    detector = detector_cls(**detector_params)
    tracker = tracker_cls(**(pipeline_cfg.get("tracker_params") or {}))

    analyzer_params = pipeline_cfg.get("analyzer_params") or {}
    behaviors_cfg = inference_config.get_behaviors()
    analyzers: list[BaseAnalyzer] = []
    for name in analyzer_names:
        # 顶层 behaviors.<key> 提供阈值默认值（behavior_fall → fall），
        # analyzer_params.<name> 可进一步覆盖
        behavior_key = str(name).removeprefix("behavior_")
        params = dict(behaviors_cfg.get(behavior_key) or {})
        if isinstance(analyzer_params, dict):
            params.update(analyzer_params.get(name) or {})
        analyzers.append(analyzer_registry.get(name)(**params))

    pipeline = InferencePipeline(
        detector=detector,
        tracker=tracker,
        analyzers=analyzers,
        annotate=bool(pipeline_cfg.get("annotate", False)),
        name=str(pipeline_cfg.get("name", "default")),
    )
    pipeline.setup()
    return pipeline
