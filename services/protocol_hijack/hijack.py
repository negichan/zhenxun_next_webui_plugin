"""
大模型协议劫持代理与管理引擎 (Protocol Hijack & Telemetry Engine)
提供请求改写、生命周期钩子、流量抓包与调用遥测。
"""

from __future__ import annotations

from collections import deque
import json
from pathlib import Path
import time
from typing import Any, Callable
import uuid

import httpx

from zhenxun.configs.path_config import DATA_PATH
from zhenxun.services.ai.core.models import ModelIdentity
from zhenxun.services.ai.llm.adapters.base import (
    BaseAdapter,
    RequestData,
    ResponseData,
)
from zhenxun.services.ai.utils.logger import log_llm as logger

from ...models.ai import TelemetryItem

HIJACK_CONFIG_PATH = DATA_PATH / "ai" / "experimental_hijack.json"


class ProtocolHijackManager:
    """协议劫持与遥测管理器 (单例)"""

    _instance: ProtocolHijackManager | None = None

    def __new__(cls) -> ProtocolHijackManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_manager()
        return cls._instance

    def _init_manager(self) -> None:
        self._enabled: bool = False
        self._intercepted_count: int = 0
        self._telemetry_history: deque[TelemetryItem] = deque(maxlen=100)
        self._pending_calls: dict[str, dict[str, Any]] = {}
        self._request_hooks: list[Callable] = []
        self._response_hooks: list[Callable] = []
        self._load_config()

    def _load_config(self) -> None:
        """从持久化文件加载开关状态"""
        try:
            if HIJACK_CONFIG_PATH.exists():
                data = json.loads(HIJACK_CONFIG_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._enabled = bool(data.get("enabled", False))
                    self._intercepted_count = int(data.get("intercepted_count", 0))
                    logger.info(
                        f"已加载实验性协议劫持配置: enabled={self._enabled}",
                        "ProtocolHijack",
                    )
        except Exception as e:
            logger.warning(f"读取协议劫持配置失败: {e}", "ProtocolHijack")

    def _save_config(self) -> None:
        """保存开关状态"""
        try:
            HIJACK_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "enabled": self._enabled,
                "intercepted_count": self._intercepted_count,
            }
            HIJACK_CONFIG_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"持久化协议劫持配置失败: {e}", "ProtocolHijack")

    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._save_config()
        logger.info(f"协议劫持总开关变更为: {self._enabled}", "ProtocolHijack")

    @property
    def intercepted_count(self) -> int:
        return self._intercepted_count

    def get_telemetry(self, limit: int = 50) -> list[TelemetryItem]:
        """获取近期拦截到的调用遥测记录 (最新的在前)"""
        items = list(self._telemetry_history)
        items.reverse()
        return items[:limit]

    def clear_telemetry(self) -> None:
        self._telemetry_history.clear()

    def record_telemetry(self, item: TelemetryItem) -> None:
        self._telemetry_history.append(item)
        self._intercepted_count += 1
        # 少量定期更新计数
        if self._intercepted_count % 10 == 0:
            self._save_config()

    def register_request_hook(self, hook: Callable) -> None:
        self._request_hooks.append(hook)

    def register_response_hook(self, hook: Callable) -> None:
        self._response_hooks.append(hook)

    async def dispatch_prepare_payload(
        self,
        adapter: BaseAdapter,
        identity: ModelIdentity,
        api_key: str,
        request: Any,
    ) -> RequestData:
        """分发请求构建流程并记录前置遥测上下文"""
        call_id = uuid.uuid4().hex[:8]
        start_time = time.monotonic()

        # 1. 提取 Prompt 预览
        prompt_preview = self._extract_prompt_preview(request)

        # 2. 调用底层适配器生成标准 RequestData
        req_data: RequestData = await adapter.prepare_payload(identity, api_key, request)

        # 3. 执行用户注册的请求拦截钩子
        for hook in self._request_hooks:
            try:
                modified = hook(adapter.api_type, identity, req_data, request)
                if modified is not None and isinstance(modified, RequestData):
                    req_data = modified
            except Exception as e:
                logger.warning(f"RequestHook 执行异常: {e}", "ProtocolHijack")

        # 4. 存入待确认上下文，等待响应匹配
        self._pending_calls[call_id] = {
            "call_id": call_id,
            "timestamp": time.time(),
            "start_monotonic": start_time,
            "api_type": adapter.api_type,
            "provider_name": identity.provider_name,
            "model_name": identity.model_name,
            "endpoint": req_data.url,
            "prompt_preview": prompt_preview,
        }

        # 将 call_id 注入到 request 的 extra 或私有属性中以便下行追踪
        if hasattr(request, "extra") and isinstance(request.extra, dict):
            request.extra["_hijack_call_id"] = call_id

        logger.debug(
            f"⚡ [Hijack] 捕获请求 [{call_id}] {adapter.api_type} -> {identity.model_name}",
            "ProtocolHijack",
        )
        return req_data

    async def dispatch_parse_payload(
        self,
        adapter: BaseAdapter,
        identity: ModelIdentity,
        request: Any,
        raw_response: httpx.Response,
    ) -> Any:
        """分发响应解析流程并完成遥测归档"""
        call_id = None
        if hasattr(request, "extra") and isinstance(request.extra, dict):
            call_id = request.extra.get("_hijack_call_id")

        call_ctx = self._pending_calls.pop(call_id, None) if call_id else None
        start_mono = call_ctx.get("start_monotonic") if call_ctx else None
        latency_ms = round((time.monotonic() - start_mono) * 1000, 2) if start_mono else None

        try:
            # 1. 调用底层适配器解析响应
            res = await adapter.parse_payload(identity, request, raw_response)

            # 2. 执行响应拦截钩子
            for hook in self._response_hooks:
                try:
                    res = hook(adapter.api_type, identity, request, res) or res
                except Exception as e:
                    logger.warning(f"ResponseHook 执行异常: {e}", "ProtocolHijack")

            # 3. 提取响应内容摘要与 Token 使用量
            resp_preview = self._extract_response_preview(res)
            input_tokens, output_tokens = self._extract_token_usage(res)

            # 4. 记录遥测
            item = TelemetryItem(
                id=call_id or uuid.uuid4().hex[:8],
                timestamp=call_ctx.get("timestamp", time.time()) if call_ctx else time.time(),
                api_type=adapter.api_type,
                provider_name=identity.provider_name,
                model_name=identity.model_name,
                endpoint=call_ctx.get("endpoint") if call_ctx else None,
                prompt_preview=call_ctx.get("prompt_preview") if call_ctx else None,
                response_preview=resp_preview,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                status="success",
            )
            self.record_telemetry(item)
            logger.debug(
                f"✅ [Hijack] 完成调用 [{item.id}] 耗时 {latency_ms}ms 消耗 Tokens: {input_tokens}+{output_tokens}",
                "ProtocolHijack",
            )
            return res

        except Exception as exc:
            # 捕获异常遥测记录
            err_msg = str(exc)
            item = TelemetryItem(
                id=call_id or uuid.uuid4().hex[:8],
                timestamp=call_ctx.get("timestamp", time.time()) if call_ctx else time.time(),
                api_type=adapter.api_type,
                provider_name=identity.provider_name,
                model_name=identity.model_name,
                endpoint=call_ctx.get("endpoint") if call_ctx else None,
                prompt_preview=call_ctx.get("prompt_preview") if call_ctx else None,
                response_preview=None,
                latency_ms=latency_ms,
                input_tokens=None,
                output_tokens=None,
                status="error",
                error_message=err_msg[:300],
            )
            self.record_telemetry(item)
            raise

    def _extract_prompt_preview(self, request: Any) -> str:
        """安全提取请求 Prompt 摘要预览"""
        try:
            if hasattr(request, "messages") and request.messages:
                for msg in reversed(request.messages):
                    content = getattr(msg, "content", None)
                    if isinstance(content, list):
                        for p in content:
                            text = getattr(p, "text", None)
                            if text:
                                return text[:150]
                    elif isinstance(content, str) and content:
                        return content[:150]
            if hasattr(request, "prompt") and request.prompt:
                return str(request.prompt)[:150]
        except Exception:
            pass
        return "(无文本内容)"

    def _extract_response_preview(self, response: Any) -> str:
        """安全提取响应预览文本"""
        try:
            if hasattr(response, "text") and response.text:
                return response.text[:150]
            if hasattr(response, "content_parts"):
                for p in response.content_parts:
                    if hasattr(p, "text") and p.text:
                        return p.text[:150]
        except Exception:
            pass
        return "(非文本响应)"

    def _extract_token_usage(self, response: Any) -> tuple[int | None, int | None]:
        """安全提取响应 Token 使用量"""
        try:
            usage = getattr(response, "usage_info", None)
            if isinstance(usage, dict):
                in_tok = usage.get("prompt_tokens") or usage.get("input_tokens")
                out_tok = usage.get("completion_tokens") or usage.get("output_tokens")
                return in_tok, out_tok
            elif usage and hasattr(usage, "prompt_tokens"):
                return usage.prompt_tokens, usage.completion_tokens
        except Exception:
            pass
        return None, None


