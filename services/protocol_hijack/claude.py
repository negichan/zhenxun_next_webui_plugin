"""
Anthropic Claude Messages API 适配器实现。
原生支持 /v1/messages 协议，独立处理顶层 system 提示词、必填 max_tokens 兜底、交替消息角色规范与工具调用映射。
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from zhenxun.services.ai.core.exceptions import (
    AuthenticationException,
    InvalidRequestException,
    RateLimitException,
    ResponseParseException,
    UpstreamServerException,
)
from zhenxun.services.ai.core.messages import (
    AssistantMessage,
    ChatRequest,
    ImagePart,
    LLMMessage,
    SystemMessage,
    TextPart,
    ToolCallPart,
    ToolMessage,
    UserMessage,
)
from zhenxun.services.ai.core.models import ModelIdentity
from zhenxun.services.ai.llm.adapters.base import (
    BaseAdapter,
    RequestData,
    ResponseData,
)
from zhenxun.services.ai.llm.adapters.handlers.base import BaseTextHandler
from zhenxun.services.ai.utils.logger import log_llm as logger


class ClaudeTextHandler(BaseTextHandler):
    """Anthropic Claude /v1/messages 协议文本与多模态处理器"""

    def __init__(self, api_type: str = "claude"):
        self.api_type = api_type

    async def prepare_text_request(
        self,
        adapter: BaseAdapter,
        identity: ModelIdentity,
        api_key: str,
        request: ChatRequest,
    ) -> RequestData:
        endpoint = "/v1/messages"
        url = adapter.get_api_url(identity, endpoint)
        headers = adapter.get_base_headers(api_key)

        # 1. 拆分 system 消息与普通上下文
        system_prompts: list[str] = []
        conversation_messages: list[dict[str, Any]] = []

        for msg in request.messages:
            if isinstance(msg, SystemMessage):
                for p in msg.content:
                    if isinstance(p, TextPart) and p.text:
                        system_prompts.append(p.text)
                continue

            # 转换单条非 system 消息
            role = "user" if isinstance(msg, (UserMessage, ToolMessage)) else "assistant"
            content_blocks: list[dict[str, Any]] = []

            if isinstance(msg, ToolMessage):
                # Anthropic 要求工具返回以 user 角色的 tool_result 块传入
                content_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": getattr(msg, "tool_call_id", "") or "unknown",
                        "content": "".join(
                            p.text for p in msg.content if isinstance(p, TextPart)
                        ),
                    }
                )
            else:
                for part in msg.content:
                    if isinstance(part, TextPart) and part.text:
                        content_blocks.append({"type": "text", "text": part.text})
                    elif isinstance(part, ImagePart):
                        # 处理图片 base64
                        img_block = self._format_image_block(part)
                        if img_block:
                            content_blocks.append(img_block)
                    elif isinstance(part, ToolCallPart):
                        # Assistant 发起的工具调用
                        args_dict = {}
                        if isinstance(part.arguments, dict):
                            args_dict = part.arguments
                        elif isinstance(part.arguments, str) and part.arguments.strip():
                            try:
                                args_dict = json.loads(part.arguments)
                            except Exception:
                                args_dict = {"raw": part.arguments}

                        content_blocks.append(
                            {
                                "type": "tool_use",
                                "id": part.call_id or f"call_{len(content_blocks)}",
                                "name": part.function_name,
                                "input": args_dict,
                            }
                        )

            if not content_blocks:
                continue

            # Claude 强制要求同一角色的消息交替出现；若连续两个相同 role，则合并到前一个
            if conversation_messages and conversation_messages[-1]["role"] == role:
                conversation_messages[-1]["content"].extend(content_blocks)
            else:
                conversation_messages.append({"role": role, "content": content_blocks})

        # 若首条不是 user，或者对话为空，自动兜底一条 user 消息
        if not conversation_messages:
            conversation_messages = [{"role": "user", "content": [{"type": "text", "text": "Hello"}]}]
        elif conversation_messages[0]["role"] != "user":
            conversation_messages.insert(0, {"role": "user", "content": [{"type": "text", "text": "Continue"}]})

        # 2. 组装 Body
        body: dict[str, Any] = {
            "model": identity.model_name,
            "messages": conversation_messages,
        }

        if system_prompts:
            body["system"] = "\n\n".join(system_prompts)

        # 3. max_tokens (Claude 必填项，若无则默认 4096)
        config = request.config or identity.generation_config
        max_tokens = None
        if config and hasattr(config, "common") and config.common and config.common.max_tokens:
            max_tokens = config.common.max_tokens
        elif config and hasattr(config, "max_output_tokens") and config.max_output_tokens:
            max_tokens = config.max_output_tokens
        body["max_tokens"] = max_tokens or 4096

        # 4. 可选生成参数 (temperature / top_p / top_k)
        if config and hasattr(config, "common") and config.common:
            if config.common.temperature is not None:
                body["temperature"] = config.common.temperature
            if config.common.top_p is not None:
                body["top_p"] = config.common.top_p
            if config.common.top_k is not None:
                body["top_k"] = config.common.top_k
            if config.common.stop_sequences:
                body["stop_sequences"] = config.common.stop_sequences

        # 5. 工具调用 (Tools)
        if request.tools:
            tool_defs, _, _ = await self._resolve_and_split_tools(request.tools)
            if tool_defs:
                body["tools"] = [
                    {
                        "name": t.name,
                        "description": t.description or "",
                        "input_schema": t.parameters or {"type": "object", "properties": {}},
                    }
                    for t in tool_defs
                ]

        return RequestData(url=url, headers=headers, body=body)

    def _format_image_block(self, part: ImagePart) -> dict[str, Any] | None:
        """转换为 Anthropic 图片 Base64 source 格式"""
        raw_bytes = None
        media_type = "image/jpeg"

        if part.raw:
            raw_bytes = part.raw
        elif part.path:
            p = Path(part.path)
            if p.exists():
                raw_bytes = p.read_bytes()
                suffix = p.suffix.lower()
                if suffix == ".png":
                    media_type = "image/png"
                elif suffix == ".webp":
                    media_type = "image/webp"
                elif suffix == ".gif":
                    media_type = "image/gif"

        if raw_bytes:
            b64_data = base64.b64encode(raw_bytes).decode("utf-8")
            return {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": b64_data,
                },
            }
        return None

    def parse_text_response(
        self,
        adapter: BaseAdapter,
        identity: ModelIdentity,
        response_json: dict[str, Any],
        is_advanced: bool = False,
    ) -> ResponseData:
        """解析 Claude 响应报文"""
        # 1. 错误拦截
        if "error" in response_json:
            error_obj = response_json["error"]
            msg = error_obj.get("message", str(error_obj)) if isinstance(error_obj, dict) else str(error_obj)
            err_type = error_obj.get("type", "unknown") if isinstance(error_obj, dict) else "unknown"

            if err_type in ("authentication_error", "permission_error"):
                raise AuthenticationException(f"Claude 鉴权失败: {msg}", details=response_json)
            elif err_type == "rate_limit_error":
                raise RateLimitException(f"Claude 速率限制: {msg}", details=response_json)
            elif err_type == "invalid_request_error":
                raise InvalidRequestException(f"Claude 无效请求: {msg}", details=response_json)
            else:
                raise UpstreamServerException(f"Claude 上游错误 ({err_type}): {msg}", details=response_json)

        # 2. 提取内容块
        content_parts = []
        raw_content = response_json.get("content", [])
        if isinstance(raw_content, list):
            for block in raw_content:
                if not isinstance(block, dict):
                    continue
                b_type = block.get("type")
                if b_type == "text":
                    content_parts.append(TextPart(text=block.get("text", "")))
                elif b_type == "tool_use":
                    tool_input = block.get("input", {})
                    args_str = (
                        json.dumps(tool_input, ensure_ascii=False)
                        if isinstance(tool_input, (dict, list))
                        else str(tool_input)
                    )
                    content_parts.append(
                        ToolCallPart(
                            call_id=block.get("id", ""),
                            function_name=block.get("name", ""),
                            arguments=args_str,
                        )
                    )

        # 3. 提取使用量
        usage = response_json.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        usage_info = {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }

        return ResponseData(
            content_parts=content_parts,
            usage_info=usage_info,
            raw_response=response_json,
        )


class ClaudeAdapter(BaseAdapter):
    """Anthropic Claude 原生适配器"""

    def __init__(self):
        super().__init__()
        self.text_handler = ClaudeTextHandler(api_type=self.api_type)

    @property
    def api_type(self) -> str:
        return "claude"

    @property
    def supported_api_types(self) -> list[str]:
        return ["claude", "anthropic"]

    @property
    def log_sanitization_context(self) -> str:
        return "anthropic_request"

    def get_chat_endpoint(self, identity: ModelIdentity) -> str:
        return "/v1/messages"

    def get_base_headers(self, api_key: str) -> dict[str, str]:
        from zhenxun.utils.user_agent import get_user_agent

        headers = get_user_agent()
        headers.update(
            {
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            }
        )
        return headers
