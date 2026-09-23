"""系统路由"""
from fastapi import APIRouter

from ..dependencies import AuthenticatedUser
from ..models.system import BotStatus, SystemHealth, SystemStatus
from ..responses import APIResponse, success_response
from ..services.system_service import (
    check_network,
    get_bot_status,
    get_system_health,
    get_system_info,
    get_system_status,
    restart_bot,
)

router = APIRouter(prefix="/system", tags=["系统"])


@router.get("/ping", response_model=APIResponse[dict], summary="Ping 健康检查")
async def ping() -> APIResponse[dict]:
    """健康检查接口"""
    return success_response(data={"message": "pong"})


@router.get("/status", response_model=APIResponse[SystemStatus], summary="获取系统状态")
async def get_status(user: AuthenticatedUser) -> APIResponse[SystemStatus]:
    """获取当前系统状态"""
    status = await get_system_status()
    return success_response(data=status)


@router.get("/health", response_model=APIResponse[SystemHealth], summary="获取系统健康状态")
async def get_health(user: AuthenticatedUser) -> APIResponse[SystemHealth]:
    """获取系统健康状态"""
    health = await get_system_health()
    return success_response(data=health)


@router.get("/bot-status", response_model=APIResponse[BotStatus], summary="获取 Bot 状态")
async def get_bot_status_route(user: AuthenticatedUser) -> APIResponse[BotStatus]:
    """获取 Bot 运行状态"""
    status = await get_bot_status()
    return success_response(data=status)


@router.get("/network", response_model=APIResponse[dict], summary="检查网络连通性")
async def check_network_route(user: AuthenticatedUser) -> APIResponse[dict]:
    """检查网络连通性"""
    result = await check_network()
    return success_response(data=result)


@router.get("/info", response_model=APIResponse[dict], summary="获取详细系统信息")
async def get_system_info_route(user: AuthenticatedUser) -> APIResponse[dict]:
    """获取详细的系统信息"""
    info = await get_system_info()
    return success_response(data=info)


@router.post("/restart", response_model=APIResponse[bool], summary="重启 Bot")
async def restart_bot_route(user: AuthenticatedUser) -> APIResponse[bool]:
    """重启 Bot"""
    result = await restart_bot()
    return success_response(data=result, message="开始重启 Bot...")
