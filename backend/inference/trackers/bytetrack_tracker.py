"""ByteTrack 风格多目标追踪器（纯 Python 实现）。

核心思路（对齐 ByteTrack 的关键特征，见 docs/plans/video-analysis-module-plan.md §3.3）：
- 两阶段关联：高置信度检测先匹配，剩余 track 再用低置信度检测兜底，
  使遮挡/低置信帧下仍能维持 track；
- IoU 贪心匹配（基于检测框，对背景变化不敏感）；
- 恒速外推预测 + track_buffer：丢失后保留若干帧，恢复后重连；
- 不引入 lap / filterpy 等外部依赖，纯 numpy。

参数：track_thresh（高低置信分界）、match_thresh（IoU 匹配阈值）、
track_buffer（丢失保留帧数）、frame_rate（速度外推的时间基准，预留）。
"""

from __future__ import annotations

from typing import Any

from inference.base import BaseTracker, Detection, Frame, Track
from inference.registry import tracker_registry

# numpy 惰性加载：未安装时本模块仍可导入（dummy 管线不受影响），
# 仅在实际调用追踪时抛出明确错误。
_np = None


def _numpy():
    global _np
    if _np is None:
        import numpy as np

        _np = np
    return _np


def iou_batch(boxes1: Any, boxes2: Any) -> Any:
    """计算两组 xyxy 框的 IoU 矩阵 (N, M)。"""
    np = _numpy()
    boxes1 = np.asarray(boxes1, dtype=np.float64)
    boxes2 = np.asarray(boxes2, dtype=np.float64)
    if boxes1.size == 0 or boxes2.size == 0:
        return np.zeros((boxes1.shape[0], boxes2.shape[0]))

    x11, y11, x12, y12 = boxes1[:, 0], boxes1[:, 1], boxes1[:, 2], boxes1[:, 3]
    x21, y21, x22, y22 = boxes2[:, 0], boxes2[:, 1], boxes2[:, 2], boxes2[:, 3]

    inter_w = np.maximum(0.0, np.minimum(x12[:, None], x22[None, :]) - np.maximum(x11[:, None], x21[None, :]))
    inter_h = np.maximum(0.0, np.minimum(y12[:, None], y22[None, :]) - np.maximum(y11[:, None], y21[None, :]))
    inter = inter_w * inter_h

    area1 = (x12 - x11) * (y12 - y11)
    area2 = (x22 - x21) * (y22 - y21)
    union = area1[:, None] + area2[None, :] - inter
    return inter / np.maximum(union, 1e-9)


def greedy_match(iou_matrix: Any, threshold: float) -> list[tuple[int, int]]:
    """按最大 IoU 贪心匹配，返回 (det_idx, track_idx) 匹配对。"""
    iou = iou_matrix.copy()
    matches: list[tuple[int, int]] = []
    n_rows, n_cols = iou.shape
    if n_rows == 0 or n_cols == 0:
        return matches
    while True:
        flat = int(iou.argmax())
        row, col = divmod(flat, n_cols)
        if iou[row, col] < threshold:
            break
        matches.append((row, col))
        iou[row, :] = -1.0
        iou[:, col] = -1.0
    return matches


class _Tracklet:
    """单条追踪轨迹的运行时状态。"""

    def __init__(self, track_id: int, bbox: tuple, score: float, class_name: str, frame_idx: int) -> None:
        self.track_id = track_id
        self.bbox = [float(v) for v in bbox]
        self.velocity = [0.0, 0.0, 0.0, 0.0]
        self.score = float(score)
        self.class_name = class_name
        self.frame_idx = frame_idx
        self.time_since_update = 0
        self.hits = 1
        self.hit_streak = 1

    @property
    def predicted_bbox(self) -> list[float]:
        """恒速外推一步（丢失时按丢失帧数多步外推）。"""
        steps = self.time_since_update + 1
        return [self.bbox[i] + self.velocity[i] * steps for i in range(4)]

    def update(self, bbox: tuple, score: float, class_name: str, frame_idx: int) -> None:
        new_bbox = [float(v) for v in bbox]
        self.velocity = [new_bbox[i] - self.bbox[i] for i in range(4)]
        self.bbox = new_bbox
        self.score = float(score)
        self.class_name = class_name
        self.frame_idx = frame_idx
        self.time_since_update = 0
        self.hits += 1
        self.hit_streak += 1

    def mark_missed(self) -> None:
        self.time_since_update += 1
        self.hit_streak = 0

    @property
    def is_tracked(self) -> bool:
        return self.time_since_update == 0


