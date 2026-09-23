"""AI 配置与模型管理路由"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..dependencies import AuthenticatedUser
from ..exceptions import APIException
from ..models.ai import (
    AiConfigData,
    AvailableModelItem,
    ImportModelsDevRequest,
    ModelTestRequest,
    ModelTestResponse,
    ModelsDevCatalogResponse,
    ProtocolHijackStatusResponse,
    TelemetryItem,
    UpdateProtocolHijackRequest,
)
from ..responses import APIResponse, success_response
from ..services.ai_service import AIService
from ..services.protocol_hijack import get_hijack_manager

router = APIRouter(prefix="/ai", tags=["AI配置与模型管理"])


@router.get(
    "/config",
    response_model=APIResponse[AiConfigData],
    response_class=JSONResponse,
    summary="获取完整的 AI 配置",
)
async def get_ai_config(user: AuthenticatedUser) -> APIResponse[AiConfigData]:
    """获取完整的 AI 配置"""
    try:
        data = AIService.get_ai_config()
        return success_response(data=data)
    except Exception as e:
        raise APIException(f"获取 AI 配置失败：{e!s}", code=500)


@router.post(
    "/config",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="保存 AI 配置",
)
async def save_ai_config(
    user: AuthenticatedUser, config: AiConfigData
) -> APIResponse[bool]:
    """保存 AI 配置并刷盘持久化"""
    try:
        result = AIService.save_ai_config(config)
        return success_response(data=result, message="AI 配置已成功保存")
    except Exception as e:
        raise APIException(f"保存 AI 配置失败：{e!s}", code=500)


@router.post(
    "/test",
    response_model=APIResponse[ModelTestResponse],
    response_class=JSONResponse,
    summary="测试模型连通性",
)
async def test_model(
    user: AuthenticatedUser, request: ModelTestRequest
) -> APIResponse[ModelTestResponse]:
    """测试指定模型的连通性与延迟"""
    try:
        result = await AIService.test_model_connectivity(request.model)
        return success_response(data=result)
    except Exception as e:
        raise APIException(f"模型测试发生异常：{e!s}", code=500)


@router.get(
    "/models",
    response_model=APIResponse[list[AvailableModelItem]],
    response_class=JSONResponse,
    summary="获取已配置的可用模型列表",
)
async def get_available_models(
    user: AuthenticatedUser,
) -> APIResponse[list[AvailableModelItem]]:
    """获取所有已配置的可用模型列表"""
    try:
        models = AIService.get_available_models()
        return success_response(data=models)
    except Exception as e:
        raise APIException(f"获取可用模型列表失败：{e!s}", code=500)


@router.get(
    "/models-dev/catalog",
    response_model=APIResponse[ModelsDevCatalogResponse],
    response_class=JSONResponse,
    summary="获取 models.dev 在线模型库目录",
)
async def get_models_dev_catalog(
    user: AuthenticatedUser,
    search: str | None = None,
) -> APIResponse[ModelsDevCatalogResponse]:
    """获取 models.dev 在线模型库，支持本地缓存与按关键字检索"""
    try:
        catalog = await AIService.fetch_models_dev_catalog(force_refresh=False)
        if search and search.strip():
            kw = search.strip().lower()
            filtered_providers = []
            for p in catalog.providers:
                if kw in p.id.lower() or kw in p.name.lower():
                    filtered_providers.append(p)
                else:
                    matched_models = [
                        m for m in p.models
                        if kw in m.id.lower() or kw in m.name.lower()
                    ]
                    if matched_models:
                        p_copy = p.model_copy()
                        p_copy.models = matched_models
                        p_copy.models_count = len(matched_models)
                        filtered_providers.append(p_copy)

            catalog.providers = filtered_providers
            catalog.total_providers = len(filtered_providers)
            catalog.total_models = sum(p.models_count for p in filtered_providers)

        return success_response(data=catalog)
    except Exception as e:
        raise APIException(f"获取 models.dev 在线目录失败：{e!s}", code=500)


@router.post(
    "/models-dev/refresh",
    response_model=APIResponse[ModelsDevCatalogResponse],
    response_class=JSONResponse,
    summary="强制从远程拉取并刷新 models.dev 缓存",
)
async def refresh_models_dev_catalog(
    user: AuthenticatedUser,
) -> APIResponse[ModelsDevCatalogResponse]:
    """强制重新从 https://models.dev/api.json 拉取并刷新缓存"""
    try:
        catalog = await AIService.fetch_models_dev_catalog(force_refresh=True)
        return success_response(data=catalog, message="models.dev 在线模型库已成功更新")
    except Exception as e:
        raise APIException(f"刷新 models.dev 缓存失败：{e!s}", code=500)


