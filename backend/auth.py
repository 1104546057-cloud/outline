"""
认证模块

提供 JWT Token 创建和用户身份验证依赖注入。
"""

import jwt
from datetime import datetime, timedelta
from fastapi import HTTPException, Depends, Request
from sqlalchemy.orm import Session

from database import get_db
from models import User
from config import JWT_SECRET_KEY, JWT_ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def get_current_user(request: Request, db: Session = Depends(get_db)):
    """
    从 Cookie 中提取 JWT Token，验证并返回当前用户

    用于需要认证的接口的依赖注入。
    """
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="未登录，请先登录")

    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="无效的认证信息")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效的认证信息")

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")

    return user


def get_user_role(user: User, db: Session) -> str:
    """返回用户角色字符串，无角色记录返回 'viewer'。"""
    from models import UserRole
    role_row = db.query(UserRole).filter(UserRole.user_id == user.id).first()
    return role_row.role if role_row else "viewer"


def require_role(*allowed_roles: str):
    """FastAPI 依赖：仅允许指定角色访问。

    用法：
        @router.post("...", dependencies=[Depends(require_role("analyst", "admin"))])
    或
        def handler(user: User = Depends(require_role("admin"))):
    """
    from functools import wraps
    from fastapi import Depends

    def _dep(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
        role = get_user_role(user, db)
        if role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"无权限：需要 {'/'.join(allowed_roles)} 角色，当前角色 {role}",
            )
        return user

    return _dep
