"""安全工具函数"""
from datetime import datetime, timedelta, timezone

from jose import jwt

from zhenxun.configs.config import Config

ALGORITHM = "HS256"
DEFAULT_EXPIRES_DELTA = timedelta(minutes=9999)


def create_access_token(username: str, expires_delta: timedelta | None = None) -> str:
    """创建访问令牌"""
    expire = datetime.now(timezone.utc) + (expires_delta or DEFAULT_EXPIRES_DELTA)
    return jwt.encode(
        claims={
            "sub": username,
            "exp": expire,
            "iat": datetime.now(timezone.utc),
        },
        key=Config.get_config("web-ui", "secret"),
        algorithm=ALGORITHM,
    )


def verify_access_token(token: str) -> str | None:
    """验证访问令牌，返回用户名"""
    try:
        payload = jwt.decode(
            token, Config.get_config("web-ui", "secret"), algorithms=[ALGORITHM]
        )
        return payload.get("sub")
    except Exception:
        return None
