"""
认证路由

提供用户登录接口。
"""

import re
from datetime import timedelta
from fastapi import APIRouter, HTTPException, Depends, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from passlib.hash import bcrypt

from database import get_db
from models import User
from schemas import LoginRequest, LoginResponse, RegisterRequest, RegisterResponse
from auth import create_access_token
from config import ACCESS_TOKEN_EXPIRE_MINUTES
from captcha_store import verify_captcha

router = APIRouter(prefix="/api/auth", tags=["认证"])


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,32}$")
MAX_NICKNAME_LENGTH = 100


@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register(request: RegisterRequest, db: Session = Depends(get_db)):
    """公开注册接口，创建默认启用的账号但不自动登录。"""
    if not verify_captcha(request.captcha_id, request.captcha_code):
        raise HTTPException(status_code=422, detail="验证码错误或已过期")

    username = request.username.strip()
    password = request.password
    nickname = request.nickname.strip() if request.nickname else None

    if not USERNAME_PATTERN.fullmatch(username):
        raise HTTPException(status_code=422, detail="用户名需为 3-32 位字母、数字或下划线")
    if not password.strip():
        raise HTTPException(status_code=422, detail="密码不能全为空白")
    if len(password) < 6:
        raise HTTPException(status_code=422, detail="密码至少需要 6 个字符")
    if len(password.encode("utf-8")) > 72:
        raise HTTPException(status_code=422, detail="密码不能超过 72 字节")
    if nickname and len(nickname) > MAX_NICKNAME_LENGTH:
        raise HTTPException(status_code=422, detail="昵称不能超过 100 个字符")

    if db.query(User).filter(User.username == username).first() is not None:
        raise HTTPException(status_code=409, detail="用户名已存在")

    try:
        user = User(
            username=username,
            password_hash=bcrypt.hash(password),
            nickname=nickname,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="用户名已存在")
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="注册失败，请稍后重试")

    return RegisterResponse(
        message="注册成功，请使用新账号登录",
        username=user.username,
        nickname=user.nickname,
    )


@router.post("/login")
async def login(request: LoginRequest, response: Response, db: Session = Depends(get_db)):
    """
    用户登录接口

    从 MySQL 数据库查询用户，使用 bcrypt 验证密码。
    测试账号可在 .env 中配置 (DEFAULT_ADMIN_USER / DEFAULT_ADMIN_PASSWORD)。
    """
    # 校验图片验证码
    if not verify_captcha(request.captcha_id, request.captcha_code):
        raise HTTPException(status_code=422, detail="验证码错误或已过期")

    # 从数据库查询用户
    user = db.query(User).filter(User.username == request.username).first()

    if user is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 验证密码（bcrypt 哈希比对）
    if not bcrypt.verify(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 检查用户是否被禁用
    if not user.is_active:
        raise HTTPException(status_code=403, detail="该账号已被禁用")

    # 生成 JWT token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )

    # 通过 Set-Cookie 下发 JWT
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        secure=False,  # 开发环境设为False，生产环境 HTTPS 建议设为 True
    )

    return LoginResponse(
        message="登录成功",
        username=user.username,
        token=access_token,
        nickname=user.nickname,
    )
