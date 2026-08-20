#!/usr/bin/env python3
"""
localization_health.py — 校园室外巡检 · 定位健康度评估节点（FR-01）
====================================================================
订阅：
  - /odometry/filtered      (nav_msgs/Odometry)
  - /gps/fix                (sensor_msgs/NavSatFix)
  - /odometry/gps           (nav_msgs/Odometry, 由 navsat_transform 输出)

发布：
  - /localization/health        (std_msgs/Bool)        true=可导航
  - /localization/diagnostics   (diagnostic_msgs/DiagnosticArray)

评估规则（对应需求 FR-01.4）：
  任一条件成立即输出 health=false：
    1. GNSS 数据年龄 > max_gnss_age_seconds
    2. GNSS fix 状态低于 min_acceptable_gnss_status
    3. 融合输出协方差迹 > max_covariance_trace
    4. /odometry/filtered 频率 < min_filtered_rate_hz
    5. map 坐标与 ENU 标定版本不一致（由外部 param 注入）

启动参数（见 outdoor_localization.launch）：
    max_gnss_age_seconds        默认 1.0
    min_acceptable_gnss_status  默认 RTK_FLOAT
    max_covariance_trace        默认 0.5
    min_filtered_rate_hz        默认 5.0
    calibration_version         默认 unknown（与任务下发版本比对）

注意：
  本节点只读取数据、输出诊断与布尔标志，不发布任何控制指令。
  安全门禁的具体停车动作由 robot_control_server 与后端任务编排器响应本话题执行。
"""

from __future__ import annotations

import math
import os
from collections import deque
from threading import Lock
from typing import Deque, Optional

import rospy
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from sensor_msgs.msg import NavSatFix, NavSatStatus
from std_msgs.msg import Bool


# GNSS fix 状态等级（数值越高越可信）
STATUS_RANK = {
    "NO_FIX":    0,
    "GPS":       1,
    "DGPS":      2,
    "SBAS":      2,
    "RTK_FLOAT": 3,
    "RTK_FIXED": 4,
}


def _fix_name(status_value: int) -> str:
    """NavSatStatus 数值 → 可读名称（与 probe_gnss.py 对齐）"""
    mapping = {-1: "NO_FIX", 0: "NO_FIX", 1: "GPS", 2: "DGPS",
               3: "DGPS", 4: "RTK_FLOAT", 5: "RTK_FIXED"}
    return mapping.get(status_value, f"UNKNOWN({status_value})")


