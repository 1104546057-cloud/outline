"""推理插件注册表。

按类别（detector / tracker / analyzer）维护"配置名 → 实现类"映射，
供 pipeline 按 YAML 配置名动态加载算法，做到配置即算法、不改代码即可切换。
"""

from __future__ import annotations

import threading
from typing import Callable, TypeVar

T = TypeVar("T")


class PluginNotFoundError(LookupError):
    """按名称找不到插件时抛出。"""


class DuplicatePluginError(ValueError):
    """重复注册同名插件时抛出。"""


class PluginRegistry:
    """线程安全的插件注册表。"""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._plugins: dict[str, type] = {}
        self._lock = threading.Lock()

    def register(self, name: str) -> Callable[[type[T]], type[T]]:
        """装饰器形式注册：@registry.register("yolo_v8n")。"""

        def decorator(cls: type[T]) -> type[T]:
            self.register_class(name, cls)
            return cls

        return decorator

    def register_class(self, name: str, cls: type) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{self.kind} 插件名不能为空")
        with self._lock:
            if name in self._plugins:
                raise DuplicatePluginError(
                    f"{self.kind} 插件 '{name}' 已注册（{self._plugins[name].__name__}）"
                )
            self._plugins[name] = cls

    def get(self, name: str) -> type:
        with self._lock:
            cls = self._plugins.get(name)
        if cls is None:
            available = ", ".join(sorted(self._plugins)) or "(无)"
            raise PluginNotFoundError(
                f"未找到 {self.kind} 插件 '{name}'，可用: {available}"
            )
        return cls

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._plugins)

    def __contains__(self, name: str) -> bool:
        with self._lock:
            return name in self._plugins

    def __len__(self) -> int:
        with self._lock:
            return len(self._plugins)


detector_registry = PluginRegistry("detector")
tracker_registry = PluginRegistry("tracker")
analyzer_registry = PluginRegistry("analyzer")
