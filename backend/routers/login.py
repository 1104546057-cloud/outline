"""
认证路由

提供用户登录接口。
"""

from datetime import timedelta
from fastapi import APIRouter, HTTPException, Depends, Response
from sqlalchemy.orm import Session
from passlib.hash import bcrypt

from database import get_db
from models import User
from schemas import LoginRequest, LoginResponse
from auth import create_access_token
from config import ACCESS_TOKEN_EXPIRE_MINUTES
from captcha_store import verify_captcha

router = APIRouter(prefix="/api/auth", tags=["认证"])


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
