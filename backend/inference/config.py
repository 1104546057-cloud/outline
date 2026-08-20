"""推理模块配置加载与热更新。

配置文件默认位于 backend/inference/inference.yaml（与推理模块同目录）。
说明：规划文档中写的是 backend/config/inference.yaml，但 backend 已存在 config.py
模块，新建 config/ 目录会与之产生 import 冲突，故将配置收进 inference/ 内。

可通过环境变量 INFERENCE_CONFIG_PATH 覆盖配置文件路径。
"""

from __future__ import annotations

import copy
import os
import threading
from pathlib import Path
from typing import Any

import yaml

INFERENCE_CONFIG_ENV = "INFERENCE_CONFIG_PATH"
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "inference.yaml"

# 默认管线兜底：即使配置文件缺失也能启动一个 dummy 管线。
DEFAULT_CONFIG: dict[str, Any] = {
    "pipelines": {
        "default": {
            "detector": "dummy",
            "tracker": "dummy",
            "analyzers": ["dummy"],
            "enabled": True,
            "target_fps": 5,
            "annotate": False,
        },
    },
    "devices": {},
    "models": {},
    "behaviors": {},
}


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并两个字典，override 优先（用于把用户配置叠加到默认值上）。"""
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class InferenceConfig:
    """推理配置管理器：负责从 YAML 加载、热更新与按设备解析管线配置。"""

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path else Path(os.getenv(INFERENCE_CONFIG_ENV, _DEFAULT_CONFIG_PATH))
        self._lock = threading.RLock()
        self._config: dict[str, Any] = {}
        self.reload()

    @property
    def path(self) -> Path:
        return self._path

    def reload(self) -> dict[str, Any]:
        """从磁盘重新加载配置（热更新），失败时保留上一次有效配置。"""
        loaded: dict[str, Any] = {}
        if self._path.is_file():
            try:
                loaded = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
                if not isinstance(loaded, dict):
                    raise ValueError("推理配置必须是 YAML 映射")
            except Exception as exc:  # noqa: BLE001 - 配置错误不能拖垮服务
                print(f"[inference] 配置加载失败，沿用上次配置: {exc}")
                return self.snapshot()
        with self._lock:
            self._config = _deep_merge(DEFAULT_CONFIG, loaded)
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        """返回当前完整配置的深拷贝。"""
        with self._lock:
            return copy.deepcopy(self._config)

    def update(self, new_config: dict[str, Any]) -> dict[str, Any]:
        """用新配置整体替换并写回文件（热加载 + 持久化）。"""
        if not isinstance(new_config, dict):
            raise ValueError("配置必须是 JSON 对象")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            yaml.safe_dump(new_config, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return self.reload()

    def get_pipeline_config(self, device_id: int) -> dict[str, Any]:
        """返回某设备应使用的管线配置（已合并默认值）。"""
        with self._lock:
            devices = self._config.get("devices", {}) or {}
            pipelines = self._config.get("pipelines", {}) or {}
            device_cfg = devices.get(str(device_id)) or devices.get(device_id) or {}
            pipeline_name = device_cfg.get("pipeline", "default") if isinstance(device_cfg, dict) else "default"
            base = pipelines.get(pipeline_name) or pipelines.get("default") or {}

        if not isinstance(base, dict):
            raise ValueError(f"管线 '{pipeline_name}' 配置非法")
        result = copy.deepcopy(base)
        result.setdefault("name", pipeline_name)
        result.setdefault("detector", "dummy")
        result.setdefault("tracker", "dummy")
        result.setdefault("analyzers", ["dummy"])
        result.setdefault("enabled", True)
        result.setdefault("target_fps", 5)
        result.setdefault("annotate", False)
        return result

    def get_models(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._config.get("models", {}) or {})

    def get_behaviors(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._config.get("behaviors", {}) or {})


# 进程内单例
inference_config = InferenceConfig()
