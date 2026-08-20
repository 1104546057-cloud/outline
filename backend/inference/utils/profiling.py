"""轻量性能计时：累计处理帧数、平均/最近延迟，供状态接口展示。"""

from __future__ import annotations

import threading
import time


class FrameProfiler:
    """线程安全的推理性能统计器。"""

    def __init__(self, window: int = 30) -> None:
        self._lock = threading.Lock()
        self._window = max(1, window)
        self._latencies: list[float] = []
        self._processed = 0
        self._last_error: str | None = None
        self._started_at = time.monotonic()

    def record(self, latency_ms: float) -> None:
        with self._lock:
            self._latencies.append(float(latency_ms))
            if len(self._latencies) > self._window:
                self._latencies.pop(0)
            self._processed += 1

    def record_error(self, message: str) -> None:
        with self._lock:
            self._last_error = message

    def snapshot(self) -> dict:
        with self._lock:
            elapsed = max(time.monotonic() - self._started_at, 1e-6)
            avg = sum(self._latencies) / len(self._latencies) if self._latencies else 0.0
            last = self._latencies[-1] if self._latencies else 0.0
            return {
                "processed_frames": self._processed,
                "measured_fps": round(self._processed / elapsed, 2),
                "avg_latency_ms": round(avg, 1),
                "last_latency_ms": round(last, 1),
                "last_error": self._last_error,
            }
