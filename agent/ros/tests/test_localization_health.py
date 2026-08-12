#!/usr/bin/env python3
"""
test_localization_health.py — localization_health 节点的纯 Python 单元测试
==================================================================================
本测试不依赖 rospy 与 ROS 环境，可在外壳 Python 上直接运行。

测试目标（对应 FR-01 与开发计划 §C-12）：
  在没有真实 GPS 信号的情况下，验证 HealthMonitor 的"判定为 false"逻辑
  能在下列四种触发条件下被正确激活：

    1. GNSS 数据年龄超过阈值
    2. GNSS fix 状态低于阈值（如只有 GPS 没有 RTK）
    3. 协方差迹超过阈值
    4. 融合输出频率低于阈值

以及一种"全部正常"的反向场景验证。

实现思路：
  - 把 localization_health.py 中的 HealthMonitor 类做最小化导入；
    若 rospy 不可用，则通过 mock 替换 rospy 关键 API。
  - 直接调用 _evaluate() 方法比对返回的健康度布尔值与原因列表。
  - 不启动真实 ROS publisher，避免污染车端话题。

运行方式：
    cd agent/ros
    python tests/test_localization_health.py
    # 或
    python -m pytest tests/test_localization_health.py -v
"""

from __future__ import annotations

import math
import os
import sys
import time
from collections import deque
from typing import List
from unittest import mock

# 让脚本能找到上一级目录的 localization_health 模块
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

# ── Mock rospy 与 ROS 消息类型 ──────────────────────────────
# 这样可以脱离真实 ROS 环境运行纯逻辑测试


class _FakeRospy:
    """最小化的 rospy mock"""
    class Time:
        @staticmethod
        def now():
            t = _FakeRospy._time_func()
            class _T:
                def __init__(self, s):
                    self._s = s
                def to_sec(self):
                    return self._s
            return _T(t)

    class Duration:
        def __init__(self, secs):
            self.secs = secs

    class Timer:
        def __init__(self, duration, callback):
            pass  # 测试不触发 Timer

    class Publisher:
        def __init__(self, *a, **k):
            self.published = []
        def publish(self, msg):
            self.published.append(msg)

    class Subscriber:
        def __init__(self, *a, **k):
            pass

    @staticmethod
    def init_node(*a, **k):
        pass

    @staticmethod
    def get_param(key, default):
        # 测试时会直接修改 monitor 的属性，这里返回 default
        return default

    @staticmethod
    def loginfo(*a, **k):
        pass

    @staticmethod
    def is_shutdown():
        return False

    @staticmethod
    def spin():
        pass

    @staticmethod
    def ROSInterruptException(*a, **k):
        return Exception()

    _time_func = time.time


# 把 mock 注入 sys.modules，必须在 import localization_health 之前
sys.modules.setdefault("rospy", _FakeRospy)

# Mock diagnostic_msgs / std_msgs / sensor_msgs（localization_health 顶部 import）
class _FakeMsgModule:
    """消息类型的 mock 容器"""
    def __init__(self):
        self._types = {}
    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in self._types:
            # 返回一个可被实例化的空类
            self._types[name] = type(name, (), {"__init__": lambda self, *a, **k: None})
        return self._types[name]

for mod in ("diagnostic_msgs.msg", "std_msgs.msg", "sensor_msgs.msg",
            "nav_msgs.msg", "geometry_msgs.msg"):
    parent, _, leaf = mod.rpartition(".")
    parent_mod = sys.modules.setdefault(parent, type(parent, (), {}))
    if not isinstance(parent_mod, type(None)):
        sys.modules[mod] = _FakeMsgModule()

# 现在 import localization_health（其内部的 rospy/xxx 都会被 mock 拦截）
try:
    from localization_health import HealthMonitor, STATUS_RANK, _fix_name
except ImportError as e:
    print(f"无法导入 localization_health: {e}")
    print(f"请确认 {PARENT_DIR}/localization_health.py 存在")
    sys.exit(2)


def _make_monitor(
    max_gnss_age: float = 1.0,
    min_status_name: str = "RTK_FLOAT",
    max_cov_trace: float = 0.5,
    min_filtered_rate: float = 5.0,
) -> HealthMonitor:
    """构造一个 HealthMonitor 实例，绕过 rospy.init_node 流程"""
    with mock.patch.object(_FakeRospy, "get_param") as m:
        params = {
            "~max_gnss_age_seconds": max_gnss_age,
            "~min_acceptable_gnss_status": min_status_name,
            "~max_covariance_trace": max_cov_trace,
            "~min_filtered_rate_hz": min_filtered_rate,
            "~calibration_version": "test-v1",
        }
        def fake_get(key, default):
            return params.get(key, default)
        m.side_effect = fake_get
        return HealthMonitor()


def _set_gnss(monitor: HealthMonitor, *, age_seconds: float,
              status: str, cov_trace: float):
    """直接设置 GNSS 状态，模拟一帧"""
    now = time.time()
    with monitor.lock:
        monitor.last_gnss_stamp = now - age_seconds
        monitor.last_gnss_status_name = status
        monitor.last_gnss_cov_trace = cov_trace


def _set_filtered_rate(monitor: HealthMonitor, rate_hz: float, window: int = 50):
    """模拟 /odometry/filtered 的近期时间戳序列"""
    now = time.time()
    if rate_hz <= 0:
        stamps: List[float] = []
    else:
        interval = 1.0 / rate_hz
        stamps = [now - (window - i) * interval for i in range(window)]
    with monitor.lock:
        monitor.filtered_stamps = deque(stamps, maxlen=200)


