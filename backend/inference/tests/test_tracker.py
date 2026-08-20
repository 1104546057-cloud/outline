"""多目标追踪器单元测试（M3）。

覆盖：
1. IoU 矩阵 / 贪心匹配
2. 同一目标连续帧 ID 稳定
3. 新目标分配新 ID
4. 丢失后 buffer 内重连保持 ID
5. 超过 buffer 移除后重新分配新 ID
6. 低置信度检测仍能维持轨迹（两阶段关联）

运行::

    cd backend
    python -m pytest inference/tests/ -v
"""

from __future__ import annotations

import numpy as np

from inference.base import Detection
from inference.trackers.bytetrack_tracker import ByteTrackTracker, greedy_match, iou_batch


def _det(bbox, conf=0.9, cls="person", cls_id=0):
    return Detection(bbox=tuple(bbox), confidence=conf, class_name=cls, class_id=cls_id)


# ============================================================
# IoU / 匹配
# ============================================================

class TestIoU:
    def test_iou_batch(self):
        boxes1 = np.array([[0, 0, 10, 10]], dtype=float)
        boxes2 = np.array([[5, 5, 15, 15]], dtype=float)
        got = iou_batch(boxes1, boxes2)[0, 0]
        assert abs(got - 25.0 / 175.0) < 1e-6

    def test_greedy_match(self):
        iou = np.array([[0.9, 0.1], [0.2, 0.8]], dtype=float)
        matches = greedy_match(iou, threshold=0.5)
        assert sorted(matches) == [(0, 0), (1, 1)]


# ============================================================
# 追踪器
# ============================================================

class TestByteTrack:
    def _tracker(self, **kw):
        params = dict(track_thresh=0.5, match_thresh=0.5)
        params.update(kw)
        return ByteTrackTracker(**params)

    def test_same_object_keeps_id(self):
        tracker = self._tracker()
        t1 = tracker.update([_det((0, 0, 10, 10))], None)
        assert len(t1) == 1
        t2 = tracker.update([_det((1, 1, 11, 11))], None)
        assert len(t2) == 1
        assert t2[0].track_id == t1[0].track_id

    def test_new_object_gets_new_id(self):
        tracker = self._tracker()
        t1 = tracker.update([_det((0, 0, 10, 10))], None)
        t2 = tracker.update([_det((0, 0, 10, 10)), _det((100, 100, 110, 110))], None)
        ids = {t.track_id for t in t2}
        assert t1[0].track_id in ids
        assert len(ids) == 2

    def test_lost_reappear_within_buffer(self):
        tracker = self._tracker()
        t1 = tracker.update([_det((0, 0, 10, 10))], None)
        assert tracker.update([], None) == []
        t3 = tracker.update([_det((0, 0,10, 10))], None)
        assert len(t3) == 1
        assert t3[0].track_id == t1[0].track_id

    def test_removed_after_buffer(self):
        tracker = self._tracker(track_buffer=2)
        t1 = tracker.update([_det((0, 0, 10, 10))], None)
        for _ in range(3):  # 丢失 3 帧 > buffer 2
            tracker.update([], None)
        t_new = tracker.update([_det((0, 0, 10, 10))], None)
        assert len(t_new) == 1
        assert t_new[0].track_id != t1[0].track_id

    def test_low_confidence_maintains_track(self):
        tracker = self._tracker()
        t1 = tracker.update([_det((0, 0, 10, 10), conf=0.9)], None)
        t2 = tracker.update([_det((1, 1, 11, 11), conf=0.3)], None)  # 低于 track_thresh
        assert len(t2) == 1
        assert t2[0].track_id == t1[0].track_id
