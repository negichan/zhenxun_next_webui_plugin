"""依赖注入"""
from typing import Annotated

from fastapi import Depends, HTTPException, WebSocket
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from zhenxun.configs.config import Config

from .models.auth import User
from .utils.security import ALGORITHM, verify_access_token

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/zhenxun/api/v1/auth/login", auto_error=False
)


def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """获取当前用户

    参数:
        token: JWT token

    返回:
        User: 用户信息

    异常:
        HTTPException: 认证失败时抛出 401 异常
    """
    if not token:
        raise HTTPException(status_code=401, detail="未提供认证令牌")

    try:
        payload = jwt.decode(
            token, Config.get_config("web-ui", "secret"), algorithms=[ALGORITHM]
        )
        username = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="无效的 token")
        return User(username=username)
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Token 验证失败：{e}")


def require_auth(user: User = Depends(get_current_user)) -> User:
    """要求用户已认证"""
    return user


# 类型别名
CurrentUser = Annotated[User, Depends(get_current_user)]
AuthenticatedUser = Annotated[User, Depends(require_auth)]


async def authenticate_websocket(websocket: WebSocket) -> bool:
    """WebSocket 握手鉴权

    浏览器原生 WebSocket 带不了 Authorization 头，token 走 query 参数；
    非浏览器客户端兼容 Authorization 头。校验失败直接拒绝握手
    （未 accept 就 close，Starlette 以 403 结束握手）。

    参数:
        websocket: WebSocket 连接

    返回:
        bool: 是否通过鉴权（未通过时连接已关闭，调用方直接 return）
    """
    token = websocket.query_params.get("token")
    if not token:
        auth_header = websocket.headers.get("authorization", "")
        token = (
            auth_header[7:].strip()
            if auth_header[:7].lower() == "bearer "
            else auth_header.strip()
        )
    if not token or verify_access_token(token) is None:
        await websocket.close(code=1008)
        return False
    return True
