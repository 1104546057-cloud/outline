"""帧总线：从 agent_gateway 订阅车端帧，按 target_fps 抽帧后交给推理管线。

关键设计（见 docs/plans/video-analysis-module-plan.md §3.1.4）：
- 推理运行在线程中（asyncio.to_thread），不阻塞 FastAPI 事件循环；
- 按 target_fps 抽帧降速，降低计算压力；
- 单帧异常被捕获记录，不影响管线持续运行；
- stop 时确保 agent_gateway 订阅被释放，避免泄漏。
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time
from datetime import datetime
from typing import Any

from agent_gateway import agent_gateway
from inference.base import Frame
from inference.config import inference_config
from inference.event_collector import emit
from inference.pipeline import InferencePipeline, build_pipeline
from inference.utils.decode import decode_jpeg, encode_jpeg, is_ndarray
from inference.utils.draw import draw_detections, draw_tracks
from inference.utils.profiling import FrameProfiler
from inference.track_history import log_run_event, upsert_track_history

_FRAME_VIEW = "color"
_QUEUE_GET_TIMEOUT_SECONDS = 1.0
_STOP_WAIT_TIMEOUT_SECONDS = 5.0
_TRACK_PERSIST_EVERY_FRAMES = 10   # 每处理 N 帧把轨迹元数据写入 video_track_history
_ERROR_LOG_MIN_INTERVAL_SECONDS = 60.0  # 运行错误写库的最小间隔（防刷库）


class InferenceFrameBus:
    """单台设备的一条运行中的推理管线。"""

    def __init__(
        self,
        device_id: int,
        pipeline_cfg: dict[str, Any] | None = None,
        pipeline: InferencePipeline | None = None,
        frame_queue: queue.Queue | None = None,
    ) -> None:
        self.device_id = device_id
        self.pipeline_cfg = pipeline_cfg or inference_config.get_pipeline_config(device_id)
        self.target_fps = float(self.pipeline_cfg.get("target_fps", 5))
        self.pipeline = pipeline or build_pipeline(self.pipeline_cfg)

        self._frame_queue: queue.Queue | None = frame_queue
        self._stop_event = threading.Event()
        self._task: asyncio.Task | None = None
        self._last_infer_time = 0.0
        self._profiler = FrameProfiler()
        self._started_at: datetime | None = None
        self._latest_tracks: list = []
        self._track_row_cache: dict[int, int] = {}
        self._frames_since_persist = 0
        self._last_error_logged_at = 0.0
        # 标注流输出（annotate=true 时启用，供 annotated-stream 接口消费）
        self._annotated_queue: queue.Queue | None = (
            queue.Queue(maxsize=1) if self.pipeline_cfg.get("annotate") else None
        )

    # ===== 生命周期 =====

    async def start(self) -> None:
        if self._frame_queue is None:
            self._frame_queue = await agent_gateway.subscribe_thread_frames(self.device_id, _FRAME_VIEW)
        self._stop_event.clear()
        self._started_at = datetime.now()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop_event.set()
        task = self._task
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=_STOP_WAIT_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
        self._task = None

    async def _run(self) -> None:
        try:
            await asyncio.to_thread(self._run_sync)
        finally:
            frame_queue = self._frame_queue
            self._frame_queue = None
            if frame_queue is not None:
                try:
                    await agent_gateway.unsubscribe_thread_frames(self.device_id, _FRAME_VIEW, frame_queue)
                except Exception:  # noqa: BLE001 - 释放失败只记录
                    print(f"[inference] 设备 {self.device_id} 释放帧订阅失败")

    # ===== 工作循环（线程内执行） =====

    def _run_sync(self) -> None:
        while not self._stop_event.is_set():
            if self._frame_queue is None:
                break
            try:
                media_frame = self._frame_queue.get(timeout=_QUEUE_GET_TIMEOUT_SECONDS)
            except queue.Empty:
                continue
            now = time.monotonic()
            if not self._should_process(now):
                continue  # 抽帧降速，丢弃过密帧
            self._last_infer_time = now
            self._process_frame(media_frame)

    def _should_process(self, now: float) -> bool:
        interval = 1.0 / max(self.target_fps, 0.1)
        return now - self._last_infer_time >= interval

    def _process_frame(self, media_frame: Any) -> None:
        started = time.perf_counter()
        try:
            frame: Frame = decode_jpeg(media_frame.data)
            detections, tracks, events = self.pipeline.run(frame)
            self._latest_tracks = tracks
            for event in events:
                event.occurred_at = event.occurred_at or datetime.now()
                emit(event, device_id=self.device_id, frame=frame)
            self._publish_annotated(frame, detections, tracks)
            self._persist_tracks_maybe()
        except Exception as exc:  # noqa: BLE001 - 单帧失败不中断管线
            message = f"{type(exc).__name__}: {exc}"
            self._profiler.record_error(message)
            print(f"[inference] 设备 {self.device_id} 帧处理异常: {message}")
            self._log_run_error(message)
        finally:
            self._profiler.record((time.perf_counter() - started) * 1000.0)

    def _persist_tracks_maybe(self) -> None:
        """每隔 N 帧把当前活跃轨迹元数据写入 video_track_history。"""
        self._frames_since_persist += 1
        if self._frames_since_persist < _TRACK_PERSIST_EVERY_FRAMES:
            return
        self._frames_since_persist = 0
        try:
            upsert_track_history(
                self.device_id,
                self._latest_tracks,
                self._track_row_cache,
                frames_delta=_TRACK_PERSIST_EVERY_FRAMES,
            )
        except Exception as exc:  # noqa: BLE001 - 持久化失败不中断推理
            print(f"[inference] 设备 {self.device_id} 轨迹持久化失败: {exc}")

    def _log_run_error(self, message: str) -> None:
        """按最小间隔把运行错误写入 inference_run_log（防刷库）。"""
        now = time.monotonic()
        if now - self._last_error_logged_at < _ERROR_LOG_MIN_INTERVAL_SECONDS:
            return
        self._last_error_logged_at = now
        try:
            log_run_event(self.device_id, "error", {"error_msg": message})
        except Exception:  # noqa: BLE001
            pass

    def _publish_annotated(self, frame: Frame, detections: list, tracks: list) -> None:
        """把带标注框的画面编码为 JPEG，推入标注队列（仅保留最新帧）。"""
        if self._annotated_queue is None or not is_ndarray(frame):
            return
        annotated = draw_tracks(draw_detections(frame, detections), tracks)
        jpeg = encode_jpeg(annotated)
        if not jpeg:
            return
        if self._annotated_queue.full():
            try:
                self._annotated_queue.get_nowait()
            except queue.Empty:
                pass
        try:
            self._annotated_queue.put_nowait(jpeg)
        except queue.Full:
            pass

    # ===== 状态 =====

    @property
    def annotated_queue(self) -> queue.Queue | None:
        return self._annotated_queue

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def latest_tracks(self) -> list[dict[str, Any]]:
        """返回当前活跃追踪目标（供 /tracks 接口查询）。"""
        return [
            {
                "track_id": t.track_id,
                "bbox": list(t.bbox),
                "confidence": round(float(t.confidence), 4),
                "class_name": t.class_name,
                "frame_idx": t.frame_idx,
            }
            for t in self._latest_tracks
        ]

    def status(self) -> dict[str, Any]:
        snapshot = self._profiler.snapshot()
        return {
            "device_id": self.device_id,
            "running": self.is_running(),
            "pipeline": self.pipeline.name,
            "target_fps": self.target_fps,
            "annotate": self._annotated_queue is not None,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            **snapshot,
        }
