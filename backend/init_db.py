"""
数据库初始化脚本

创建所有数据表，并插入默认管理员用户。
运行方式：python init_db.py
"""

import os
from sqlalchemy import inspect
from passlib.hash import bcrypt

from database import engine, SessionLocal, Base
from models import User, Device, Cluster


def init_database():
    """初始化数据库：创建表结构 + 插入默认数据"""

    # 1. 创建所有表
    print("正在创建数据表...")
    Base.metadata.create_all(bind=engine)

    # 检查表是否创建成功
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"当前数据库中的表: {tables}")

    # 2. 插入默认管理员用户（如果不存在）
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

    print("数据库初始化完成！")


if __name__ == "__main__":
    init_database()
