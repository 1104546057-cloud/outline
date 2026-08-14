"""帧解码工具。

惰性加载 cv2 + numpy：安装后把 JPEG 字节解码为 BGR ndarray，
未安装时原样返回 bytes，保证 M1 的 dummy 管线在最小依赖环境下也能跑通。
"""

from __future__ import annotations

from typing import Any


def decode_jpeg(data: bytes) -> Any:
    """把 JPEG 字节解码为 BGR ndarray（可用时），否则返回原始 bytes。"""
    if not data:
        return data
    try:
        import cv2
        import numpy as np

        arr = np.frombuffer(data, dtype=np.uint8)
        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if image is not None:
            return image
    except Exception:  # noqa: BLE001 - 解码失败按原始字节处理
        pass
    return data


def is_ndarray(frame: Any) -> bool:
    """判断 frame 是否已解码为 numpy 数组。"""
    return type(frame).__module__ == "numpy" and hasattr(frame, "shape")


def encode_jpeg(frame: Any, quality: int = 85) -> bytes | None:
    """把 BGR ndarray 编码为 JPEG 字节（未安装 cv2 时返回 None）。"""
    try:
        import cv2

        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if ok:
            return buf.tobytes()
    except Exception:  # noqa: BLE001
        pass
    return None
