"""
实验性协议劫持与扩展装载器
将 Claude 适配器及 chat、response 别名注册至真寻 LLMAdapterFactory，并挂载透明劫持代理。
"""

from __future__ import annotations

from zhenxun.services.ai.llm.adapters.factory import LLMAdapterFactory
from zhenxun.services.log import logger

from .claude import ClaudeAdapter
from .hijack import HijackedAdapterProxy, ProtocolHijackManager

_IS_INSTALLED = False


def get_hijack_manager() -> ProtocolHijackManager:
    """获取单例协议劫持管理器"""
    return ProtocolHijackManager()


def install_protocol_hijack() -> None:
    """
    安装并激活实验性协议扩展与劫持代理。
    幂等执行，仅在首次调用时执行底层工厂注册。
    """
    global _IS_INSTALLED
    if _IS_INSTALLED:
        return

    try:
        # 1. 确保真寻原生 11 种默认适配器已预加载
        LLMAdapterFactory.initialize()

        hijack_mgr = get_hijack_manager()

        # 2. 注册 Claude 原生适配器
        claude_adapter = ClaudeAdapter()
        LLMAdapterFactory.register_adapter(claude_adapter)

        # 3. 注入友好别名映射: chat -> openai, response -> openai_responses, anthropic -> claude
        alias_maps = {
            "chat": "openai",
            "response": "openai_responses",
            "responses": "openai_responses",
            "claude": "claude",
            "anthropic": "claude",
        }
        for alias, target_key in alias_maps.items():
            LLMAdapterFactory._api_type_mapping[alias] = target_key

        # 4. 对三大核心协议挂载透明劫持代理 (HijackedAdapterProxy)
        target_keys = ["openai", "openai_responses", "claude"]
        for key in target_keys:
            orig_adapter = LLMAdapterFactory._adapters.get(key)
            if orig_adapter and not isinstance(orig_adapter, HijackedAdapterProxy):
                LLMAdapterFactory._adapters[key] = HijackedAdapterProxy(
                    target=orig_adapter,
                    manager=hijack_mgr,
                )

        _IS_INSTALLED = True
        logger.info(
            f"已成功加载实验性协议适配与劫持系统 (核心支持: chat, response, claude | 当前开关: {hijack_mgr.is_enabled()})",
            "WebUI-ProtocolHijack",
        )

    except Exception as e:
        logger.error(
            f"安装实验性协议适配与劫持系统失败: {e}",
            "WebUI-ProtocolHijack",
            e=e,
        )
