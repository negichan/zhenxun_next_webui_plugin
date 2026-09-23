"""认证路由"""
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request

from ..dependencies import AuthenticatedUser, oauth2_scheme
from ..exceptions import AuthenticationException
from ..models.auth import LoginRequest, LoginResponse
from ..responses import APIResponse, success_response
from ..services.auth_service import AuthService
from ..utils.security import create_access_token

router = APIRouter(prefix="/auth", tags=["认证"])

# ==================== 登录防爆破 ====================
# 每个来源 IP 在滑动窗口内最多允许 _MAX_FAILURES 次登录失败，
# 超出后窗口内直接 429 拒绝，防止对登录接口无限速爆破。
# 计数存内存：进程重启清零，单进程部署下够用
_FAILURE_WINDOW = 600  # 秒
_MAX_FAILURES = 5
_failed_logins: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _ensure_not_locked(ip: str) -> None:
    now = time.monotonic()
    attempts = _failed_logins[ip]
    while attempts and now - attempts[0] > _FAILURE_WINDOW:
        attempts.popleft()
    if len(attempts) >= _MAX_FAILURES:
        raise HTTPException(
            status_code=429,
            detail=f"登录失败次数过多，请约 {_FAILURE_WINDOW // 60} 分钟后再试",
        )


def _record_failure(ip: str) -> None:
    _failed_logins[ip].append(time.monotonic())


def _clear_failures(ip: str) -> None:
    _failed_logins.pop(ip, None)


@router.post("/login", response_model=APIResponse[LoginResponse], summary="用户登录")
async def login(request: LoginRequest, req: Request) -> APIResponse[LoginResponse]:
    """用户登录接口"""
    ip = _client_ip(req)
    _ensure_not_locked(ip)
    try:
        response = AuthService.login(request)
    except AuthenticationException:
        _record_failure(ip)
        raise
    _clear_failures(ip)
    return success_response(data=response, message="登录成功")


@router.get("/verify", response_model=APIResponse[dict], summary="验证 Token")
async def verify_token(user: AuthenticatedUser) -> APIResponse[dict]:
    """验证 Token 是否有效（token 经 Authorization 头传递，不进 URL/访问日志）"""
    return success_response(data={"valid": True, "username": user.username})


@router.post(
    "/refresh",
    response_model=APIResponse[LoginResponse],
    summary="刷新 Token",
)
async def refresh_token(token: str = Depends(oauth2_scheme)) -> APIResponse[LoginResponse]:
    """刷新访问令牌（token 经 Authorization 头传递，不进 URL/访问日志）"""
    username = AuthService.verify_token(token)
    new_token = create_access_token(username)
    return success_response(
        data=LoginResponse(
            access_token=new_token, token_type="bearer", expires_in=1800
        ),
        message="Token 刷新成功",
    )
