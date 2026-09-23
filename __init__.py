"""WebUI Next - 重构后的 WebUI 后端"""
import secrets

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
import nonebot
from nonebot.log import default_filter, default_format
from nonebot.plugin import PluginMetadata

from pathlib import Path
from fastapi.staticfiles import StaticFiles

from zhenxun.configs.config import Config as gConfig
from zhenxun.configs.utils import PluginExtraData, RegisterConfig
from zhenxun.services.log import logger, logger_
from zhenxun.utils.enum import PluginType
from zhenxun.utils.manager.priority_manager import PriorityLifecycle

# 导入配置以注册 CORS 中间件
from . import config as _config  # noqa: F401
from .exceptions import APIException
from .responses import error_response
from .routers import (
    ai_router,
    analytics_router,
    auth_router,
    config_router,
    dashboard_router,
    database_router,
    file_router,
    main_router,
    manage_router,
    plugin_router,
    sticker_router,
    store_router,
    system_router,
    theme_router,
)
from .routers.websocket import ws_chat_router, ws_log_router, ws_status_router
from .routers.debug_ws import router as ws_debug_router
from .services.log_service import LOG_STORAGE
from .services.webui_release import dist_ready, ensure_dist

__plugin_meta__ = PluginMetadata(
    name="WebUi Next",
    description="重构后的 WebUI API",
    usage='"""\n    """.strip(),',
    extra=PluginExtraData(
        author="NegiChan",
        version="0.2",
        plugin_type=PluginType.HIDDEN,
        configs=[
            RegisterConfig(
                module="web-ui",
                key="username",
                value="admin",
                help="前端管理用户名",
                type=str,
                default_value="admin",
            ),
            RegisterConfig(
                module="web-ui",
                key="password",
                value=None,
                help="前端管理密码",
                type=str,
                default_value=None,
            ),
            RegisterConfig(
                module="web-ui",
                key="secret",
                value=secrets.token_urlsafe(32),
                help="JWT 密钥",
                type=str,
                default_value=None,
            ),
        ],
    ).to_dict(),
)

driver = nonebot.get_driver()

gConfig.set_name("web-ui", "web-ui")

# HTTP API 路由 - 统一使用 /zhenxun/api/v1 前缀
BaseApiRouter = APIRouter(prefix="/zhenxun/api/v1")

BaseApiRouter.include_router(auth_router)
BaseApiRouter.include_router(ai_router)
BaseApiRouter.include_router(analytics_router)
BaseApiRouter.include_router(dashboard_router)
BaseApiRouter.include_router(main_router)
BaseApiRouter.include_router(plugin_router)
BaseApiRouter.include_router(system_router)
BaseApiRouter.include_router(file_router)
BaseApiRouter.include_router(config_router)
BaseApiRouter.include_router(database_router)
BaseApiRouter.include_router(store_router)
BaseApiRouter.include_router(theme_router)
BaseApiRouter.include_router(manage_router)
BaseApiRouter.include_router(sticker_router)
# 调试模拟状态的 HTTP 端点（同一路由里的 WS 端点经 WsApiRouter 暴露）
BaseApiRouter.include_router(ws_debug_router)

# WebSocket API 路由 - 统一使用 /zhenxun/ws/v1 前缀
WsApiRouter = APIRouter(prefix="/zhenxun/ws/v1")

WsApiRouter.include_router(ws_log_router)
WsApiRouter.include_router(ws_status_router)
WsApiRouter.include_router(ws_chat_router)
WsApiRouter.include_router(ws_debug_router)


@PriorityLifecycle.on_startup(priority=0)
async def _():
    import asyncio
    import re

    try:
        _tasks = []

        ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*m")

        async def log_sink(message: str):
            loop = None
            if not loop:
                try:
                    loop = asyncio.get_running_loop()
                except Exception as e:
                    logger.warning("Web Ui Next log_sink", e=e)

            if not loop:
                loop = asyncio.new_event_loop()

            clean_message = ANSI_ESCAPE_PATTERN.sub("", message.rstrip("\n"))
            _tasks.append(loop.create_task(LOG_STORAGE.add(clean_message)))

        logger_.add(
            log_sink,
            colorize=True,
            filter=default_filter,
            format=default_format
        )

        app: FastAPI = nonebot.get_app()

        @app.exception_handler(APIException)
        async def api_exception_handler(request, exc: APIException):
            return JSONResponse(
                status_code=exc.code,
                content=error_response(
                    message=exc.message,
                    code=exc.code,
                    data=exc.data
                ).model_dump(),
            )

        @app.exception_handler(Exception)
        async def general_exception_handler(request, exc: Exception):
            logger.error(f"Unexpected error: {exc!s}", "WebUiNext")
            return JSONResponse(
                status_code=500,
                content=error_response(
                    message=f"服务器内部错误：{exc!s}",
                    code=500
                ).model_dump(),
            )

        app.include_router(BaseApiRouter)
        app.include_router(WsApiRouter)

        # ==========================
        # 挂载前端 dist 到 /next
        # ==========================
        # dist 随前端构建产物放到插件数据目录，升级前端只覆盖此处、不碰插件代码
        dist_path = Path().resolve() / "data" / "web_ui" / "dist"
        dist_path.mkdir(parents=True, exist_ok=True)

        app.mount(
            "/next",
            StaticFiles(
                directory=str(dist_path),
                html=True  # Vue history 模式支持
            ),
            name="webui-next"
        )
        logger.info("<g>WebUI Next 前端挂载成功: /next</g>", "WebUiNext")

        # 本地没有前端产物时，后台从 GitHub Release 拉取（不阻塞 bot 启动）
        if dist_ready():
            logger.info("检测到本地前端 dist，跳过自动拉取", "WebUiNext")
        else:
            logger.warning(
                "本地 data/web_ui/dist 为空，后台尝试从 GitHub Release 拉取前端…",
                "WebUiNext",
            )
            asyncio.create_task(ensure_dist())

        # ==========================
        # 激活实验性 AI 协议扩展与劫持
        # ==========================
        try:
            from .services.protocol_hijack import install_protocol_hijack
            install_protocol_hijack()
        except Exception as e:
            logger.warning(f"实验性 AI 协议扩展加载警告: {e}", "WebUiNext")

        logger.info("<g>WebUI Next API 启动成功</g>", "WebUiNext")

    except Exception as e:
        logger.error("<g>WebUI Next API 启动失败</g>", "WebUiNext", e=e)
