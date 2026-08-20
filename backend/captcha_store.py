"""
验证码存储模块

使用内存字典存储验证码，支持过期清理。
生产环境建议替换为 Redis 存储。
"""

import time
import secrets
import threading
from typing import Optional


# 验证码存储：{captcha_id: (code_lower, expire_time)}
_store: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()

# 验证码有效期（秒）
CAPTCHA_TTL = 300  # 5分钟


def generate_captcha_id() -> str:
    """生成唯一的验证码 ID"""
    return secrets.token_urlsafe(16)


def save_captcha(captcha_id: str, code: str) -> None:
    """保存验证码（忽略大小写，统一转为小写存储）"""
    expire_at = time.time() + CAPTCHA_TTL
    with _lock:
        _store[captcha_id] = (code.lower(), expire_at)
        _cleanup_expired()


def verify_captcha(captcha_id: str, user_input: str) -> bool:
    """
    验证用户输入的验证码，验证后立即删除（一次性）。
    返回 True 表示验证成功。
    """
    with _lock:
        entry = _store.pop(captcha_id, None)
    if entry is None:
        return False
    code, expire_at = entry
    if time.time() > expire_at:
        return False
    return code == user_input.lower().strip()


def _cleanup_expired() -> None:
    """清理过期验证码（在锁内调用）"""
    now = time.time()
    expired_keys = [k for k, (_, exp) in _store.items() if now > exp]
    for k in expired_keys:
        del _store[k]
