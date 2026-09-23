"""AI / LLM 配置与模型管理服务"""
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any

import httpx

from zhenxun.configs.config import Config as gConfig
from zhenxun.configs.path_config import DATA_PATH
from zhenxun.services.log import logger

from ..models.ai import (
    AiConfigData,
    AvailableModelItem,
    ContextSettingsItem,
    DefaultModelsItem,
    ImportModelsDevRequest,
    ModelDetailItem,
    ModelTestResponse,
    ModelsDevCatalogResponse,
    ModelsDevModelItem,
    ModelsDevProviderItem,
    ProviderItem,
)

MODELS_JSON_PATH = DATA_PATH / "ai" / "models.json"
MODELS_DEV_CACHE_PATH = DATA_PATH / "ai" / "models_dev_cache.json"
MODELS_DEV_REMOTE_URL = "https://models.dev/api.json"
_LAST_MODELS_JSON_MTIME: float = 0.0



class AIService:
    """AI 配置与模型管理业务服务 (插件层实现)"""

    @staticmethod
    def _parse_provider_item(p: Any) -> ProviderItem:
        """安全解析服务商配置对象"""
        if hasattr(p, "model_dump"):
            data = p.model_dump()
        elif isinstance(p, dict):
            data = p
        else:
            data = dict(p)

        clean_models = []
        for m in data.get("models", []):
            if hasattr(m, "model_dump"):
                m_dict = m.model_dump()
            elif isinstance(m, dict):
                m_dict = m
            else:
                m_dict = {"model_name": getattr(m, "model_name", str(m))}

            clean_models.append(
                ModelDetailItem(
                    model_name=m_dict.get("model_name", ""),
                    temperature=m_dict.get("temperature"),
                    max_tokens=m_dict.get("max_tokens") or m_dict.get("max_output_tokens"),
                    max_output_tokens=m_dict.get("max_output_tokens"),
                    reasoning_effort=m_dict.get("reasoning_effort"),
                )
            )

        return ProviderItem(
            name=data.get("name", ""),
            api_key=data.get("api_key", ""),
            api_base=data.get("api_base"),
            api_type=data.get("api_type", "openai"),
            temperature=data.get("temperature"),
            max_output_tokens=data.get("max_output_tokens"),
            timeout=data.get("timeout", 180),
            models=clean_models,
            enabled=data.get("enabled", True),
            priority=data.get("priority", 1),
            weight=data.get("weight", 10),
        )

    @classmethod
    def _sync_models_json_to_config(cls) -> bool:
        """检测 data/ai/models.json 变更，若有修改则同步写回 plugins2config.yaml"""
        global _LAST_MODELS_JSON_MTIME
        if not MODELS_JSON_PATH.exists():
            return False

        try:
            current_mtime = MODELS_JSON_PATH.stat().st_mtime
            if current_mtime <= _LAST_MODELS_JSON_MTIME:
                return False

            with open(MODELS_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                return False

            changed = False

            # 同步各节点到 gConfig
            if "providers" in data:
                gConfig.set_config("AI", "PROVIDERS", data["providers"], auto_save=False)
                changed = True
            elif "PROVIDERS" in data:
                gConfig.set_config("AI", "PROVIDERS", data["PROVIDERS"], auto_save=False)
                changed = True

            if "default_models" in data:
                gConfig.set_config("AI", "DEFAULT_MODELS", data["default_models"], auto_save=False)
                changed = True
            elif "DEFAULT_MODELS" in data:
                gConfig.set_config("AI", "DEFAULT_MODELS", data["DEFAULT_MODELS"], auto_save=False)
                changed = True

            if "model_groups" in data:
                gConfig.set_config("AI", "MODEL_GROUPS", data["model_groups"], auto_save=False)
                changed = True
            elif "MODEL_GROUPS" in data:
                gConfig.set_config("AI", "MODEL_GROUPS", data["MODEL_GROUPS"], auto_save=False)
                changed = True

            if "context_settings" in data:
                gConfig.set_config("AI", "CONTEXT_SETTINGS", data["context_settings"], auto_save=False)
                changed = True

            if "agent_settings" in data:
                gConfig.set_config("AI", "AGENT_SETTINGS", data["agent_settings"], auto_save=False)
                changed = True

            if "client_settings" in data:
                gConfig.set_config("AI", "CLIENT_SETTINGS", data["client_settings"], auto_save=False)
                changed = True

            if "debug_log" in data:
                gConfig.set_config("AI", "DEBUG_LOG", data["debug_log"], auto_save=False)
                changed = True

            if "sandbox" in data:
                gConfig.set_config("AI", "SANDBOX", data["sandbox"], auto_save=False)
                changed = True

            if "provider_settings" in data:
                gConfig.set_config("AI", "PROVIDER_SETTINGS", data["provider_settings"], auto_save=False)
                changed = True

            if changed:
                gConfig.save(save_simple_data=True)
                _LAST_MODELS_JSON_MTIME = current_mtime
                logger.info("检测到 data/ai/models.json 发生变动，已自动同步更新至 plugins2config.yaml", "WebUI-AI")

                try:
                    from zhenxun.services.ai.config.manager import get_llm_config
                    get_llm_config.cache_clear()
                except Exception:
                    pass

                return True
        except Exception as e:
            logger.warning(f"同步 data/ai/models.json 到 Config 失败: {e}", "WebUI-AI")
        return False

    @classmethod
    def _dump_config_to_models_json(cls, data: AiConfigData) -> None:
        """将当前 AI 配置持久化写入 data/ai/models.json 作为镜像"""
        global _LAST_MODELS_JSON_MTIME
        try:
            MODELS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
            dump_data = data.model_dump()
            with open(MODELS_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(dump_data, f, ensure_ascii=False, indent=2)

            _LAST_MODELS_JSON_MTIME = MODELS_JSON_PATH.stat().st_mtime
            logger.info("已同步写入最新 AI 配置至 data/ai/models.json", "WebUI-AI")
        except Exception as e:
            logger.warning(f"写入 data/ai/models.json 失败: {e}", "WebUI-AI")

    @classmethod
    def get_ai_config(cls) -> AiConfigData:
        """获取当前完整的 AI 配置"""
        # 1. 优先检查 models.json 是否被外部手动改动过，若有变动先同步刷入 Config
        cls._sync_models_json_to_config()

        # 2. 读取配置
        providers_raw = gConfig.get_config("AI", "PROVIDERS", default=[])
        default_models_raw = gConfig.get_config("AI", "DEFAULT_MODELS", default={})
        model_groups_raw = gConfig.get_config("AI", "MODEL_GROUPS", default={})
        context_settings_raw = gConfig.get_config("AI", "CONTEXT_SETTINGS", default={})
        agent_settings_raw = gConfig.get_config("AI", "AGENT_SETTINGS", default={})
        client_settings_raw = gConfig.get_config("AI", "CLIENT_SETTINGS", default={})
        debug_log_raw = gConfig.get_config("AI", "DEBUG_LOG", default={})
        sandbox_raw = gConfig.get_config("AI", "SANDBOX", default={})
        provider_settings_raw = gConfig.get_config("AI", "PROVIDER_SETTINGS", default={})

        provider_items = [cls._parse_provider_item(p) for p in providers_raw] if providers_raw else []

        result = AiConfigData(
            providers=provider_items,
            default_models=DefaultModelsItem.model_validate(default_models_raw) if default_models_raw else DefaultModelsItem(),
            model_groups=model_groups_raw or {},
            context_settings=ContextSettingsItem.model_validate(context_settings_raw) if context_settings_raw else ContextSettingsItem(),
            agent_settings=agent_settings_raw or {},
            client_settings=client_settings_raw or {},
            debug_log=debug_log_raw or {},
            sandbox=sandbox_raw or {},
            provider_settings=provider_settings_raw or {},
        )

        # 3. 如果 models.json 尚不存在，则自动初始化生成一份
        if not MODELS_JSON_PATH.exists():
            cls._dump_config_to_models_json(result)

        return result

    @classmethod
    def save_ai_config(cls, data: AiConfigData) -> bool:
        """保存 AI 全局配置并同步写入 plugins2config.yaml 和 data/ai/models.json"""
        try:
            providers_dict = [p.model_dump(exclude_none=True) for p in data.providers]
            default_models_dict = data.default_models.model_dump(exclude_none=True)
            model_groups_dict = data.model_groups
            context_settings_dict = data.context_settings.model_dump()
            agent_settings_dict = data.agent_settings.model_dump()
            client_settings_dict = data.client_settings.model_dump()
            debug_log_dict = data.debug_log.model_dump()
            sandbox_dict = data.sandbox.model_dump()
            provider_settings_dict = data.provider_settings.model_dump()

            # 1. 写入真寻主配置系统并刷盘到 plugins2config.yaml
            gConfig.set_config("AI", "PROVIDERS", providers_dict, auto_save=False)
            gConfig.set_config("AI", "DEFAULT_MODELS", default_models_dict, auto_save=False)
            gConfig.set_config("AI", "MODEL_GROUPS", model_groups_dict, auto_save=False)
            gConfig.set_config("AI", "CONTEXT_SETTINGS", context_settings_dict, auto_save=False)
            gConfig.set_config("AI", "AGENT_SETTINGS", agent_settings_dict, auto_save=False)
            gConfig.set_config("AI", "CLIENT_SETTINGS", client_settings_dict, auto_save=False)
            gConfig.set_config("AI", "DEBUG_LOG", debug_log_dict, auto_save=False)
            gConfig.set_config("AI", "SANDBOX", sandbox_dict, auto_save=False)
            gConfig.set_config("AI", "PROVIDER_SETTINGS", provider_settings_dict, auto_save=True)

            try:
                from zhenxun.services.ai.config.manager import get_llm_config
                get_llm_config.cache_clear()
            except Exception:
                pass

            # 2. 同步写入一份到 data/ai/models.json
            cls._dump_config_to_models_json(data)

            logger.info("AI 配置已成功保存至 plugins2config.yaml 与 data/ai/models.json", "WebUI-AI")
            return True
        except Exception as e:
            logger.error(f"保存 AI 配置失败: {e}", "WebUI-AI")
            raise e

    @staticmethod
    async def test_model_connectivity(model_name_str: str) -> ModelTestResponse:
        """测试指定模型的连通性与响应时间"""
        start_time = time.monotonic()
        try:
            from zhenxun.services.ai.llm.api import chat

            await chat("你好，请简要回复一个词确认连通性。", model=model_name_str)
            end_time = time.monotonic()
            latency = round((end_time - start_time) * 1000, 2)
            return ModelTestResponse(
                success=True,
                message=f"模型 '{model_name_str}' 连接正常",
                latency_ms=latency,
            )
        except Exception as e:
            end_time = time.monotonic()
            latency = round((end_time - start_time) * 1000, 2)
            user_msg = getattr(e, "user_friendly_message", str(e))
            return ModelTestResponse(
                success=False,
                message=f"连接测试失败: {user_msg}",
                latency_ms=latency,
            )

    @classmethod
    def get_available_models(cls) -> list[AvailableModelItem]:
        """获取所有当前配置的可用模型列表"""
        cfg = cls.get_ai_config()
        result: list[AvailableModelItem] = []
        for p in cfg.providers:
            for m in p.models:
                result.append(
                    AvailableModelItem(
                        id=f"{p.name}/{m.model_name}",
                        provider=p.name,
                        model_name=m.model_name,
                        is_available=True,
                    )
                )
        return result

    @staticmethod
    def _map_models_dev_api_type_and_base(provider_id: str, npm: str | None, api: str | None) -> tuple[str, str | None]:
        """将 models.dev 的 npm/provider 映射为真寻支持的 api_type 与默认 api_base"""
        p_id_lower = provider_id.lower()
        npm_lower = (npm or "").lower()

        if "google" in npm_lower or p_id_lower in ["google", "gemini"]:
            api_type = "gemini"
            default_base = "https://generativelanguage.googleapis.com"
        elif "anthropic" in npm_lower or p_id_lower in ["anthropic", "claude"]:
            api_type = "claude"
            default_base = "https://api.anthropic.com"
        elif "openrouter" in npm_lower or p_id_lower == "openrouter":
            api_type = "openrouter"
            default_base = "https://openrouter.ai/api/v1"
        elif p_id_lower == "deepseek":
            api_type = "deepseek"
            default_base = "https://api.deepseek.com"
        elif p_id_lower in ["volcengine", "doubao", "ark"]:
            api_type = "doubao"
            default_base = "https://ark.cn-beijing.volces.com/api/v3"
        elif p_id_lower in ["zhipu", "z-ai", "glm"]:
            api_type = "glm"
            default_base = "https://open.bigmodel.cn/api/paas/v4"
        elif p_id_lower in ["minimax"]:
            api_type = "minimax"
            default_base = "https://api.minimax.chat/v1"
        elif p_id_lower in ["mimo", "xiaomi"]:
            api_type = "mimo"
            default_base = "https://api.mimo.mi.com/v1"
        elif p_id_lower == "openai":
            api_type = "openai"
            default_base = "https://api.openai.com/v1"
        elif p_id_lower == "groq":
            api_type = "openai"
            default_base = "https://api.groq.com/openai/v1"
        elif p_id_lower == "mistral":
            api_type = "openai"
            default_base = "https://api.mistral.ai/v1"
        elif p_id_lower in ["siliconflow", "siliconflow-cn"]:
            api_type = "openai"
            default_base = "https://api.siliconflow.cn/v1"
        elif p_id_lower in ["moonshot", "moonshotai"]:
            api_type = "openai"
            default_base = "https://api.moonshot.ai/v1"
        else:
            api_type = "openai"
            default_base = None

        api_base = api or default_base
        return api_type, api_base

    @classmethod
    def _parse_models_dev_raw_dict(cls, data: dict) -> ModelsDevCatalogResponse:
        """清洗并格式化 models.dev 原始字典"""
        providers: list[ModelsDevProviderItem] = []
        for p_id, p in data.items():
            if not isinstance(p, dict):
                continue
            npm = p.get("npm")
            api = p.get("api")
            api_type, api_base = cls._map_models_dev_api_type_and_base(p_id, npm, api)

            models: list[ModelsDevModelItem] = []
            for m_id, m in p.get("models", {}).items():
                if not isinstance(m, dict):
                    continue
                limit = m.get("limit") if isinstance(m.get("limit"), dict) else {}
                models.append(
                    ModelsDevModelItem(
                        id=m.get("id", m_id),
                        name=m.get("name", m_id),
                        description=m.get("description"),
                        context_limit=limit.get("context"),
                        max_output_tokens=limit.get("output"),
                        reasoning=bool(m.get("reasoning", False)),
                        tool_call=bool(m.get("tool_call", True)),
                        temperature=bool(m.get("temperature", True)),
                        release_date=m.get("release_date"),
                    )
                )

            providers.append(
                ModelsDevProviderItem(
                    id=p_id,
                    name=p.get("name", p_id),
                    api_base=api_base,
                    api_type=api_type,
                    npm=npm,
                    doc=p.get("doc"),
                    env=p.get("env") or [],
                    models_count=len(models),
                    models=models,
                )
            )

        # 排序：将主流常用提供商排在最前
        priority_keys = [
            "deepseek",
            "google",
            "openai",
            "anthropic",
            "openrouter",
            "siliconflow",
            "volcengine",
            "z-ai",
            "minimax",
            "groq",
            "mistral",
            "moonshotai",
        ]

        def _sort_key(item: ModelsDevProviderItem):
            try:
                idx = priority_keys.index(item.id.lower())
                return (0, idx)
            except ValueError:
                return (1, item.name.lower())

        providers.sort(key=_sort_key)

        mtime_str = None
        if MODELS_DEV_CACHE_PATH.exists():
            mtime_str = datetime.fromtimestamp(
                MODELS_DEV_CACHE_PATH.stat().st_mtime, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S")

        return ModelsDevCatalogResponse(
            total_providers=len(providers),
            total_models=sum(p.models_count for p in providers),
            cached_at=mtime_str or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            providers=providers,
        )

    @classmethod
    async def fetch_models_dev_catalog(cls, force_refresh: bool = False) -> ModelsDevCatalogResponse:
        """获取 models.dev 在线模型库目录，支持本地文件缓存与平滑回退"""
        # 1. 若无需强制刷新且本地已有缓存，直接从缓存读取
        if not force_refresh and MODELS_DEV_CACHE_PATH.exists():
            try:
                with open(MODELS_DEV_CACHE_PATH, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
                if isinstance(raw_data, dict):
                    return cls._parse_models_dev_raw_dict(raw_data)
            except Exception as e:
                logger.warning(f"读取 models.dev 本地缓存失败: {e}，将尝试在线拉取", "WebUI-AI")

        # 2. 在线拉取 https://models.dev/api.json
        try:
            logger.info("正在从 https://models.dev/api.json 拉取全球模型库...", "WebUI-AI")
            async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
                resp = await client.get(MODELS_DEV_REMOTE_URL)
                resp.raise_for_status()
                raw_data = resp.json()

            if isinstance(raw_data, dict):
                # 保存到本地缓存
                MODELS_DEV_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                with open(MODELS_DEV_CACHE_PATH, "w", encoding="utf-8") as f:
                    json.dump(raw_data, f, ensure_ascii=False)
                logger.info(f"models.dev 模型库拉取并缓存成功，包含 {len(raw_data)} 家服务商", "WebUI-AI")
                return cls._parse_models_dev_raw_dict(raw_data)
        except Exception as e:
            logger.error(f"在线拉取 models.dev 失败: {e}", "WebUI-AI")
            # 若拉取失败但存在历史缓存，则降级返回历史缓存
            if MODELS_DEV_CACHE_PATH.exists():
                try:
                    with open(MODELS_DEV_CACHE_PATH, "r", encoding="utf-8") as f:
                        raw_data = json.load(f)
                    if isinstance(raw_data, dict):
                        logger.warning("已降级使用历史 models.dev 本地缓存", "WebUI-AI")
                        return cls._parse_models_dev_raw_dict(raw_data)
                except Exception:
                    pass
            raise RuntimeError(f"拉取 models.dev 失败且无可用本地缓存：{e}")

    @classmethod
    async def import_models_dev_provider(cls, req: ImportModelsDevRequest) -> bool:
        """从 models.dev 导入服务商和指定模型到当前系统的 AI 配置中"""
        catalog = await cls.fetch_models_dev_catalog(force_refresh=False)
        target_p = next((p for p in catalog.providers if p.id.lower() == req.provider_id.lower()), None)
        if not target_p:
            raise ValueError(f"未在 models.dev 中找到服务商 '{req.provider_id}'")

        current_cfg = cls.get_ai_config()
        p_name = req.provider_name or target_p.name or target_p.id

        # 选定的模型列表
        if req.selected_model_names:
            models_to_import = [
                m for m in target_p.models
                if m.id in req.selected_model_names or m.name in req.selected_model_names
            ]
        else:
            models_to_import = target_p.models

        new_detail_items = [
            ModelDetailItem(
                model_name=m.id,
                temperature=0.7,
                max_tokens=m.max_output_tokens,
                max_output_tokens=m.max_output_tokens,
                reasoning_effort="medium" if m.reasoning else None,
            )
            for m in models_to_import
        ]

        # 检查是否已存在同名服务商
        existing_p = next((p for p in current_cfg.providers if p.name.lower() == p_name.lower()), None)
        if existing_p:
            existing_model_names = {m.model_name.lower() for m in existing_p.models}
            for nm in new_detail_items:
                if nm.model_name.lower() not in existing_model_names:
                    existing_p.models.append(nm)
            if req.api_base:
                existing_p.api_base = req.api_base
            if req.api_type:
                existing_p.api_type = req.api_type
            if req.api_key and req.api_key != "YOUR_API_KEY":
                existing_p.api_key = req.api_key
        else:
            new_p = ProviderItem(
                name=p_name,
                api_key=req.api_key,
                api_base=req.api_base or target_p.api_base,
                api_type=req.api_type or target_p.api_type,
                temperature=None,
                max_output_tokens=None,
                timeout=180,
                models=new_detail_items,
            )
            current_cfg.providers.append(new_p)

        # 持久化并同步 models.json 与 plugins2config.yaml
        cls.save_ai_config(current_cfg)
        return True

