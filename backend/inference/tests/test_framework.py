"""推理框架单元测试（M1）。

覆盖：
1. 插件注册表（注册、查询、去重、未找到）
2. 配置加载与热更新（默认值合并、按设备解析、持久化）
3. 管线编排（dummy 组件装配、process 不抛错）
4. 事件归集（event_type 映射、高等级才写告警）
5. 帧总线抽帧节流
6. 管理器生命周期（启停、订阅释放）

运行::

    cd backend
    python -m pytest inference/tests/ -v
"""

from __future__ import annotations

import asyncio
import queue as thread_queue

import pytest

from inference.base import BaseDetector, BehaviorEvent, Detection
from inference.config import InferenceConfig, inference_config
from inference.pipeline import build_pipeline
from inference.registry import (
    DuplicatePluginError,
    PluginNotFoundError,
    PluginRegistry,
)


# ============================================================
# 插件注册表
# ============================================================

class TestPluginRegistry:
    def test_register_and_get(self):
        reg = PluginRegistry("detector")

        @reg.register("foo")
        class Foo(BaseDetector):
            def detect(self, frame):
                return []

        assert "foo" in reg
        assert reg.get("foo") is Foo
        assert reg.names() == ["foo"]

    def test_duplicate_raises(self):
        reg = PluginRegistry("tracker")

        @reg.register("dup")
        class A:  # noqa: B903
            pass

        with pytest.raises(DuplicatePluginError):
            reg.register_class("dup", A)

    def test_get_not_found(self):
        reg = PluginRegistry("analyzer")
        with pytest.raises(PluginNotFoundError):
            reg.get("nonexistent")


# ============================================================
# 配置加载与热更新
# ============================================================

class TestConfig:
    def test_default_pipeline_fallback(self):
        cfg = inference_config.get_pipeline_config(999999)
        assert cfg["detector"] == "dummy"
        assert cfg["tracker"] == "dummy"
        assert cfg["analyzers"] == ["dummy"]
        assert cfg["target_fps"] > 0

    def test_load_and_update(self, tmp_path):
        path = tmp_path / "inference.yaml"
        path.write_text(
            "pipelines:\n  default:\n    target_fps: 7\n",
            encoding="utf-8",
        )
        cfg = InferenceConfig(path)
        assert cfg.get_pipeline_config(1)["target_fps"] == 7

        cfg.update({"pipelines": {"default": {"target_fps": 9}}})
        assert cfg.get_pipeline_config(1)["target_fps"] == 9
        # 已持久化到文件
        assert "9" in path.read_text(encoding="utf-8")

    def test_device_pipeline_mapping(self, tmp_path):
        path = tmp_path / "inference.yaml"
        path.write_text(
            "pipelines:\n"
            "  default:\n    target_fps: 5\n"
            "  fast:\n    target_fps: 15\n"
            "devices:\n"
            "  1:\n    pipeline: fast\n",
            encoding="utf-8",
        )
        cfg = InferenceConfig(path)
        assert cfg.get_pipeline_config(1)["target_fps"] == 15
        assert cfg.get_pipeline_config(2)["target_fps"] == 5


# ============================================================
# 管线编排
# ============================================================

class TestPipeline:
    def test_build_with_dummy_components(self):
        cfg = inference_config.get_pipeline_config(1)
        pipeline = build_pipeline(cfg)
        assert pipeline.detector.__class__.__name__ == "DummyDetector"
        assert pipeline.tracker.__class__.__name__ == "DummyTracker"

    def test_process_returns_empty_without_error(self):
        pipeline = build_pipeline(inference_config.get_pipeline_config(1))
        # 未安装 cv2 时 frame 传入原始 bytes，dummy 组件应忽略内容
        events = pipeline.process(b"not-a-real-jpeg")
        assert events == []


# ============================================================
# 事件归集
# ============================================================

class FakeSession:
    def __init__(self):
        self.added = []
        self.committed = False

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        pass

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


class TestEventCollector:
    def test_event_type_mapping(self):
        from inference.event_collector import build_event_type

        assert build_event_type(BehaviorEvent(event_type="fall")) == "video_fall"

    def test_high_severity_writes_alert(self):
        from inference.event_collector import emit

        db = FakeSession()
        event = BehaviorEvent(
            event_type="fall",
            track_ids=[1],
            confidence=0.9,
            severity="high",
            description="疑似摔倒",
        )
        emit(event, device_id=3, db=db)
        # 明细 + 告警，共两条
        assert len(db.added) == 2
        assert db.added[0].event_type == "video_fall"
        assert db.added[1].alert_type == "video_fall"
        assert db.added[1].source_type == "video_inference"
        # 注入会话时不提交（由调用方管理）
        assert not db.committed

    def test_info_severity_no_alert(self):
        from inference.event_collector import emit

        db = FakeSession()
        emit(BehaviorEvent(event_type="dummy", severity="info"), device_id=3, db=db)
        assert len(db.added) == 1
        assert db.added[0].source == "inference"


# ============================================================
# 帧总线抽帧节流
# ============================================================

class TestFrameBusThrottle:
    def test_should_process_interval(self):
        from inference.frame_bus import InferenceFrameBus

        cfg = inference_config.get_pipeline_config(1)
        bus = InferenceFrameBus(1, pipeline_cfg=cfg, pipeline=build_pipeline(cfg))

        # 首帧：_last_infer_time 初始为 0，远早于 now，应处理
        assert bus._should_process(100.0) is True
        bus._last_infer_time = 100.0
        # target_fps=5 → 间隔 0.2s，0.05s 内应跳过
        assert bus._should_process(100.05) is False
        assert bus._should_process(100.25) is True


# ============================================================
# 管理器生命周期（启停 + 订阅释放）
# ============================================================

class TestManagerLifecycle:
    def test_start_and_stop(self, monkeypatch):
        from agent_gateway import agent_gateway
        from inference.manager import InferenceManager

        async def fake_subscribe(device_id, view):
            return thread_queue.Queue(maxsize=1)

        async def fake_unsubscribe(device_id, view, frame_queue):
            pass

        monkeypatch.setattr(agent_gateway, "subscribe_thread_frames", fake_subscribe)
        monkeypatch.setattr(agent_gateway, "unsubscribe_thread_frames", fake_unsubscribe)
        # 避免单测写真实数据库：manager 启停时的运行日志改为空实现
        monkeypatch.setattr("inference.manager.log_run_event", lambda *args, **kwargs: None)

        manager = InferenceManager()

        async def scenario():
            status = await manager.start(1)
            assert status["running"] is True
            assert manager.running_device_ids() == [1]
            assert manager.get_status(1)["running"] is True

            await manager.stop(1)
            assert manager.running_device_ids() == []
            assert manager.get_status(1)["running"] is False

        asyncio.run(scenario())

    def test_stop_not_running_raises(self):
        from fastapi import HTTPException
        from inference.manager import InferenceManager

        manager = InferenceManager()

        async def scenario():
            with pytest.raises(HTTPException) as exc_info:
                await manager.stop(1)
            assert exc_info.value.status_code == 404

        asyncio.run(scenario())
