"""推理管线管理器：维护每台设备运行中的 InferenceFrameBus。"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException

from inference.config import inference_config
from inference.frame_bus import InferenceFrameBus
from inference.track_history import log_run_event


class InferenceManager:
    """按 device_id 管理推理管线的启停与状态查询。"""

    def __init__(self) -> None:
        self._buses: dict[int, InferenceFrameBus] = {}
        self._lock = asyncio.Lock()

    async def start(self, device_id: int) -> dict[str, Any]:
        async with self._lock:
            if device_id in self._buses:
                raise HTTPException(status_code=409, detail="该设备的推理管线已在运行")
            pipeline_cfg = inference_config.get_pipeline_config(device_id)
            if not pipeline_cfg.get("enabled", True):
                raise HTTPException(status_code=409, detail="该设备的推理管线已在配置中禁用")
            bus = InferenceFrameBus(device_id, pipeline_cfg=pipeline_cfg)
            await bus.start()
            self._buses[device_id] = bus
            try:
                await asyncio.to_thread(
                    log_run_event,
                    device_id,
                    "start",
                    {"pipeline": bus.pipeline.name, "target_fps": bus.target_fps},
                )
            except Exception as exc:  # noqa: BLE001 - 日志失败不影响管线
                print(f"[inference] 设备 {device_id} 运行日志写入失败: {exc}")
            return bus.status()

    async def stop(self, device_id: int) -> dict[str, Any]:
        async with self._lock:
            bus = self._buses.pop(device_id, None)
        if bus is None:
            raise HTTPException(status_code=404, detail="该设备未在运行推理管线")
        await bus.stop()
        try:
            await asyncio.to_thread(log_run_event, device_id, "stop", bus.status())
        except Exception:  # noqa: BLE001
            pass
        return {"device_id": device_id, "running": False}

    def get_bus(self, device_id: int) -> InferenceFrameBus | None:
        return self._buses.get(device_id)

    def get_status(self, device_id: int) -> dict[str, Any]:
        bus = self._buses.get(device_id)
        if bus is None:
            return {"device_id": device_id, "running": False, "pipeline": None}
        return bus.status()

    def status_all(self) -> list[dict[str, Any]]:
        return [bus.status() for bus in self._buses.values()]

    def running_device_ids(self) -> list[int]:
        return sorted(self._buses)

    async def stop_all(self) -> None:
        for device_id in list(self._buses):
            try:
                await self.stop(device_id)
            except Exception as exc:  # noqa: BLE001
                print(f"[inference] 停止设备 {device_id} 管线失败: {exc}")


inference_manager = InferenceManager()
