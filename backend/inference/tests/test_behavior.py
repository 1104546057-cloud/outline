"""行为分析器单元测试（M4）。

覆盖：摔倒（宽高比）、聚集（距离聚类）、奔跑（帧间位移）、冷却期去重。

运行::

    cd backend
    python -m pytest inference/tests/ -v
"""

from __future__ import annotations

from inference.analyzers.behavior_crowd import CrowdAnalyzer
from inference.analyzers.behavior_fall import FallAnalyzer
from inference.analyzers.behavior_run import RunAnalyzer
from inference.base import Track


def _person(track_id, bbox, conf=0.9):
    return Track(track_id=track_id, bbox=tuple(bbox), confidence=conf, class_name="person", frame_idx=0)


# ============================================================
# 摔倒检测
# ============================================================

class TestFall:
    def test_fall_detected(self):
        analyzer = FallAnalyzer(aspect_ratio_threshold=1.2, duration_frames=3, min_confidence=0.0)
        # 宽 50 高 20 → 宽高比 2.5（倒地形态）
        tracks = [_person(1, (0, 0, 50, 20))]
        events = []
        for _ in range(3):
            events = analyzer.analyze(tracks, None)
        assert events and events[0].event_type == "fall"
        assert events[0].track_ids == [1]

    def test_upright_no_event(self):
        analyzer = FallAnalyzer(aspect_ratio_threshold=1.2, duration_frames=3, min_confidence=0.0)
        # 宽 20 高 50 → 宽高比 0.4（站立形态）
        tracks = [_person(1, (0, 0, 20, 50))]
        for _ in range(3):
            events = analyzer.analyze(tracks, None)
        assert events == []

    def test_cooldown_suppresses_repeat(self):
        analyzer = FallAnalyzer(aspect_ratio_threshold=1.2, duration_frames=2, min_confidence=0.0, cooldown_frames=5)
        tracks = [_person(1, (0, 0, 50, 20))]
        analyzer.analyze(tracks, None)
        assert analyzer.analyze(tracks, None)[0].event_type == "fall"  # 第 2 帧触发
        assert analyzer.analyze(tracks, None) == []  # 冷却期内不再重复


# ============================================================
# 聚集检测
# ============================================================

class TestCrowd:
    def test_crowd_detected(self):
        analyzer = CrowdAnalyzer(min_targets=3, distance_threshold=100, duration_frames=2)
        persons = [_person(i, (i * 1.0, 0, i * 1.0 + 10, 10)) for i in range(3)]
        events = []
        for _ in range(2):
            events = analyzer.analyze(persons, None)
        assert events and events[0].event_type == "crowd"

    def test_few_persons_no_event(self):
        analyzer = CrowdAnalyzer(min_targets=3, distance_threshold=100, duration_frames=2)
        persons = [_person(0, (0, 0, 10, 10)), _person(1, (500, 500, 510, 510))]
        for _ in range(2):
            events = analyzer.analyze(persons, None)
        assert events == []

    def test_cluster_separation(self):
        analyzer = CrowdAnalyzer(min_targets=3, distance_threshold=50, duration_frames=1)
        # 两组各 2 人，相距很远：任何一组都不够 3 人 → 不触发
        persons = [
            _person(0, (0, 0, 10, 10)),
            _person(1, (10, 0, 20, 10)),
            _person(2, (1000, 0, 1010, 10)),
            _person(3, (1010, 0, 1020, 10)),
        ]
        events = analyzer.analyze(persons, None)
        assert events == []


# ============================================================
# 奔跑检测
# ============================================================

class TestRun:
    def test_run_detected(self):
        analyzer = RunAnalyzer(speed_threshold=10, duration_frames=2)
        analyzer.analyze([_person(1, (0, 0, 10, 10))], None)   # 首帧建立基准
        analyzer.analyze([_person(1, (50, 50, 60, 60))], None)  # 位移 ~70px
        events = analyzer.analyze([_person(1, (100, 100, 110, 110))], None)
        assert events and events[0].event_type == "run"

    def test_slow_no_event(self):
        analyzer = RunAnalyzer(speed_threshold=10, duration_frames=2)
        analyzer.analyze([_person(1, (0, 0, 10, 10))], None)
        analyzer.analyze([_person(1, (1, 1, 11, 11))], None)   # 位移 ~1.4px
        events = analyzer.analyze([_person(1, (2, 2, 12, 12))], None)
        assert events == []
