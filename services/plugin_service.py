"""插件服务"""
import asyncio
import json
from pathlib import Path

import nonebot

from zhenxun.configs.config import Config
from zhenxun.configs.utils import ConfigGroup
from zhenxun.models.plugin_info import PluginInfo as DbPluginInfo
from zhenxun.services.cache.runtime_cache import PluginInfoMemoryCache
from zhenxun.utils.enum import BlockType, PluginType
from tortoise.expressions import Q

from ..exceptions import NotFoundException
from ..models.plugin import (
    PluginConfigItem,
    PluginConfigResult,
    PluginInfo,
    PluginListRequest,
    PluginListResult,
    PluginSettingsRequest,
    PluginToggleRequest,
)

# 置顶/常驻标记持久化文件（与主题配置同目录）
MARKS_FILE = Path().resolve() / "data" / "web_ui" / "plugin_marks.json"


class PluginService:
    """插件服务"""

    @staticmethod
    async def get_plugin_list(request: PluginListRequest) -> PluginListResult:
        """获取插件列表

        参数:
            request: 列表请求

        返回:
            PluginListResult: 插件列表结果
        """
        query = DbPluginInfo.filter(load_status=True)

        # 搜索过滤
        if request.search:
            search = request.search.lower()
            query = query.filter(
                Q(name__icontains=search)
                | Q(module__icontains=search)
                | Q(author__icontains=search)
            )

        # 状态过滤
        if request.status is not None:
            query = query.filter(status=request.status)

        # 类型过滤
        if request.plugin_type:
            query = query.filter(plugin_type=request.plugin_type)

        # 获取总数
        total = await query.count()

        # 分页
        offset = (request.page - 1) * request.page_size
        plugins = await query.limit(request.page_size).offset(offset)

        # 转换为模型，同时清理不存在的插件记录
        items = []
        modules_to_delete = []

        for plugin in plugins:
            # 检查插件是否存在：通过 nonebot 是否能获取到插件
            nb_plugin = nonebot.get_plugin_by_module_name(plugin.module_path)

            if nb_plugin is None:
                # 插件未加载，标记删除
                modules_to_delete.append(plugin.id)
                continue

            # 参考旧 web_ui 的实现逻辑
            # is_builtin: builtin_plugins 路径或 HIDDEN 类型的插件
            is_builtin = (
                "builtin_plugins" in plugin.module_path
                or plugin.plugin_type == PluginType.HIDDEN
            )
            # allow_switch 和 allow_setting: 非 HIDDEN 类型的插件允许开关和设置
            plugin_type_enum = plugin.plugin_type
            is_hidden = plugin_type_enum == PluginType.HIDDEN if plugin_type_enum else False
            allow_switch = not is_hidden
            allow_setting = not is_hidden

            # 从 nonebot 插件 metadata 中获取描述
            description = ""
            if nb_plugin.metadata:
                description = nb_plugin.metadata.description or ""

            items.append(
                PluginInfo(
                    id=plugin.id,
                    module=plugin.module,
                    name=plugin.name,
                    description=description,
                    author=plugin.author or "",
                    version=plugin.version or "0",
                    plugin_type=plugin.plugin_type.value if plugin.plugin_type else "",
                    is_enabled=plugin.status,
                    allow_switch=allow_switch,
                    allow_setting=allow_setting,
                    is_builtin=is_builtin,
                )
            )

        # 清理不存在的插件记录
        if modules_to_delete:
            await DbPluginInfo.filter(id__in=modules_to_delete).delete()

        return PluginListResult(
            items=items,
            total=total - len(modules_to_delete),
            page=request.page,
            page_size=request.page_size,
            has_next=offset + len(items) < total - len(modules_to_delete),
            has_prev=request.page > 1,
        )

    @staticmethod
    async def toggle_plugin(request: PluginToggleRequest) -> bool:
        """切换插件状态

        参数:
            request: 切换请求

        返回:
            bool: 是否成功

        异常:
            NotFoundException: 插件不存在
        """
        plugin = await DbPluginInfo.filter(module=request.module).first()
        if not plugin:
            raise NotFoundException(f"插件 {request.module} 不存在")
        plugin.status = request.enable
        plugin.block_type = None if request.enable else BlockType.ALL
        await plugin.save()
        await PluginInfoMemoryCache.upsert_from_model(plugin)
        return True

    @staticmethod
    async def update_plugin_settings(request: PluginSettingsRequest) -> bool:
        """更新插件通用设置（权限等级 / 限制超级用户）

        参数:
            request: 设置请求，字段为 None 时跳过对应项

        返回:
            bool: 是否成功

        异常:
            NotFoundException: 插件不存在
        """
        plugin = await DbPluginInfo.filter(module=request.module).first()
        if not plugin:
            raise NotFoundException(f"插件 {request.module} 不存在")
        if request.level is not None:
            plugin.level = request.level
        if request.limit_superuser is not None:
            plugin.limit_superuser = request.limit_superuser
        await plugin.save()
        await PluginInfoMemoryCache.upsert_from_model(plugin)
        return True

    @staticmethod
    async def get_marks() -> dict:
        """读取置顶/常驻标记

        返回:
            dict: {"pinned": [...], "resident": [...]}
        """
        try:
            raw = await asyncio.to_thread(
                MARKS_FILE.read_text, encoding="utf-8"
            )
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return {
                    "pinned": parsed.get("pinned") or [],
                    "resident": parsed.get("resident") or [],
                }
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        return {"pinned": [], "resident": []}

    @staticmethod
    async def save_marks(pinned: list[str], resident: list[str]) -> bool:
        """写入置顶/常驻标记（全量覆盖）"""

        def _write() -> None:
            MARKS_FILE.parent.mkdir(parents=True, exist_ok=True)
            MARKS_FILE.write_text(
                json.dumps(
                    {"pinned": pinned, "resident": resident},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

        await asyncio.to_thread(_write)
        return True

    @staticmethod
    async def get_plugin_config(module: str) -> PluginConfigResult:
        """获取插件配置

        参数:
            module: 模块名

        返回:
            PluginConfigResult: 配置结果

        异常:
            NotFoundException: 插件不存在
        """
        plugin = await DbPluginInfo.filter(module=module).first()
        if not plugin:
            raise NotFoundException(f"插件 {module} 不存在")

        configs = Config.get(module)
        config_items = []

        if configs:
            for key, config_group in configs.configs.items():
                config_items.append(
                    PluginConfigItem(
                        module=module,
                        key=key,
                        value=str(config_group.value),
                        description=config_group.help,
                    )
                )

        return PluginConfigResult(
            module=module,
            name=plugin.name,
            configs=config_items,
        )

    @staticmethod
    def __build_plugin_config(module: str, cfg: str, config: ConfigGroup) -> dict:
        """构建插件配置数据

        参数:
            module: 模块名
            cfg: 配置键
            config: 配置组

        返回:
            dict: 配置数据
        """
        import re

        type_str = ""
        type_inner = None
        ct = str(config.configs[cfg].type)
        if r := re.search(r"<class '(.*)'>", ct):
            type_str = r[1]
        elif (r := re.search(r"typing\.(.*)\[(.*)\]", ct)) or (
            r := re.search(r"(.*)\[(.*)\]", ct)
        ):
            type_str = r[1]
            if type_str:
                type_str = type_str.lower()
            type_inner = r[2]
            if type_inner:
                type_inner = [x.strip() for x in type_inner.split(",")]
        else:
            type_str = ct

        return {
            "module": module,
            "key": cfg,
            "value": config.configs[cfg].value,
            "help": config.configs[cfg].help,
            "default_value": config.configs[cfg].default_value,
            "type": type_str,
            "type_inner": type_inner,
        }

    @staticmethod
    async def get_plugin_detail(module: str) -> dict:
        """获取插件详情

        参数:
            module: 模块名

        返回:
            dict: 插件详情

        异常:
            NotFoundException: 插件不存在
        """
        plugin = await DbPluginInfo.filter(module=module).first()
        if not plugin:
            raise NotFoundException(f"插件 {module} 不存在")

        config_list = []
        if config := Config.get(module):
            config_list.extend(
                PluginService.__build_plugin_config(module, cfg, config)
                for cfg in config.configs
            )

        return {
            "id": plugin.id,
            "module": module,
            "plugin_name": plugin.name,
            "default_status": plugin.default_status,
            "limit_superuser": plugin.limit_superuser,
            "cost_gold": plugin.cost_gold,
            "menu_type": plugin.menu_type,
            "version": plugin.version or "0",
            "level": plugin.level,
            "status": plugin.status,
            "author": plugin.author,
            "config_list": config_list,
            "block_type": plugin.block_type,
        }