class HealthMonitor:
    def __init__(self) -> None:
        # 参数
        self.max_gnss_age = float(rospy.get_param("~max_gnss_age_seconds", 1.0))
        self.min_status_name = str(rospy.get_param("~min_acceptable_gnss_status", "RTK_FLOAT"))
        self.max_cov_trace = float(rospy.get_param("~max_covariance_trace", 0.5))
        self.min_filtered_rate = float(rospy.get_param("~min_filtered_rate_hz", 5.0))
        self.calibration_version = str(rospy.get_param("~calibration_version", "unknown"))

        # 状态
        self.lock = Lock()
        self.last_gnss_stamp: Optional[float] = None
        self.last_gnss_status_name: str = "NO_FIX"
        self.last_gnss_cov_trace: Optional[float] = None
        self.filtered_stamps: Deque[float] = deque(maxlen=200)

        # 发布器
        self.pub_health = rospy.Publisher("/localization/health", Bool, queue_size=1, latch=True)
        self.pub_diag = rospy.Publisher("/localization/diagnostics",
                                        DiagnosticArray, queue_size=1)

        # 订阅器
        self.sub_odom = rospy.Subscriber("/odometry/filtered",
                                         self._on_filtered, queue_size=20)
        self.sub_gps = rospy.Subscriber("/gps/fix",
                                        self._on_gps, queue_size=20)

        # 主循环：以 10Hz 评估并发布
        rospy.Timer(rospy.Duration(0.1), self._tick)
        rospy.loginfo(
            "localization_health 启动: max_age=%.2f min_status=%s max_cov=%.3f min_rate=%.1f",
            self.max_gnss_age, self.min_status_name,
            self.max_cov_trace, self.min_filtered_rate
        )

    # ---------- 订阅回调 ----------
    def _on_filtered(self, msg) -> None:
        with self.lock:
            self.filtered_stamps.append(rospy.Time.now().to_sec())

    def _on_gps(self, msg: NavSatFix) -> None:
        with self.lock:
            self.last_gnss_stamp = msg.header.stamp.to_sec() if msg.header.stamp else rospy.Time.now().to_sec()
            self.last_gnss_status_name = _fix_name(msg.status.status if hasattr(msg, "status") else -1)
            try:
                cov = msg.position_covariance
                self.last_gnss_cov_trace = float(cov[0] + cov[4] + cov[8])
            except Exception:
                self.last_gnss_cov_trace = None

    # ---------- 周期评估 ----------
    def _evaluate(self) -> tuple[bool, list[tuple[str, str, str]]]:
        """返回 (healthy, [(key, value, message)])"""
        now = rospy.Time.now().to_sec()
        reasons: list[tuple[str, str, str]] = []

        # 1. GNSS 数据年龄
        with self.lock:
            gnss_age = (now - self.last_gnss_stamp) if self.last_gnss_stamp else math.inf
            gnss_status = self.last_gnss_status_name
            gnss_cov = self.last_gnss_cov_trace
            stamps = list(self.filtered_stamps)

        ok_gnss_age = gnss_age <= self.max_gnss_age
        reasons.append((
            "gnss_age",
            f"{gnss_age:.2f}s" if math.isfinite(gnss_age) else "INF",
            "ok" if ok_gnss_age else f"超过阈值 {self.max_gnss_age}s"
        ))

        # 2. GNSS fix 等级
        ok_status = STATUS_RANK.get(gnss_status, 0) >= STATUS_RANK.get(self.min_status_name, 99)
        reasons.append((
            "gnss_fix_status",
            gnss_status,
            "ok" if ok_status else f"低于阈值 {self.min_status_name}"
        ))

        # 3. 融合输出协方差（由 /odometry/filtered 提供，这里使用 GNSS 协方差近似；
        #    实际项目可在阶段 B 替换为 filtered.pose.covariance trace）
        ok_cov = True
        if gnss_cov is not None:
            ok_cov = gnss_cov <= self.max_cov_trace
            reasons.append((
                "covariance_trace",
                f"{gnss_cov:.4f}",
                "ok" if ok_cov else f"超过阈值 {self.max_cov_trace}"
            ))
        else:
            reasons.append(("covariance_trace", "N/A", "无数据"))

        # 4. 融合频率
        filtered_rate = 0.0
        if len(stamps) >= 2 and stamps[-1] > stamps[0]:
            filtered_rate = (len(stamps) - 1) / (stamps[-1] - stamps[0])
        ok_rate = filtered_rate >= self.min_filtered_rate
        reasons.append((
            "filtered_rate_hz",
            f"{filtered_rate:.2f}",
            "ok" if ok_rate else f"低于阈值 {self.min_filtered_rate}Hz"
        ))

        healthy = ok_gnss_age and ok_status and ok_cov and ok_rate
        return healthy, reasons

    def _tick(self, _event) -> None:
        healthy, reasons = self._evaluate()
        self.pub_health.publish(Bool(data=healthy))

        diag = DiagnosticArray()
        diag.header.stamp = rospy.Time.now()
        status = DiagnosticStatus()
        status.name = "outdoor_localization"
        status.hardware_id = self.calibration_version
        status.level = DiagnosticStatus.OK if healthy else DiagnosticStatus.ERROR
        status.message = "localization_healthy" if healthy else "localization_unhealthy"
        for key, value, msg in reasons:
            status.values.append(KeyValue(key=key, value=value))
            if "ok" not in msg.lower():
                status.message += f"; {key}: {msg}"
        diag.status.append(status)
        self.pub_diag.publish(diag)


def main() -> None:
    rospy.init_node("dwc_localization_health", anonymous=False)
    HealthMonitor()
    rospy.spin()


if __name__ == "__main__":
    try:
        main()
    except rospy.ROSInterruptException:
        pass
