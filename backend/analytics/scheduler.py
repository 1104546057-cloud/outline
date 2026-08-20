"""研判模块批处理调度。

提供两个入口：
- run_daily(): 日聚合 + 规则评估，每日凌晨由外部触发器调用一次
- run_near_realtime(): 5 分钟级增量刷新关键指标缓存

调度触发方式（项目侧已使用 systemd 托管后端）：
- 日聚合：通过后端启动时挂一个 APScheduler BackgroundScheduler，或外部 cron 调 /api/analytics/admin/run-daily
- 近实时：同进程 BackgroundScheduler 每 5 分钟触发一次

本模块仅提供纯函数实现，调度入口由 main.py 或 routers/analytics_admin.py 调用。
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from sqlalchemy.orm import Session

from database import SessionLocal
from models import AnalyticsIndicator
from analytics.engine import run_daily_aggregation
from analytics.detector import run_all_rules


def run_daily(target_date: datetime | None = None) -> dict:
    """执行日聚合 + 规则评估的完整流程。

    返回 {"aggregated": int, "hits": int, "duration_seconds": float}
    """
    started = datetime.now()
    db: Session = SessionLocal()
    aggregated = 0
    try:
        indicators = db.query(AnalyticsIndicator).filter(AnalyticsIndicator.is_active == True).all()  # noqa: E712
        for ind in indicators:
            try:
                run_daily_aggregation(db, ind.id, target_date)
                aggregated += 1
            except Exception as e:
                print(f"[scheduler] 指标 {ind.code} 聚合失败: {e}")
        hits = run_all_rules(db)
    finally:
        db.close()

    duration = (datetime.now() - started).total_seconds()
    return {"aggregated": aggregated, "hits": len(hits), "duration_seconds": duration}


def run_near_realtime(refresh_fn: Callable[[Session], None] | None = None) -> None:
    """近实时刷新：默认只跑规则评估，调用方可传入自定义刷新逻辑（如更新 Redis 缓存）。"""
    db: Session = SessionLocal()
    try:
        if refresh_fn:
            refresh_fn(db)
        run_all_rules(db)
    finally:
        db.close()
