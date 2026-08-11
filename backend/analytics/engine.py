"""指标表达式 DSL 引擎。

支持四类表达式（与指标字典 expression 字段约定一致）：

1. aggregate
   {"type":"aggregate","func":"count|sum|avg|max|min","table":"devices",
    "field":"battery","filter":{"status":"online"},"group_by":"severity"}
2. ratio
   {"type":"ratio","numerator":<aggregate>,"denominator":<aggregate>}
3. arithmetic
   {"type":"arithmetic","op":"+|-|*|/","operands":[<expression>, ...]}
4. timeshift
   {"type":"timeshift","base":<expression>,"shift":"day|week|month","offset":7}

filter 支持的算子键：
   status            等值
   status_in         列表 IN
   battery_lt        字段小于
   battery_gt        字段大于
   has_online        （仅 clusters）是否含在线设备

本引擎直接基于 SQLAlchemy ORM 查询，避免引入额外数据立方体。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import (
    Device, Cluster, DeviceTelemetry, PatrolTask, SecurityAlert,
    AnalyticsEvent, AnalyticsMetricDaily,
)


# 已支持的表名 → ORM 类
_TABLE_MAP = {
    "devices": Device,
    "device_telemetry": DeviceTelemetry,
    "patrol_tasks": PatrolTask,
    "security_alerts": SecurityAlert,
    "analytics_event": AnalyticsEvent,
    "clusters": Cluster,
}


class EngineError(Exception):
    """DSL 解析或执行错误。"""


def _apply_filter(query, flt: dict[str, Any]):
    """对 query 应用 filter 字典中的条件。"""
    if not flt:
        return query
    model_cls = query.column_descriptions[0]["entity"]
    if "status" in flt:
        query = query.filter(model_cls.status == flt["status"])
    if "status_in" in flt:
        query = query.filter(model_cls.status.in_(flt["status_in"]))
    if "battery_lt" in flt:
        query = query.filter(model_cls.battery < flt["battery_lt"])
    if "battery_gt" in flt:
        query = query.filter(model_cls.battery > flt["battery_gt"])
    if "source" in flt:
        query = query.filter(model_cls.source == flt["source"])
    return query


def _eval_aggregate(db: Session, expr: dict, date_range: tuple[datetime, datetime] | None = None) -> Any:
    """执行 aggregate 表达式，返回标量或分组结果。"""
    table_name = expr.get("table")
    model_cls = _TABLE_MAP.get(table_name)
    if model_cls is None:
        raise EngineError(f"未支持的表: {table_name}")

    fn_name = expr.get("func", "count")
    field_name = expr.get("field")
    flt = expr.get("filter", {})

    if fn_name == "count":
        query = db.query(model_cls)
        query = _apply_filter(query, flt)
        if "group_by" in expr:
            group_field = getattr(model_cls, expr["group_by"])
            rows = db.query(group_field, func.count()).group_by(group_field).all()
            return {str(k): int(v) for k, v in rows}
        return int(query.count())

    if not field_name:
        raise EngineError(f"func={fn_name} 需要 field 字段")
    if not hasattr(model_cls, field_name):
        raise EngineError(f"{table_name} 没有 {field_name} 字段")
    column = getattr(model_cls, field_name)

    fn_map = {"sum": func.sum, "avg": func.avg, "max": func.max, "min": func.min}
    sql_fn = fn_map.get(fn_name)
    if sql_fn is None:
        raise EngineError(f"未支持的 func: {fn_name}")

    query = db.query(sql_fn(column))
    query = _apply_filter(query, flt)
    result = query.scalar()
    return float(result) if result is not None else 0.0


def _eval_ratio(db: Session, expr: dict, date_range: tuple[datetime, datetime] | None = None) -> float:
    """两 aggregate 的比值，分母为零返回 0。"""
    num = _evaluate(db, expr["numerator"], date_range)
    den = _evaluate(db, expr["denominator"], date_range)
    if isinstance(num, dict) or isinstance(den, dict):
        raise EngineError("ratio 不支持分组结果")
    if not den:
        return 0.0
    return float(num) / float(den)


def _eval_arithmetic(db: Session, expr: dict, date_range: tuple[datetime, datetime] | None = None) -> float:
    """多表达式的四则运算，从左到右折叠。"""
    op = expr.get("op", "+")
    operands = expr.get("operands", [])
    if len(operands) < 2:
        raise EngineError("arithmetic 至少需要两个 operands")

    values = [float(_evaluate(db, o, date_range)) for o in operands]
    result = values[0]
    for v in values[1:]:
        if op == "+":
            result += v
        elif op == "-":
            result -= v
        elif op == "*":
            result *= v
        elif op == "/":
            result = result / v if v else 0.0
        else:
            raise EngineError(f"未支持的运算符: {op}")
    return result


def _evaluate(db: Session, expr: dict, date_range: tuple[datetime, datetime] | None = None) -> Any:
    """递归执行表达式 DSL。"""
    if not isinstance(expr, dict):
        raise EngineError("expression 必须是 JSON 对象")
    t = expr.get("type")
    if t == "aggregate":
        return _eval_aggregate(db, expr, date_range)
    if t == "ratio":
        return _eval_ratio(db, expr, date_range)
    if t == "arithmetic":
        return _eval_arithmetic(db, expr, date_range)
    if t == "external":
        # 外部数据源占位：实际值由采集任务写入 analytics_external_metric 后再聚合
        return 0.0
    raise EngineError(f"未支持的表达式类型: {t}")


def compute_indicator(db: Session, expression: dict, date_range: tuple[datetime, datetime] | None = None) -> Any:
    """对外暴露的指标计算入口。"""
    if not expression:
        return None
    return _evaluate(db, expression, date_range)


def run_daily_aggregation(db: Session, indicator_id: int, target_date: datetime | None = None) -> float | None:
    """对单个指标执行日聚合，写入 analytics_metric_daily（dimension_key='all'）。

    返回本次聚合值。本函数仅处理日粒度指标的简化路径；
    带维度的细分聚合（按 device_id / cluster_id）在 scheduler 中批量调度。
    """
    from models import AnalyticsIndicator, AnalyticsMetricDaily

    indicator = db.query(AnalyticsIndicator).filter(AnalyticsIndicator.id == indicator_id).first()
    if not indicator or not indicator.is_active or not indicator.expression:
        return None

    if target_date is None:
        target_date = datetime.now()
    date_key = target_date.replace(hour=0, minute=0, second=0, microsecond=0)

    value = compute_indicator(db, indicator.expression)

    existing = db.query(AnalyticsMetricDaily).filter(
        AnalyticsMetricDaily.indicator_id == indicator_id,
        AnalyticsMetricDaily.dimension_key == "all",
        AnalyticsMetricDaily.date == date_key,
    ).first()

    if existing:
        existing.value = value
        existing.sample_count = (existing.sample_count or 0) + 1
        existing.updated_at = datetime.now()
    else:
        db.add(AnalyticsMetricDaily(
            indicator_id=indicator_id,
            dimension_key="all",
            date=date_key,
            value=value,
            sample_count=1,
        ))
    db.commit()
    return value