# ─────────────────────────────────────────────────────────────
# 测试用例
# ─────────────────────────────────────────────────────────────

def test_all_healthy():
    """四个条件全满足时应判定为 healthy=true"""
    m = _make_monitor()
    _set_gnss(m, age_seconds=0.1, status="RTK_FIXED", cov_trace=0.05)
    _set_filtered_rate(m, rate_hz=30.0)
    healthy, reasons = m._evaluate()
    assert healthy, f"应判定为 healthy，但 reasons={reasons}"
    failed = [r for r in reasons if "ok" not in r[2].lower()]
    assert not failed, f"不应有失败项: {failed}"
    print("[PASS] 全部条件满足 → healthy=true")


def test_gnss_age_exceeded():
    """GNSS 年龄超过阈值应判定为 unhealthy"""
    m = _make_monitor(max_gnss_age=1.0)
    _set_gnss(m, age_seconds=2.5, status="RTK_FIXED", cov_trace=0.05)
    _set_filtered_rate(m, rate_hz=30.0)
    healthy, reasons = m._evaluate()
    assert not healthy, "GNSS 年龄 2.5s > 1.0s 应导致 unhealthy"
    age_reason = next(r for r in reasons if r[0] == "gnss_age")
    assert "超过阈值" in age_reason[2], f"应提示超阈：{age_reason}"
    print(f"[PASS] GNSS 年龄超阈触发 → {age_reason[2]}")


def test_gnss_status_low():
    """GNSS fix 低于阈值应判定为 unhealthy"""
    m = _make_monitor(min_status_name="RTK_FLOAT")
    _set_gnss(m, age_seconds=0.1, status="GPS", cov_trace=0.05)
    _set_filtered_rate(m, rate_hz=30.0)
    healthy, reasons = m._evaluate()
    assert not healthy, "fix=GPS 低于 RTK_FLOAT 应导致 unhealthy"
    status_reason = next(r for r in reasons if r[0] == "gnss_fix_status")
    assert "RTK_FLOAT" in status_reason[2]
    print(f"[PASS] GNSS fix GPS < RTK_FLOAT 触发 → {status_reason[2]}")


def test_covariance_exceeded():
    """协方差迹超过阈值应判定为 unhealthy"""
    m = _make_monitor(max_cov_trace=0.5)
    _set_gnss(m, age_seconds=0.1, status="RTK_FIXED", cov_trace=1.2)
    _set_filtered_rate(m, rate_hz=30.0)
    healthy, reasons = m._evaluate()
    assert not healthy, "cov_trace 1.2 > 0.5 应导致 unhealthy"
    cov_reason = next(r for r in reasons if r[0] == "covariance_trace")
    assert "超过阈值" in cov_reason[2]
    print(f"[PASS] 协方差超阈触发 → {cov_reason[2]}")


def test_filtered_rate_low():
    """/odometry/filtered 频率过低应判定为 unhealthy"""
    m = _make_monitor(min_filtered_rate=5.0)
    _set_gnss(m, age_seconds=0.1, status="RTK_FIXED", cov_trace=0.05)
    _set_filtered_rate(m, rate_hz=2.0)
    healthy, reasons = m._evaluate()
    assert not healthy, "filtered 2Hz < 5Hz 应导致 unhealthy"
    rate_reason = next(r for r in reasons if r[0] == "filtered_rate_hz")
    assert "低于阈值" in rate_reason[2]
    print(f"[PASS] 融合频率过低触发 → {rate_reason[2]}")


def test_no_gnss_data_at_all():
    """完全没收到 GNSS 数据时（last_gnss_stamp=None）应判定为 unhealthy"""
    m = _make_monitor()
    # 不调用 _set_gnss，保持初始状态
    _set_filtered_rate(m, rate_hz=30.0)
    healthy, reasons = m._evaluate()
    assert not healthy, "无 GNSS 数据应导致 unhealthy"
    print("[PASS] 无 GNSS 数据 → unhealthy")


def test_status_rank_ordering():
    """STATUS_RANK 应符合 NO_FIX < GPS < DGPS < RTK_FLOAT < RTK_FIXED"""
    assert STATUS_RANK["NO_FIX"] < STATUS_RANK["GPS"]
    assert STATUS_RANK["GPS"] < STATUS_RANK["DGPS"]
    assert STATUS_RANK["DGPS"] < STATUS_RANK["RTK_FLOAT"]
    assert STATUS_RANK["RTK_FLOAT"] < STATUS_RANK["RTK_FIXED"]
    print("[PASS] STATUS_RANK 顺序正确")


def test_fix_name_mapping():
    """_fix_name 应把数值映射为可读字符串"""
    assert _fix_name(-1) == "NO_FIX"
    assert _fix_name(0) == "NO_FIX"
    assert _fix_name(1) == "GPS"
    assert _fix_name(5) == "RTK_FIXED"
    unknown = _fix_name(99)
    assert "UNKNOWN" in unknown
    print(f"[PASS] _fix_name 映射正确（未知值返回 {unknown}）")


# ─────────────────────────────────────────────────────────────

def run_all():
    tests = [
        test_all_healthy,
        test_gnss_age_exceeded,
        test_gnss_status_low,
        test_covariance_exceeded,
        test_filtered_rate_low,
        test_no_gnss_data_at_all,
        test_status_rank_ordering,
        test_fix_name_mapping,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"[ERROR] {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n=== {passed} passed, {failed} failed ===")
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
