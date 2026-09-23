"""认证服务"""
import hmac

from zhenxun.configs.config import Config

from ..exceptions import AuthenticationException, ValidationException
from ..models.auth import LoginRequest, LoginResponse
from ..utils.security import create_access_token, verify_access_token


class AuthService:
    """认证服务"""

    @staticmethod
    def authenticate(request: LoginRequest) -> bool:
        """验证用户登录"""
        username = Config.get_config("web-ui", "username")
        password = Config.get_config("web-ui", "password")

        if not username or not password:
            raise ValidationException("管理员账号或密码未配置")

        # 恒定时间比较，避免按字节逐位短路造成的时序侧信道
        username_ok = hmac.compare_digest(
            request.username.encode("utf-8"), str(username).encode("utf-8")
        )
        password_ok = hmac.compare_digest(
            request.password.encode("utf-8"), str(password).encode("utf-8")
        )
        if not (username_ok and password_ok):
            raise AuthenticationException("用户名或密码错误")

        return True

    @staticmethod
    def login(request: LoginRequest) -> LoginResponse:
        """用户登录"""
        AuthService.authenticate(request)
        token = create_access_token(request.username)
        return LoginResponse(
            access_token=token,
            token_type="bearer",
            expires_in=1800,
        )

    @staticmethod
    def verify_token(token: str) -> str:
        """验证 token"""
        username = verify_access_token(token)
        if not username:
            raise AuthenticationException("Token 无效或已过期")
        return username
