"""研判模块通知通道：站内消息 + 邮件。

邮件通道默认关闭，通过 EMAIL_ENABLED 环境变量开启。
不引入外部 SMTP 库，使用 Python 标准库 smtplib。
"""

from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from sqlalchemy.orm import Session

from models import AnalyticsNotification, User, UserRole


def push_inapp(
    db: Session,
    user_id: int,
    title: str,
    content: str | None = None,
    category: str = "alert",
    ref_type: str | None = None,
    ref_id: int | None = None,
) -> AnalyticsNotification:
    """写入站内通知。"""
    n = AnalyticsNotification(
        user_id=user_id,
        title=title,
        content=content,
        category=category,
        ref_type=ref_type,
        ref_id=ref_id,
        is_read=False,
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    return n


def notify_role(
    db: Session,
    role: str,
    title: str,
    content: str | None = None,
    category: str = "alert",
    ref_type: str | None = None,
    ref_id: int | None = None,
) -> int:
    """向所有指定角色用户推送站内消息，返回推送数量。"""
    rows = db.query(UserRole).filter(UserRole.role == role).all()
    for r in rows:
        push_inapp(db, r.user_id, title, content, category, ref_type, ref_id)
    return len(rows)


def send_email(to_addrs: list[str], subject: str, body: str, html: bool = False) -> bool:
    """发送邮件。失败返回 False，不抛异常以免影响主流程。

    环境变量：
      EMAIL_ENABLED=true|false
      SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM
    """
    if os.getenv("EMAIL_ENABLED", "false").lower() != "true":
        return False
    if not to_addrs:
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = os.getenv("SMTP_FROM", os.getenv("SMTP_USER", ""))
        msg["To"] = ",".join(to_addrs)
        msg.attach(MIMEText(body, "html" if html else "plain", "utf-8"))
        with smtplib.SMTP(
            os.getenv("SMTP_HOST", "localhost"),
            int(os.getenv("SMTP_PORT", "25")),
        ) as server:
            server.starttls()
            user = os.getenv("SMTP_USER")
            if user:
                server.login(user, os.getenv("SMTP_PASSWORD", ""))
            server.sendmail(msg["From"], to_addrs, msg.as_string())
        return True
    except Exception as e:
        print(f"[notifier] 邮件发送失败: {e}")
        return False
