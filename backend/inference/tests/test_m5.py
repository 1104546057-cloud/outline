"""M5 告警闭环单元测试。

覆盖：
1. 证据截图 capture_evidence（无 cv2 降级、伪造 cv2 正常写入、边界裁剪）
2. notify 订阅/取消/广播（事件循环内）

运行::

    cd backend
    python -m pytest inference/tests/ -v
"""

from __future__ import annotations

import asyncio
import sys
import types

import numpy as np
import pytest

from inference.base import BehaviorEvent
from inference.event_collector import ALERT_SOURCE_TYPE, capture_evidence


# ============================================================
# 证据截图
# ============================================================

class TestCaptureEvidence:
    def test_no_cv2_returns_none(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "cv2", None)
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        event = BehaviorEvent(event_type="fall", bbox=(10, 10, 50, 50))
        assert capture_evidence(frame, event, device_id=1) is None

    def test_capture_with_fake_cv2(self, monkeypatch, tmp_path):
        import inference.event_collector as ec

        written = {}

        fake_cv2 = types.ModuleType("cv2")
        fake_cv2.imwrite = lambda path, img: written.setdefault(path, img) is not None
        monkeypatch.setitem(sys.modules, "cv2", fake_cv2)
        monkeypatch.setattr(ec, "EVIDENCE_DIR", tmp_path / "data" / "video_evidence")
        monkeypatch.setattr(ec, "BASE_DIR", tmp_path)

        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        event = BehaviorEvent(event_type="fall", bbox=(10, 10, 50, 50))
        rel = capture_evidence(frame, event, device_id=1)

        assert rel is not None
        assert rel.startswith("data/video_evidence/")
        assert "fall" in rel
        # 截图实际发生（伪造 imwrite 被调用）
        assert len(written) == 1

    def test_invalid_bbox_returns_none(self, monkeypatch, tmp_path):
        import inference.event_collector as ec

        fake_cv2 = types.ModuleType("cv2")
        fake_cv2.imwrite = lambda path, img: True
        monkeypatch.setitem(sys.modules, "cv2", fake_cv2)
        monkeypatch.setattr(ec, "EVIDENCE_DIR", tmp_path / "data" / "video_evidence")
        monkeypatch.setattr(ec, "BASE_DIR", tmp_path)

        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        # bbox 完全在画面外 → 裁剪区域为空 → 返回 None
        event = BehaviorEvent(event_type="fall", bbox=(500, 500, 600, 600))
        assert capture_evidence(frame, event, device_id=1) is None


# ============================================================
# 告警源类型
# ============================================================

class TestAlertSourceType:
    def test_source_type_value(self):
        assert ALERT_SOURCE_TYPE == "video_inference"


# ============================================================
# notify 广播
# ============================================================

class TestNotify:
    def test_broadcast(self):
        from inference import notify

        async def scenario():
            queue = notify.subscribe()
            notify._broadcast({"type": "video_alert", "payload": {"id": 1}})
            message = queue.get_nowait()
            assert message["type"] == "video_alert"
            assert message["payload"]["id"] == 1

            notify.unsubscribe(queue)
            assert len(notify._subscribers) == 0

        asyncio.run(scenario())

    def test_broadcast_no_subscribers(self):
        from inference import notify

        async def scenario():
            notify._subscribers.clear()
            notify._broadcast({"type": "video_alert"})  # 不抛错
            assert len(notify._subscribers) == 0

        asyncio.run(scenario())
