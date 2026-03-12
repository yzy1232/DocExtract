"""
安全工具 - 密码哈希与 JWT 令牌
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from passlib.context import CryptContext
from jose import JWTError, jwt
from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """对密码进行 bcrypt 哈希"""
    # 为避免 bcrypt 的 72 字节限制，先使用 SHA-256 对任意长度的密码做摘要，再对摘要结果进行 bcrypt 哈希
    import hashlib

    digest = hashlib.sha256((password or "").encode("utf-8")).hexdigest()
    return pwd_context.hash(digest)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    import hashlib

    digest = hashlib.sha256((plain_password or "").encode("utf-8")).hexdigest()
    return pwd_context.verify(digest, hashed_password)


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    """创建访问令牌"""
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(subject: str) -> str:
    """创建刷新令牌"""
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "refresh",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    """解码并验证 JWT 令牌，返回 payload"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return {}


def generate_api_key() -> str:
    """生成 API 密钥"""
    import secrets
    return f"dk_{secrets.token_urlsafe(32)}"
