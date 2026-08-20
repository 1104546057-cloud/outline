"""行为分析器插件包。导入本包即触发内置分析器注册。"""

from inference.analyzers.behavior_crowd import CrowdAnalyzer  # noqa: F401
from inference.analyzers.behavior_fall import FallAnalyzer  # noqa: F401
from inference.analyzers.behavior_run import RunAnalyzer  # noqa: F401
from inference.analyzers.dummy_analyzer import DummyAnalyzer  # noqa: F401

__all__ = ["CrowdAnalyzer", "FallAnalyzer", "RunAnalyzer", "DummyAnalyzer"]
