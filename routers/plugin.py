"""插件路由"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..dependencies import AuthenticatedUser
from ..models.plugin import (
    PluginConfigResult,
    PluginListRequest,
    PluginListResult,
    PluginMarksRequest,
    PluginSettingsRequest,
    PluginToggleRequest,
)
from ..responses import APIResponse, success_response
from ..services.plugin_service import PluginService

router = APIRouter(prefix="/plugin", tags=["插件管理"])


@router.post(
    "/list",
    response_model=APIResponse[PluginListResult],
    response_class=JSONResponse,
    summary="获取插件列表",
)
async def get_plugin_list(
    user: AuthenticatedUser, request: PluginListRequest
) -> APIResponse[PluginListResult]:
    """获取插件列表

    支持搜索、状态过滤、类型过滤和分页。
    """
    result = await PluginService.get_plugin_list(request)
    return success_response(data=result)


@router.post(
    "/toggle",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="切换插件状态",
)
async def toggle_plugin(
    user: AuthenticatedUser, request: PluginToggleRequest
) -> APIResponse[bool]:
    """切换插件启用/禁用状态"""
    result = await PluginService.toggle_plugin(request)
    return success_response(data=result, message="状态已更新")


@router.post(
    "/settings",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="更新插件通用设置",
)
async def update_plugin_settings(
    user: AuthenticatedUser, request: PluginSettingsRequest
) -> APIResponse[bool]:
    """更新所有插件默认拥有的设置项（权限等级 / 限制超级用户）"""
    result = await PluginService.update_plugin_settings(request)
    return success_response(data=result, message="设置已更新")


@router.get(
    "/marks",
    response_model=APIResponse[dict],
    response_class=JSONResponse,
    summary="获取插件标记",
)
async def get_plugin_marks(user: AuthenticatedUser) -> APIResponse[dict]:
    """获取置顶/常驻插件标记"""
    result = await PluginService.get_marks()
    return success_response(data=result)


@router.post(
    "/marks",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="保存插件标记",
)
async def save_plugin_marks(
    user: AuthenticatedUser, request: PluginMarksRequest
) -> APIResponse[bool]:
    """保存置顶/常驻插件标记（全量覆盖）"""
    result = await PluginService.save_marks(request.pinned, request.resident)
    return success_response(data=result, message="标记已保存")


@router.get(
    "/config/{module}",
    response_model=APIResponse[PluginConfigResult],
    response_class=JSONResponse,
    summary="获取插件配置",
)
async def get_plugin_config(
    user: AuthenticatedUser, module: str
) -> APIResponse[PluginConfigResult]:
    """获取指定插件的配置"""
    result = await PluginService.get_plugin_config(module)
    return success_response(data=result)


@router.get(
    "/detail/{module}",
    response_model=APIResponse[dict],
    response_class=JSONResponse,
    summary="获取插件详情",
)
async def get_plugin_detail(
    user: AuthenticatedUser, module: str
) -> APIResponse[dict]:
    """获取指定插件的详细信息"""
    result = await PluginService.get_plugin_detail(module)
    return success_response(data=result)
