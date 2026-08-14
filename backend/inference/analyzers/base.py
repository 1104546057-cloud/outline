"""行为分析器基类：统一帧计数、冷却期与状态清理。

各行为分析器继承本类，只需实现 _analyze(tracks, frame) 返回事件列表。
"""

from __future__ import annotations

from typing import Any

from inference.base import BaseAnalyzer, BehaviorEvent, Frame, Track


class BaseBehaviorAnalyzer(BaseAnalyzer):
    """提供帧计数、按 key 冷却、按 track 状态清理的行为分析器基类。"""

    def __init__(self, cooldown_frames: int = 0, stale_frames: int = 300, **kwargs) -> None:  # noqa: ARG002
        self.cooldown_frames = int(cooldown_frames)
        self.stale_frames = int(stale_frames)
        self._frame_idx = 0
        self._last_emit: dict[Any, int] = {}
        self._last_seen: dict[Any, int] = {}

    def analyze(self, tracks: list[Track], frame: Frame) -> list[BehaviorEvent]:
        self._frame_idx += 1
        return self._analyze(tracks, frame)

    def _analyze(self, tracks: list[Track], frame: Frame) -> list[BehaviorEvent]:  # pragma: no cover - 抽象
        raise NotImplementedError

    # ===== 冷却期 =====

    def _can_emit(self, key: Any) -> bool:
        """同 key 在 cooldown_frames 帧内只放行一次；放行时记录当前帧。"""
        if self.cooldown_frames > 0:
            last = self._last_emit.get(key)
            if last is not None and self._frame_idx - last < self.cooldown_frames:
                return False
        self._last_emit[key] = self._frame_idx
        return True

    # ===== 状态清理 =====

    def _touch(self, key: Any) -> None:
        self._last_seen[key] = self._frame_idx

    def _prune(self, mapping: dict) -> None:
        """移除久未更新的 key（超过 stale_frames 帧未出现）。"""
        stale = [
            k for k in list(mapping)
            if self._frame_idx - self._last_seen.get(k, 0) > self.stale_frames
        ]
        for k in stale:
            mapping.pop(k, None)
