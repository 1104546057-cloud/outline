#!/usr/bin/env python3
"""
probe_gnss.py — 校园室外巡检 · 阶段 A GNSS 能力探测脚本
================================================================
本脚本用于在车端一次性采集 GNSS / IMU / 里程计的实际能力，输出
JSON 格式报告，作为阶段 A 闸门 A-1 的关键证据：

  1. 枚举当前 ROS master 上与定位相关的话题与消息类型
  2. 订阅 /gps/fix 一段时间，统计：
       - 实际刷新频率（Hz）
       - fix 状态枚举分布（NO_FIX / GPS / DGPS / RTK_FLOAT / RTK_FIXED 等）
       - 位置精度（position_covariance_trace 或 hdop）
       - 数据年龄分布
  3. 订阅 /imu 与 /odom，校验时间戳是否与 /gps/fix 对齐
  4. 输出 JSON 报告（写入控制台和可选 --out 文件）

用法（车端启动底盘 + GNSS 驱动后运行）：

  python3 probe_gnss.py --duration 60 --out gnss_capability_report.json

依赖：
  - rospy（ROS1 noetic）
  - sensor_msgs, nav_msgs, geometry_msgs
  - numpy（仅用于方差统计，可选）

输出 JSON 结构示例：

  {
    "ros_master_uri": "http://localhost:11311",
    "collected_at": "2026-08-12T17:00:00+08:00",
    "duration_seconds": 60,
    "topics": [
      {"name": "/gps/fix", "type": "sensor_msgs/NavSatFix", "publishers": 1},
      ...
    ],
    "gnss": {
      "topic": "/gps/fix",
      "samples": 58,
      "avg_rate_hz": 0.97,
      "fix_status_counts": {"RTK_FIXED": 50, "RTK_FLOAT": 8},
      "avg_position_covariance_trace": 0.0025,
      "max_data_age_seconds": 1.3,
      "avg_data_age_seconds": 0.21
    },
    "imu": {"topic": "/imu", "samples": 600, "avg_rate_hz": 100.0},
    "odom": {"topic": "/odom", "samples": 60, "avg_rate_hz": 10.0},
    "alignment": {"imu_lag_seconds": 0.02, "odom_lag_seconds": 0.05}
  }

注意：
  - 本脚本不写入任何控制指令，纯订阅采集，对车体安全无影响。
  - 若车端未安装 numpy，统计部分会降级为最大/最小/计数；不影响主流程。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

try:
    import rospy
    import rostopic
    from sensor_msgs.msg import NavSatFix, NavSatStatus, Imu
    from nav_msgs.msg import Odometry
    ROSPY_AVAILABLE = True
except ImportError:
    ROSPY_AVAILABLE = False

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False


# NavSatFix / NavSatStatus 的 status 枚举（ROS1 noetic）
FIX_STATUS_NAMES = {
    NavSatStatus.STATUS_NO_FIX: "NO_FIX",
    NavSatStatus.STATUS_FIX: "GPS",
    NavSatStatus.STATUS_SBAS_FIX: "SBAS",
    NavSatStatus.STATUS_GBAS_FIX: "GBAS",
    NavSatStatus.STATUS_GPS_SATELLITE_FIX: "GPS",
    NavSatStatus.STATUS_GLONASS_SATELLITE_FIX: "GLONASS",
    NavSatStatus_STATUS_GPS_GLONASS_SATELLITE_FIX: "GPS_GLONASS",
    NavSatStatus.STATUS_GPS_PSEUDORANGE_DIFFERENTIAL: "DGPS",
    NavSatStatus.STATUS_RTK_FLOAT: "RTK_FLOAT",
    NavSatStatus.STATUS_RTK_FIXED: "RTK_FIXED",
    NavSatStatus.STATUS_PSEUDORANGE_DIFFERENTIAL: "DGPS",
} if ROSPY_AVAILABLE else {}

# 兼容不同 ROS 版本：缺失的常量回退为字符串
def _safe_fix_name(status_value: int) -> str:
    """将 NavSatStatus.status 数值映射为可读名称。"""
    # 标准 noetic 常量
    mapping = {
        -1: "NO_FIX",
        0: "NO_FIX",
        1: "GPS",      # STATUS_FIX
        2: "DGPS",     # STATUS_SBAS_FIX 在部分驱动中也表示差分
        3: "DGPS",
        4: "RTK_FLOAT",  # 注意：编号在不同版本可能不一致
        5: "RTK_FIXED",
        # 高位标识位（位运算）已剥离子分类
    }
    return mapping.get(status_value, f"UNKNOWN({status_value})")


def list_localization_topics() -> List[Dict[str, Any]]:
    """枚举 ROS master 上的定位相关话题。"""
    if not ROSPY_AVAILABLE:
        return []
    try:
        pub_topics = rospy.get_published_topics()
    except Exception as e:
        rospy.logwarn(f"无法获取话题列表: {e}")
        return []

    candidates = ("/gps", "/imu", "/odom", "/fix", "/gnss", "/navsat",
                  "/odometry", "/localized_pose")
    result = []
    for name, msg_type in pub_topics:
        if any(tag in name.lower() for tag in ("gps", "imu", "odom", "fix",
                                                "gnss", "navsat", "odometry",
                                                "localization", "pose")):
            publishers = 0
            try:
                pubs_subs = rostopic.get_info_text(name)
                # 简单解析 rostopic 输出统计
                if "Publishers:" in pubs_subs:
                    publishers = pubs_subs.count("*")
            except Exception:
                pass
            result.append({"name": name, "type": msg_type, "publishers": publishers})
    return result


class _Collector:
    """轻量数据采集器：分别收集 GNSS、IMU、ODOM 样本。"""
    def __init__(self, duration: float):
        self.duration = duration
        self.gnss_samples: List[Dict[str, Any]] = []
        self.imu_samples: List[Dict[str, Any]] = []
        self.odom_samples: List[Dict[str, Any]] = []
        self.last_gnss_stamp: Optional[float] = None
        self.gnss_fix_counts: Counter = Counter()
        self.cov_trace_list: List[float] = []
        self.age_list: List[float] = []
        self.imu_stamp_lags: List[float] = []
        self.odom_stamp_lags: List[float] = []

    def _ros_now(self) -> float:
        return rospy.Time.now().to_sec()

    def on_gnss(self, msg: NavSatFix) -> None:
        now = self._ros_now()
        stamp = msg.header.stamp.to_sec() if msg.header.stamp else now
        status_name = _safe_fix_name(msg.status.status if hasattr(msg, "status") else -1)
        # position_covariance 是 3x3 行优先；trace = Σ diagonal
        cov_trace = None
        try:
            if msg.position_covariance_type in (0, 1, 2):
                cov = msg.position_covariance
                cov_trace = float(cov[0] + cov[4] + cov[8])
        except Exception:
            cov_trace = None

        self.gnss_samples.append({
            "stamp": stamp,
            "now": now,
            "age": now - stamp,
            "status": status_name,
            "latitude": msg.latitude,
            "longitude": msg.longitude,
            "altitude": msg.altitude,
            "cov_trace": cov_trace,
        })
        self.gnss_fix_counts[status_name] += 1
        if cov_trace is not None:
            self.cov_trace_list.append(cov_trace)
        self.age_list.append(now - stamp)
        self.last_gnss_stamp = stamp

    def on_imu(self, msg: Imu) -> None:
        now = self._ros_now()
        stamp = msg.header.stamp.to_sec() if msg.header.stamp else now
        self.imu_samples.append({"stamp": stamp, "now": now})
        if self.last_gnss_stamp:
            self.imu_stamp_lags.append(abs(stamp - self.last_gnss_stamp))

    def on_odom(self, msg: Odometry) -> None:
        now = self._ros_now()
        stamp = msg.header.stamp.to_sec() if msg.header.stamp else now
        self.odom_samples.append({"stamp": stamp, "now": now})
        if self.last_gnss_stamp:
            self.odom_stamp_lags.append(abs(stamp - self.last_gnss_stamp))

    def summarize(self) -> Dict[str, Any]:
        def _avg(xs):
            return float(sum(xs) / len(xs)) if xs else None

        def _max(xs):
            return float(max(xs)) if xs else None

        def _pct(arr, p):
            if not arr:
                return None
            if NUMPY_AVAILABLE:
                return float(np.percentile(arr, p))
            arr_sorted = sorted(arr)
            k = max(0, min(len(arr_sorted) - 1, int((p / 100.0) * len(arr_sorted))))
            return float(arr_sorted[k])

        gnss_rate = None
        if len(self.gnss_samples) >= 2:
            span = self.gnss_samples[-1]["now"] - self.gnss_samples[0]["now"]
            gnss_rate = (len(self.gnss_samples) - 1) / span if span > 0 else None

        imu_rate = None
        if len(self.imu_samples) >= 2:
            span = self.imu_samples[-1]["now"] - self.imu_samples[0]["now"]
            imu_rate = (len(self.imu_samples) - 1) / span if span > 0 else None

        odom_rate = None
        if len(self.odom_samples) >= 2:
            span = self.odom_samples[-1]["now"] - self.odom_samples[0]["now"]
            odom_rate = (len(self.odom_samples) - 1) / span if span > 0 else None

        return {
            "gnss": {
                "topic": "/gps/fix",
                "samples": len(self.gnss_samples),
                "avg_rate_hz": gnss_rate,
                "fix_status_counts": dict(self.gnss_fix_counts),
                "avg_position_covariance_trace": _avg(self.cov_trace_list),
                "max_position_covariance_trace": _max(self.cov_trace_list),
                "p95_position_covariance_trace": _pct(self.cov_trace_list, 95),
                "avg_data_age_seconds": _avg(self.age_list),
                "max_data_age_seconds": _max(self.age_list),
            },
            "imu": {
                "topic": "/imu",
                "samples": len(self.imu_samples),
                "avg_rate_hz": imu_rate,
            },
            "odom": {
                "topic": "/odom",
                "samples": len(self.odom_samples),
                "avg_rate_hz": odom_rate,
            },
            "alignment": {
                "imu_lag_seconds_avg": _avg(self.imu_stamp_lags),
                "odom_lag_seconds_avg": _avg(self.odom_stamp_lags),
            },
        }


def run_probe(duration: float, gnss_topic: str, imu_topic: str,
              odom_topic: str) -> Dict[str, Any]:
    """执行时长为 duration 秒的探测，返回完整报告字典。"""
    if not ROSPY_AVAILABLE:
        raise RuntimeError("未检测到 rospy / sensor_msgs，请在车端 ROS1 环境运行")

    rospy.init_node("dwc_probe_gnss", anonymous=True)
    rospy.loginfo(
        "GNSS 能力探测启动：duration=%.1fs gnss=%s imu=%s odom=%s",
        duration, gnss_topic, imu_topic, odom_topic
    )

    collector = _Collector(duration)
    subs = [
        rospy.Subscriber(gnss_topic, NavSatFix, collector.on_gnss),
        rospy.Subscriber(imu_topic, Imu, collector.on_imu),
        rospy.Subscriber(odom_topic, Odometry, collector.on_odom),
    ]

    deadline = time.time() + duration
    while time.time() < deadline and not rospy.is_shutdown():
        time.sleep(0.5)

    for s in subs:
        s.unregister()

    topics = list_localization_topics()
    summary = collector.summarize()
    report: Dict[str, Any] = {
        "ros_master_uri": os.environ.get("ROS_MASTER_URI", "http://localhost:11311"),
        "collected_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "duration_seconds": duration,
        "topics": topics,
    }
    report.update(summary)

    # 闸门判定（按需求 FR-01 与阶段 A 退出条件给出初步结论）
    gnss = summary["gnss"]
    supports_rtk = any(
        name in gnss["fix_status_counts"]
        for name in ("RTK_FIXED", "RTK_FLOAT")
    )
    report["gate_a_preliminary"] = {
        "supports_rtk": supports_rtk,
        "rate_acceptable": (gnss["avg_rate_hz"] or 0) >= 1.0,
        "note": (
            "通过初步闸门：支持 RTK 且刷新率 ≥1Hz。"
            if supports_rtk and (gnss["avg_rate_hz"] or 0) >= 1.0
            else "未通过初步闸门，请在 gnss_capability.md 中说明并升级方案。"
        ),
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="校园室外巡检 GNSS 能力探测（阶段 A）")
    parser.add_argument("--duration", type=float, default=60.0,
                        help="采集时长（秒），默认 60")
    parser.add_argument("--gnss-topic", default="/gps/fix",
                        help="GNSS NavSatFix 话题名（默认 /gps/fix）")
    parser.add_argument("--imu-topic", default="/imu",
                        help="IMU 话题名（默认 /imu，实际可能为 /imu/data）")
    parser.add_argument("--odom-topic", default="/odom",
                        help="里程计话题名（默认 /odom）")
    parser.add_argument("--out", default=None,
                        help="可选：将完整 JSON 报告写入指定文件")
    args = parser.parse_args()

    try:
        report = run_probe(
            duration=args.duration,
            gnss_topic=args.gnss_topic,
            imu_topic=args.imu_topic,
            odom_topic=args.odom_topic,
        )
    except RuntimeError as e:
        print(f"[probe_gnss] 错误: {e}", file=sys.stderr)
        return 2

    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"\n报告已保存到 {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
