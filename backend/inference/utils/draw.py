"""检测/追踪框绘制（标注流渲染）。

惰性加载 cv2：未安装时原样返回输入帧，保证框架在最小环境下可加载。
"""

from __future__ import annotations

from typing import Any, Iterable

from inference.base import Detection, Track

# 稳定的类别配色（BGR），超出范围循环使用
_PALETTE = [
    (0, 200, 0),     # 绿
    (0, 0, 255),     # 红
    (255, 200, 0),   # 青
    (255, 0, 128),   # 紫
    (255, 128, 0),   # 蓝
    (0, 255, 255),   # 黄
]


def _color_for(key: int) -> tuple[int, int, int]:
    return _PALETTE[key % len(_PALETTE)]


def draw_detections(frame: Any, detections: Iterable[Detection]) -> Any:
    """在帧上绘制检测框与类别标签，返回（就地修改后的）帧。"""
    try:
        import cv2
    except Exception:  # noqa: BLE001
        return frame

    for det in detections:
        x1, y1, x2, y2 = (int(round(v)) for v in det.bbox)
        color = _color_for(det.class_id if det.class_id >= 0 else hash(det.class_name) % 6)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label = f"{det.class_name} {det.confidence:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(frame, (x1, max(0, y1 - th - 4)), (x1 + tw, y1), color, -1)
        cv2.putText(frame, label, (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    return frame


def draw_tracks(frame: Any, tracks: Iterable[Track]) -> Any:
    """在帧上绘制追踪框与 track_id。"""
    try:
        import cv2
    except Exception:  # noqa: BLE001
        return frame

    for t in tracks:
        x1, y1, x2, y2 = (int(round(v)) for v in t.bbox)
        color = _color_for(t.track_id)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label = f"#{t.track_id} {t.class_name}"
        cv2.putText(frame, label, (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    return frame
