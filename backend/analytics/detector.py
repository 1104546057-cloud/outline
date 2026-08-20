"""异常数据识别引擎。

支持四种规则类型：
- threshold:    阈值越界，命中立即告警
- zscore:       与基线均值/标准差比较，|z| 超阈值触发
- consecutive:  连续 N 个窗口命中条件才触发
- ratio:        与基线值比较，下降/上升比例超阈值

命中后自动写入 SecurityAlert，由上层调度器调用。
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from models import AnalyticsRule, AnalyticsMetricDaily, SecurityAlert, AnalyticsIndicator


class DetectorError(Exception):
    pass


def _latest_value(db: Session, indicator_id: int) -> float | None:
    """取最近一次聚合值。"""
    row = db.query(AnalyticsMetricDaily).filter(
        AnalyticsMetricDaily.indicator_id == indicator_id,
        AnalyticsMetricDaily.dimension_key == "all",
    ).order_by(AnalyticsMetricDaily.date.desc()).first()
    return float(row.value) if row and row.value is not None else None


def _baseline_series(db: Session, indicator_id: int, window_days: int) -> list[float]:
    """取最近 window_days 天的聚合值序列（按日期升序）。"""
    rows = db.query(AnalyticsMetricDaily).filter(
        AnalyticsMetricDaily.indicator_id == indicator_id,
        AnalyticsMetricDaily.dimension_key == "all",
    ).order_by(AnalyticsMetricDaily.date.desc()).limit(window_days).all()
    values = [float(r.value) for r in reversed(rows) if r.value is not None]
    return values


def _check_threshold(condition: dict, value: float) -> bool:
    op = condition.get("op", "<")
    threshold = float(condition.get("value", 0))
    if op == "<":
        return value < threshold
    if op == ">":
        return value > threshold
    if op == "<=":
        return value <= threshold
    if op == ">=":
        return value >= threshold
    if op == "==":
        return math.isclose(value, threshold)
    return False


def _check_zscore(condition: dict, series: list[float], value: float) -> bool:
    if len(series) < 3:
        return False
    mean = statistics.mean(series)
    stdev = statistics.stdev(series)
    if stdev == 0:
        return False
    z = (value - mean) / stdev
    threshold = float(condition.get("z_threshold", 2))
    # z_threshold 为正数；负值表示下降偏离
    if threshold > 0:
        return z > threshold
    return z < threshold


def _check_consecutive(db: Session, condition: dict, series: list[float]) -> bool:
    """连续 N 天命中条件才触发。series 最后一个元素是最新值。"""
    consecutive_days = int(condition.get("consecutive_days", 3))
    if len(series) < consecutive_days:
        return False
    for v in series[-consecutive_days:]:
        if not _check_threshold(condition, v):
            return False
    return True


def _check_ratio(condition: dict, series: list[float], value: float) -> bool:
    if len(series) < 2:
        return False
    baseline = statistics.mean(series[:-1])
    if baseline == 0:
        return False
    drop_pct = float(condition.get("drop_pct", 0))
    if drop_pct > 0:
        # 下降百分比触发
        return (baseline - value) / baseline >= drop_pct
    # 上升百分比触发
    rise_pct = float(condition.get("rise_pct", 0))
    return (value - baseline) / baseline >= rise_pct


def evaluate_rule(db: Session, rule: AnalyticsRule) -> dict | None:
    """评估单条规则，命中则写入 SecurityAlert 并返回详情；否则返回 None。

    返回结构：{"rule_id", "indicator_id", "value", "severity", "alert_id"}
    """
    if not rule.is_active:
        return None

    indicator = rule.indicator
    if not indicator or not indicator.is_active:
        return None

    value = _latest_value(db, indicator.id)
    if value is None:
        return None

    condition = rule.condition or {}
    rule_type = rule.rule_type
    window_days = int(condition.get("window_days", condition.get("window_minutes", 7) if "window_minutes" not in condition else 7))
    series = _baseline_series(db, indicator.id, max(window_days, 7))

    hit = False
    if rule_type == "threshold":
        hit = _check_threshold(condition, value)
    elif rule_type == "zscore":
        hit = _check_zscore(condition, series, value)
    elif rule_type == "consecutive":
        hit = _check_consecutive(db, condition, series)
    elif rule_type == "ratio":
        hit = _check_ratio(condition, series, value)
    else:
        raise DetectorError(f"未支持的规则类型: {rule_type}")

    if not hit:
        return None

    # 同源同指标 30 分钟内已有 pending/acknowledged 告警则去重，避免告警风暴
    duplicate = db.query(SecurityAlert).filter(
        SecurityAlert.source_type == "analytics_rule",
        SecurityAlert.source_id == str(rule.id),
        SecurityAlert.status.in_(["pending", "acknowledged"]),
    ).first()
    if duplicate:
        return None

    alert = SecurityAlert(
        alert_type=rule.alert_type or "analytics_rule",
        severity=rule.severity,
        title=f"[研判] {rule.name}",
        description=(rule.description or "") + f" | 当前值={value} {indicator.unit or ''}",
        source_type="analytics_rule",
        source_id=str(rule.id),
        occurred_at=datetime.now(),
        status="pending",
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)

    return {
        "rule_id": rule.id,
        "indicator_id": indicator.id,
        "value": value,
        "severity": rule.severity,
        "alert_id": alert.id,
    }


def run_all_rules(db: Session) -> list[dict]:
    """批量评估所有启用规则，返回命中列表。"""
    rules = db.query(AnalyticsRule).filter(AnalyticsRule.is_active == True).all()  # noqa: E712
    hits = []
    for rule in rules:
        try:
            result = evaluate_rule(db, rule)
            if result:
                hits.append(result)
        except Exception as e:
            print(f"[detector] 规则 {rule.id}({rule.name}) 评估失败: {e}")
    return hits
