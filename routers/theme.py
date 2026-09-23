"""主题路由：管理员全局主题的读取 / 保存（保存后广播多端同步）"""
from fastapi import APIRouter

from ..dependencies import AuthenticatedUser
from ..responses import APIResponse, success_response
from ..services.theme_service import get_theme, update_theme
from .websocket import _broadcast_status_event

router = APIRouter(prefix="/theme", tags=["主题"])


@router.get("", response_model=APIResponse[dict], summary="获取主题配置")
async def get_theme_route(user: AuthenticatedUser) -> APIResponse[dict]:
    """读取管理员的全局主题配置"""
    return success_response(data=await get_theme())


@router.put("", response_model=APIResponse[dict], summary="保存主题配置")
async def update_theme_route(
    payload: dict, user: AuthenticatedUser
) -> APIResponse[dict]:
    """保存主题配置，并通过状态 WS 广播 theme_update 事件"""
    saved = await update_theme(payload)
    await _broadcast_status_event({"type": "theme_update", "data": saved})
    return success_response(data=saved)
