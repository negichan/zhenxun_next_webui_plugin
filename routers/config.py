"""配置路由"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..dependencies import AuthenticatedUser
from ..models.config import (
    ConfigSaveRequest,
    ConfigValueSetRequest,
    EnvFileContent,
    PluginConfigSaveRequest,
    YamlConfigContent,
)
from ..responses import APIResponse, success_response
from ..services.config_service import ConfigService

router = APIRouter(prefix="/config", tags=["配置管理"])


@router.get(
    "/env",
    response_model=APIResponse[EnvFileContent],
    response_class=JSONResponse,
    summary="读取环境变量文件",
)
async def get_env_file(
    user: AuthenticatedUser, name: str
) -> APIResponse[EnvFileContent]:
    """读取环境变量文件并返回结构化数据"""
    result = ConfigService.parse_env_file(name)
    return success_response(data=result)


@router.post(
    "/env",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="保存环境变量文件",
)
async def save_env_file(
    user: AuthenticatedUser, request: ConfigSaveRequest
) -> APIResponse[bool]:
    """保存环境变量文件"""
    result = ConfigService.save_env_file(request)
    return success_response(data=result, message="保存成功")


@router.get(
    "/yaml",
    response_model=APIResponse[YamlConfigContent],
    response_class=JSONResponse,
    summary="读取 config.yaml 配置文件",
)
async def get_yaml_file(
    user: AuthenticatedUser,
) -> APIResponse[YamlConfigContent]:
    """读取 config.yaml 配置文件"""
    result = ConfigService.read_yaml()
    return success_response(data=result)


@router.post(
    "/yaml",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="保存 config.yaml 配置文件",
)
async def save_yaml_file(
    user: AuthenticatedUser, content: str
) -> APIResponse[bool]:
    """保存 config.yaml 配置文件"""
    result = ConfigService.save_yaml(content)
    return success_response(data=result, message="保存成功")


@router.get(
    "/value",
    response_model=APIResponse[str | None],
    response_class=JSONResponse,
    summary="获取配置值",
)
async def get_config_value(
    user: AuthenticatedUser, module: str, key: str
) -> APIResponse[str | None]:
    """获取指定模块的配置值"""
    value = ConfigService.get_config_value(module, key)
    return success_response(data=value)


@router.post(
    "/value",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="设置配置值",
)
async def set_config_value(
    user: AuthenticatedUser, request: ConfigValueSetRequest
) -> APIResponse[bool]:
    """设置指定模块的配置值"""
    result = ConfigService.set_config_value(
        request.module, request.key, request.value
    )
    return success_response(data=result, message="设置成功")


@router.post(
    "/restart",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="重启 Bot",
)
async def restart_bot(user: AuthenticatedUser) -> APIResponse[bool]:
    """重启 Bot"""
    result = await ConfigService.restart_bot()
    return success_response(data=result, message="开始重启 Bot...")


@router.post(
    "/plugin/batch",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="批量设置插件配置",
)
async def batch_set_plugin_configs(
    user: AuthenticatedUser, request: PluginConfigSaveRequest
) -> APIResponse[bool]:
    """批量设置插件配置"""
    result = ConfigService.batch_set_plugin_configs(request.module, request.configs)
    if result:
        return success_response(data=result, message="保存成功")
    return success_response(data=result, message="部分配置保存失败")
