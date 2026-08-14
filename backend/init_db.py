"""
数据库初始化脚本

创建所有数据表，并插入默认管理员用户。
运行方式：python init_db.py
"""

import os
from pathlib import Path
from sqlalchemy import inspect, text
from passlib.hash import bcrypt

from database import engine, SessionLocal, Base
from models import (
    User, Device, Cluster, DeviceTelemetry, DeviceToken,
    PatrolArea, PatrolPoint, PatrolRoute, PatrolRoutePoint, PatrolTask, SecurityAlert,
    UserRole, AnalyticsIndicator, AnalyticsEvent, AnalyticsMetricDaily,
    AnalyticsRule, AnalyticsReportTemplate, AnalyticsReportRun, AnalyticsNotification,
    # 校园室外巡检（阶段 B/C）
    OutdoorCalibration, OutdoorRoute, OutdoorWaypoint,
    OutdoorPatrolTask, OutdoorPatrolEvent,
    # 视频识别分析（M3/M5）
    VideoTrackHistory, InferenceRunLog,
)


def init_database():
    """初始化数据库：创建表结构 + 插入默认数据 + 迁移已有表"""

    # 1. 创建所有表
    print("正在创建数据表...")
    Base.metadata.create_all(bind=engine)

    # 检查表是否创建成功
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"当前数据库中的表: {tables}")

    # 2. 迁移已有的 devices 表（添加 port 和 last_seen 列如果不存在）
    db = SessionLocal()
    try:
        columns = [col["name"] for col in inspector.get_columns("devices")]
        
        if "port" not in columns:
            print("正在为 devices 表添加 port 列...")
            db.execute(text("ALTER TABLE devices ADD COLUMN port INT DEFAULT 9000 NOT NULL COMMENT '控制服务端口号'"))
            db.commit()
            print("已添加 port 列")
        
        if "last_seen" not in columns:
            print("正在为 devices 表添加 last_seen 列...")
            db.execute(text("ALTER TABLE devices ADD COLUMN last_seen DATETIME NULL COMMENT '最后遥测上报时间'"))
            db.commit()
            print("已添加 last_seen 列")

    except Exception as e:
        db.rollback()
        print(f"迁移 devices 表失败（可能列已存在）: {e}")
    finally:
        db.close()

    # 3. 插入默认管理员用户（如果不存在）
    db = SessionLocal()
    try:
        admin_username = os.getenv("DEFAULT_ADMIN_USER", "admin")
        admin_password = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123")

        existing_admin = db.query(User).filter(User.username == admin_username).first()
        if existing_admin is None:
            admin_user = User(
                username=admin_username,
                password_hash=bcrypt.hash(admin_password),
                nickname="管理员",
                is_active=True,
            )
            db.add(admin_user)
            db.commit()
            print(f"已创建默认管理员用户: {admin_username} / {admin_password}")
        else:
            print(f"管理员用户已存在 ({admin_username})，跳过创建")
    except Exception as e:
        db.rollback()
        print(f"插入默认用户失败: {e}")
        raise
    finally:
        db.close()

    # 4. 数据统计研判模块迁移（默认角色 + 指标字典 + 示例规则）
    #    通过执行 migrations/001_analytics.sql 完成种子数据填充，幂等可重复执行。
    migration_file = Path(__file__).parent / "migrations" / "001_analytics.sql"
    if migration_file.is_file():
        print(f"正在执行研判模块迁移脚本: {migration_file.name}")
        with engine.begin() as conn:
            sql_text = migration_file.read_text(encoding="utf-8")
            # 按 ";" 分句执行（MySQL driver 不支持多语句时退化为单条）
            statements = [s.strip() for s in sql_text.split(";") if s.strip() and not s.strip().startswith("--")]
            for stmt in statements:
                try:
                    conn.execute(text(stmt))
                except Exception as stmt_err:
                    print(f"  跳过语句（可能已存在）: {str(stmt_err).splitlines()[0]}")
        print("研判模块迁移完成")
    else:
        print(f"未找到迁移脚本: {migration_file}")

    # 5. 视频识别分析模块迁移（幂等）
    inference_migration = Path(__file__).parent / "migrations" / "003_video_inference.sql"
    if inference_migration.is_file():
        print(f"正在执行视频识别分析迁移脚本: {inference_migration.name}")
        with engine.begin() as conn:
            sql_text = inference_migration.read_text(encoding="utf-8")
            statements = [s.strip() for s in sql_text.split(";") if s.strip() and not s.strip().startswith("--")]
            for stmt in statements:
                try:
                    conn.execute(text(stmt))
                except Exception as stmt_err:
                    print(f"  跳过语句（可能已存在）: {str(stmt_err).splitlines()[0]}")
        print("视频识别分析迁移完成")
    else:
        print(f"未找到迁移脚本: {inference_migration}")

    # 6. 校园室外巡检模块迁移（幂等）
    outdoor_migration = Path(__file__).parent / "migrations" / "002_outdoor_patrol.sql"
    if outdoor_migration.is_file():
        print(f"正在执行室外巡检迁移脚本: {outdoor_migration.name}")
        with engine.begin() as conn:
            sql_text = outdoor_migration.read_text(encoding="utf-8")
            statements = [s.strip() for s in sql_text.split(";") if s.strip() and not s.strip().startswith("--")]
            for stmt in statements:
                try:
                    conn.execute(text(stmt))
                except Exception as stmt_err:
                    print(f"  跳过语句（可能已存在）: {str(stmt_err).splitlines()[0]}")
        print("室外巡检迁移完成")
    else:
        print(f"未找到迁移脚本: {outdoor_migration}")

    print("数据库初始化完成！")


if __name__ == "__main__":
    init_database()
