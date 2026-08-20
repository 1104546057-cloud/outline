"""
数据库配置模块

使用 SQLAlchemy 连接 MySQL 数据库，提供数据库会话管理。
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from urllib.parse import quote_plus
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# 加载 .env 环境变量
load_dotenv()

# MySQL 数据库连接配置
DB_USER = os.getenv("DB_USER", "dwc")
DB_PASSWORD = os.getenv("DB_PASSWORD", "dwc@123")
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_NAME = os.getenv("DB_NAME", "devices_web_control")
DB_BACKEND = os.getenv("DB_BACKEND", "mysql").strip().lower()

if DB_BACKEND == "sqlite":
    # 独立 SQLite 文件，避免和室内 MySQL（indoor_platform）抢同一个库
    sqlite_path = os.getenv(
        "SQLITE_PATH",
        str(Path(__file__).resolve().parent / "outdoor.db"),
    )
    Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)
    DATABASE_URL = f"sqlite:///{sqlite_path}"
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
    )
else:
    # 格式: mysql+pymysql://用户名:密码@主机:端口/数据库名
    # 注意：密码中含有特殊字符（如 @），需要使用 quote_plus 进行 URL 编码
    DATABASE_URL = (
        f"mysql+pymysql://{DB_USER}:{quote_plus(DB_PASSWORD)}"
        f"@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
    )
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        pool_size=5,
        max_overflow=10,
        pool_recycle=3600,
    )

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# 声明基类（SQLAlchemy 2.0 风格）
class Base(DeclarativeBase):
    pass


def get_db():
    """
    获取数据库会话的依赖注入函数

    用于 FastAPI 的 Depends() 依赖注入，确保每个请求使用独立的数据库会话，
    并在请求结束后自动关闭。异常时自动回滚，防止脏数据意外提交。
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