@router.post(
    "/models-dev/import",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="从 models.dev 导入服务商和模型",
)
async def import_models_dev_provider(
    user: AuthenticatedUser,
    request: ImportModelsDevRequest,
) -> APIResponse[bool]:
    """从 models.dev 快速导入服务商到当前 AI 配置"""
    try:
        result = await AIService.import_models_dev_provider(request)
        return success_response(data=result, message=f"已成功导入服务商 '{request.provider_id}'")
    except Exception as e:
        raise APIException(f"导入服务商失败：{e!s}", code=500)


@router.get(
    "/experimental/protocol-hijack",
    response_model=APIResponse[ProtocolHijackStatusResponse],
    response_class=JSONResponse,
    summary="获取实验性协议劫持状态与支持协议",
)
async def get_protocol_hijack_status(
    user: AuthenticatedUser,
) -> APIResponse[ProtocolHijackStatusResponse]:
    """获取当前协议劫持总开关状态与已支持的核心协议列表"""
    try:
        mgr = get_hijack_manager()
        status_data = ProtocolHijackStatusResponse(
            enabled=mgr.is_enabled(),
            supported_protocols=["chat", "response", "claude"],
            intercepted_count=mgr.intercepted_count,
        )
        return success_response(data=status_data)
    except Exception as e:
        raise APIException(f"获取协议劫持状态失败：{e!s}", code=500)


@router.post(
    "/experimental/protocol-hijack",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="更新实验性协议劫持总开关",
)
async def update_protocol_hijack_status(
    user: AuthenticatedUser,
    request: UpdateProtocolHijackRequest,
) -> APIResponse[bool]:
    """开启或关闭大模型协议适配与劫持系统"""
    try:
        mgr = get_hijack_manager()
        mgr.set_enabled(request.enabled)
        msg = "实验性协议适配与劫持已启用" if request.enabled else "实验性协议适配与劫持已关闭"
        return success_response(data=request.enabled, message=msg)
    except Exception as e:
        raise APIException(f"更新协议劫持状态失败：{e!s}", code=500)


@router.get(
    "/experimental/telemetry",
    response_model=APIResponse[list[TelemetryItem]],
    response_class=JSONResponse,
    summary="获取近期大模型调用抓包遥测记录",
)
async def get_protocol_telemetry(
    user: AuthenticatedUser,
    limit: int = 50,
) -> APIResponse[list[TelemetryItem]]:
    """获取最近拦截记录的大模型调用耗时、Token消耗与Prompt摘要"""
    try:
        mgr = get_hijack_manager()
        items = mgr.get_telemetry(limit=limit)
        return success_response(data=items)
    except Exception as e:
        raise APIException(f"获取调用遥测记录失败：{e!s}", code=500)


@router.delete(
    "/experimental/telemetry",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="清空调用抓包遥测记录",
)
async def clear_protocol_telemetry(
    user: AuthenticatedUser,
) -> APIResponse[bool]:
    """清空当前内存中的大模型调用抓包遥测历史"""
    try:
        mgr = get_hijack_manager()
        mgr.clear_telemetry()
        return success_response(data=True, message="遥测记录已清空")
    except Exception as e:
        raise APIException(f"清空遥测记录失败：{e!s}", code=500)

