"""纯 Python 非极大值抑制（NMS）。

不依赖 OpenCV，输入为 numpy 数组（boxes 为 (N,4) xyxy、scores 为 (N,)），
按分数降序贪心保留，返回保留框的下标。
"""

from __future__ import annotations

from typing import Any


def nms(boxes: Any, scores: Any, iou_threshold: float = 0.45) -> list[int]:
    """对一组边界框做 NMS，返回保留框的原始下标（按分数降序）。"""
    import numpy as np

    boxes = np.asarray(boxes, dtype=np.float64)
    scores = np.asarray(scores, dtype=np.float64)
    if boxes.ndim != 2 or boxes.shape[1] != 4 or boxes.shape[0] == 0:
        return []
    if boxes.shape[0] != scores.shape[0]:
        raise ValueError("boxes 与 scores 数量不一致")

    order = scores.argsort()[::-1]
    keep: list[int] = []

    x1 = boxes[:, 0]
    y1 = boxes[:, 1]
    x2 = boxes[:, 2]
    y2 = boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)

    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]

        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])

        inter_w = np.maximum(0.0, xx2 - xx1)
        inter_h = np.maximum(0.0, yy2 - yy1)
        inter = inter_w * inter_h
        union = areas[i] + areas[rest] - inter
        iou = inter / np.maximum(union, 1e-9)

        order = rest[np.where(iou <= iou_threshold)[0]]

    return keep


def iou(box_a: Any, box_b: Any) -> float:
    """两个 xyxy 框的交并比。"""
    import numpy as np

    a = np.asarray(box_a, dtype=np.float64)
    b = np.asarray(box_b, dtype=np.float64)
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    union = area_a + area_b - inter
    return float(inter / union) if union > 1e-9 else 0.0
