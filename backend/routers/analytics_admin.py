"""数据统计研判 · 管理路由（指标字典、规则、报告、调度触发）。

权限：analyst 或 admin。
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import require_role, get_current_user
from database import get_db
from models import (
    User, AnalyticsIndicator, AnalyticsRule,
    AnalyticsReportTemplate, AnalyticsReportRun, UserRole,
)
from schemas import (
    AnalyticsIndicatorCreate, AnalyticsIndicatorUpdate,
    AnalyticsRuleCreate, AnalyticsRuleUpdate,
    AnalyticsReportTemplateCreate, AnalyticsReportRunCreate,
    UserRoleUpdate,
)


router = APIRouter(prefix="/api/analytics/admin", tags=["研判管理"])


# ===== 指标字典管理 =====

@router.get("/indicators", dependencies=[Depends(require_role("analyst", "admin"))])
async def admin_list_indicators(db: Session = Depends(get_db)):
    return db.query(AnalyticsIndicator).order_by(AnalyticsIndicator.id).all()


@router.post("/indicators", dependencies=[Depends(require_role("admin"))])
async def admin_create_indicator(
    payload: AnalyticsIndicatorCreate,
    db: Session = Depends(get_db),
):
    if db.query(AnalyticsIndicator).filter(AnalyticsIndicator.code == payload.code).first():
        raise HTTPException(status_code=409, detail="指标编码已存在")
    ind = AnalyticsIndicator(
        code=payload.code, name=payload.name, category=payload.category,
        data_source=payload.data_source, expression=payload.expression,
        unit=payload.unit, granularity=payload.granularity,
        baseline=payload.baseline, description=payload.description,
        is_active=payload.is_active,
    )
    db.add(ind)
    db.commit()
    db.refresh(ind)
    return ind


@router.put("/indicators/{iid}", dependencies=[Depends(require_role("admin"))])
async def admin_update_indicator(
    iid: int,
    payload: AnalyticsIndicatorUpdate,
    db: Session = Depends(get_db),
):
    ind = db.query(AnalyticsIndicator).filter(AnalyticsIndicator.id == iid).first()
    if not ind:
        raise HTTPException(status_code=404, detail="指标不存在")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(ind, k, v)
    db.commit()
    db.refresh(ind)
    return ind


@router.delete("/indicators/{iid}", dependencies=[Depends(require_role("admin"))])
async def admin_delete_indicator(iid: int, db: Session = Depends(get_db)):
    ind = db.query(AnalyticsIndicator).filter(AnalyticsIndicator.id == iid).first()
    if not ind:
        raise HTTPException(status_code=404, detail="指标不存在")
    db.delete(ind)
    db.commit()
    return {"ok": True}


# ===== 规则管理 =====

@router.get("/rules", dependencies=[Depends(require_role("analyst", "admin"))])
async def admin_list_rules(db: Session = Depends(get_db)):
    rules = db.query(AnalyticsRule).order_by(AnalyticsRule.id).all()
    return [
        {
            "id": r.id, "name": r.name, "indicator_id": r.indicator_id,
            "rule_type": r.rule_type, "condition": r.condition,
            "severity": r.severity, "alert_type": r.alert_type,
            "description": r.description, "is_active": r.is_active,
            "indicator_code": r.indicator.code if r.indicator else None,
        }
        for r in rules
    ]


@router.post("/rules", dependencies=[Depends(require_role("analyst", "admin"))])
async def admin_create_rule(payload: AnalyticsRuleCreate, db: Session = Depends(get_db)):
    ind = db.query(AnalyticsIndicator).filter(AnalyticsIndicator.id == payload.indicator_id).first()
    if not ind:
        raise HTTPException(status_code=404, detail="关联指标不存在")
    rule = AnalyticsRule(
        name=payload.name, indicator_id=payload.indicator_id,
        rule_type=payload.rule_type, condition=payload.condition,
        severity=payload.severity, alert_type=payload.alert_type,
        description=payload.description, is_active=payload.is_active,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.put("/rules/{rid}", dependencies=[Depends(require_role("analyst", "admin"))])
async def admin_update_rule(rid: int, payload: AnalyticsRuleUpdate, db: Session = Depends(get_db)):
    rule = db.query(AnalyticsRule).filter(AnalyticsRule.id == rid).first()
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/rules/{rid}", dependencies=[Depends(require_role("analyst", "admin"))])
async def admin_delete_rule(rid: int, db: Session = Depends(get_db)):
    rule = db.query(AnalyticsRule).filter(AnalyticsRule.id == rid).first()
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    db.delete(rule)
    db.commit()
    return {"ok": True}


# ===== 报告模板与生成 =====

@router.get("/report-templates", dependencies=[Depends(require_role("analyst", "admin"))])
async def admin_list_templates(db: Session = Depends(get_db)):
    return db.query(AnalyticsReportTemplate).order_by(AnalyticsReportTemplate.id).all()


@router.post("/report-templates", dependencies=[Depends(require_role("analyst", "admin"))])
async def admin_create_template(
    payload: AnalyticsReportTemplateCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    tpl = AnalyticsReportTemplate(
        name=payload.name, description=payload.description,
        config=payload.config, format=payload.format,
        created_by=user.id, is_active=payload.is_active,
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl


@router.post("/reports/run", dependencies=[Depends(require_role("analyst", "admin"))])
async def admin_run_report(
    payload: AnalyticsReportRunCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """触发报告生成。

    本接口仅创建运行记录并标记 pending；
    实际生成逻辑（PDF/Excel 渲染）由后台 worker 异步消费。
    本期占位返回 run_id，渲染实现见 M3 里程碑。
    """
    tpl = db.query(AnalyticsReportTemplate).filter(
        AnalyticsReportTemplate.id == payload.template_id
    ).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="报告模板不存在")

    run = AnalyticsReportRun(
        template_id=tpl.id,
        triggered_by=user.id,
        status="pending",
        period_start=payload.period_start,
        period_end=payload.period_end or datetime.now(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return {"run_id": run.id, "status": run.status, "message": "已提交，生成完成后可在报告中心下载"}


@router.get("/reports/runs", dependencies=[Depends(require_role("analyst", "admin"))])
async def admin_list_runs(
    template_id: int | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(AnalyticsReportRun)
    if template_id:
        query = query.filter(AnalyticsReportRun.template_id == template_id)
    rows = query.order_by(AnalyticsReportRun.created_at.desc()).limit(50).all()
    return [
        {
            "id": r.id, "template_id": r.template_id,
            "triggered_by": r.triggered_by, "status": r.status,
            "period_start": r.period_start.isoformat() if r.period_start else None,
            "period_end": r.period_end.isoformat() if r.period_end else None,
            "file_path": r.file_path,
            "error_message": r.error_message,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


# ===== 调度触发 =====

@router.post("/run-daily", dependencies=[Depends(require_role("analyst", "admin"))])
async def admin_trigger_daily():
    """手动触发日聚合 + 规则评估。"""
    from analytics.scheduler import run_daily
    result = run_daily()
    return result


@router.post("/run-rules", dependencies=[Depends(require_role("analyst", "admin"))])
async def admin_trigger_rules():
    """手动触发规则评估。"""
    from analytics.detector import run_all_rules
    from database import SessionLocal
    db = SessionLocal()
    try:
        hits = run_all_rules(db)
    finally:
        db.close()
    return {"hits": len(hits), "details": hits}


# ===== 用户角色管理 =====

@router.get("/users/roles", dependencies=[Depends(require_role("admin"))])
async def admin_list_user_roles(db: Session = Depends(get_db)):
    rows = db.query(UserRole).all()
    return [
        {"id": r.id, "user_id": r.user_id, "role": r.role, "created_at": r.created_at.isoformat()}
        for r in rows
    ]


@router.put("/users/{user_id}/role", dependencies=[Depends(require_role("admin"))])
async def admin_update_user_role(user_id: int, payload: UserRoleUpdate, db: Session = Depends(get_db)):
    row = db.query(UserRole).filter(UserRole.user_id == user_id).first()
    if not row:
        row = UserRole(user_id=user_id, role=payload.role)
        db.add(row)
    else:
        row.role = payload.role
    db.commit()
    db.refresh(row)
    return {"ok": True, "user_id": user_id, "role": row.role}