@tracker_registry.register("bytetrack")
class ByteTrackTracker(BaseTracker):
    """IoU 关联 + 两阶段置信度 + 恒速预测 + buffer 的追踪器。"""

    def __init__(
        self,
        track_thresh: float = 0.5,
        match_thresh: float = 0.8,
        track_buffer: int = 30,
        frame_rate: int = 30,
        **kwargs,  # noqa: ARG002
    ) -> None:
        self.track_thresh = float(track_thresh)
        self.match_thresh = float(match_thresh)
        self.track_buffer = int(track_buffer)
        self.frame_rate = int(frame_rate)
        self._next_id = 1
        self._tracks: list[_Tracklet] = []
        self._frame_idx = 0

    def update(self, detections: list[Detection], frame: Frame) -> list[Track]:
        self._frame_idx += 1

        dets = sorted(detections, key=lambda d: d.confidence, reverse=True)
        high = [d for d in dets if d.confidence >= self.track_thresh]
        low = [d for d in dets if d.confidence < self.track_thresh]

        track_indices = list(range(len(self._tracks)))

        # 阶段一：高置信度检测匹配全部存活 track
        matched, unmatched_tracks, unmatched_high = self._match(high, track_indices)
        for det_idx, t_idx in matched:
            d = high[det_idx]
            self._tracks[t_idx].update(d.bbox, d.confidence, d.class_name, self._frame_idx)

        # 阶段二：低置信度检测匹配剩余 track（维持遮挡中的轨迹）
        matched2, unmatched_tracks, _ = self._match(low, unmatched_tracks)
        for det_idx, t_idx in matched2:
            d = low[det_idx]
            self._tracks[t_idx].update(d.bbox, d.confidence, d.class_name, self._frame_idx)

        # 未匹配的高置信度检测新建轨迹
        for det_idx in unmatched_high:
            d = high[det_idx]
            self._tracks.append(
                _Tracklet(self._next_id, d.bbox, d.confidence, d.class_name, self._frame_idx)
            )
            self._next_id += 1

        # 未匹配的 track 标记丢失
        for t_idx in unmatched_tracks:
            self._tracks[t_idx].mark_missed()

        # 清理超过 buffer 仍丢失的轨迹
        self._tracks = [t for t in self._tracks if t.time_since_update <= self.track_buffer]

        # 返回当前活跃（本帧被匹配或新建）的轨迹
        return [
            Track(
                track_id=t.track_id,
                bbox=tuple(t.bbox),
                confidence=t.score,
                class_name=t.class_name,
                frame_idx=t.frame_idx,
            )
            for t in self._tracks
            if t.is_tracked
        ]

    def _match(
        self,
        dets: list[Detection],
        track_indices: list[int],
    ) -> tuple[list[tuple[int, int]], list[int], list[int]]:
        """返回 (匹配对(det_idx, 全局track_idx), 未匹配track全局idx, 未匹配det_idx)。"""
        if not dets or not track_indices:
            return [], list(track_indices), list(range(len(dets)))

        np = _numpy()
        det_boxes = np.array([d.bbox for d in dets], dtype=np.float64)
        track_boxes = np.array([self._tracks[i].predicted_bbox for i in track_indices], dtype=np.float64)
        iou_matrix = iou_batch(det_boxes, track_boxes)

        matches = greedy_match(iou_matrix, self.match_thresh)
        matched_det = {di for di, _ in matches}
        matched_trk = {ti for _, ti in matches}

        unmatched_dets = [i for i in range(len(dets)) if i not in matched_det]
        unmatched_tracks = [track_indices[ti] for ti in range(len(track_indices)) if ti not in matched_trk]
        return [(di, track_indices[ti]) for di, ti in matches], unmatched_tracks, unmatched_dets