class HijackedAdapterProxy(BaseAdapter):
    """
    协议适配器透明劫持代理。
    全面代理 BaseAdapter 属性与特有方法，在 prepare_payload 与 parse_payload 阶段进行挂钩拦截。
    """

    def __init__(self, target: BaseAdapter, manager: ProtocolHijackManager):
        self._target = target
        self._manager = manager

    @property
    def api_type(self) -> str:
        return self._target.api_type

    @property
    def supported_api_types(self) -> list[str]:
        return self._target.supported_api_types

    @property
    def text_handler(self) -> Any:
        return getattr(self._target, "text_handler", None)

    @text_handler.setter
    def text_handler(self, val: Any) -> None:
        setattr(self._target, "text_handler", val)

    @property
    def log_sanitization_context(self) -> str:
        return getattr(self._target, "log_sanitization_context", "default")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target, name)

    async def prepare_payload(
        self, identity: ModelIdentity, api_key: str, request: Any
    ) -> RequestData:
        if not self._manager.is_enabled():
            return await self._target.prepare_payload(identity, api_key, request)

        return await self._manager.dispatch_prepare_payload(
            self._target, identity, api_key, request
        )

    async def parse_payload(
        self, identity: ModelIdentity, request: Any, raw_response: httpx.Response
    ) -> Any:
        if not self._manager.is_enabled():
            return await self._target.parse_payload(identity, request, raw_response)

        return await self._manager.dispatch_parse_payload(
            self._target, identity, request, raw_response
        )
