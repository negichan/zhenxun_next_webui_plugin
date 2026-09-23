"""AI / LLM 配置与模型管理模型"""
from typing import Any
from pydantic import BaseModel, Field


class ModelDetailItem(BaseModel):
    """单个模型详细配置"""

    model_name: str = Field(..., description="模型标识名称")
    temperature: float | None = Field(default=None, description="模型默认温度")
    max_tokens: int | None = Field(default=None, description="最大输出 Token")
    max_output_tokens: int | None = Field(default=None, description="最大输出 Token (别名)")
    reasoning_effort: str | None = Field(default=None, description="推理深度级别")


class ProviderItem(BaseModel):
    """模型服务提供商配置"""

    name: str = Field(..., description="提供商唯一标识")
    api_key: str | list[str] = Field(..., description="API 密钥 (支持单 Key 或多 Key 列表)")
    api_base: str | None = Field(default=None, description="API 基础 URL")
    api_type: str = Field(default="openai", description="API 协议类型")
    temperature: float | None = Field(default=None, description="全局默认温度")
    max_output_tokens: int | None = Field(default=None, description="默认最大输出 Token")
    timeout: int = Field(default=180, description="请求超时时间 (秒)")
    models: list[ModelDetailItem] = Field(default_factory=list, description="模型列表")
    enabled: bool = Field(default=True, description="是否启用该渠道")
    priority: int = Field(default=1, description="渠道调度优先级")
    weight: int = Field(default=10, description="渠道负载均衡权重")


class DefaultModelsItem(BaseModel):
    """按任务分类的默认模型配置"""

    chat: str | None = Field(default="Gemini/gemini-3.5-flash", description="默认对话模型")
    embedding: str | None = Field(default="Gemini/gemini-embedding-2", description="默认向量嵌入模型")
    tts: str | None = Field(default="Gemini/gemini-3.1-flash-tts-preview", description="默认语音合成模型")
    image: str | None = Field(default="Gemini/gemini-2.5-flash-image", description="默认图像生成模型")
    rerank: str | None = Field(default="siliconflow/BAAI/bge-reranker-v2-m3", description="默认重排模型")


class LLMSummaryItem(BaseModel):
    """大模型自然语言对话压缩总结配置"""

    enable: bool = Field(default=True, description="是否开启大模型总结压缩")
    trigger_threshold: float = Field(default=0.8, description="触发压缩 Token 比例或绝对值")
    max_history_turns: int = Field(default=0, description="触发最大历史轮数 (0 为不限制)")
    summarization_model: str | None = Field(default="DeepSeek/deepseek-v4-flash", description="总结使用的大模型")
    summarization_prompt: str = Field(
        default="请以客观、精炼的语言概括以下对话内容。重点保留核心话题、重要决定、用户个性偏好与情感基调。",
        description="总结系统提示词",
    )
    keep_recent_turns: int = Field(default=3, description="强制原样保留的最近轮数")


class ToolPruningItem(BaseModel):
    """工具结果自动修剪配置"""

    enable: bool = Field(default=False, description="是否开启长工具输出修剪")
    trigger_threshold: float = Field(default=0.6, description="触发修剪的 Token 阈值")
    max_history_turns: int = Field(default=15, description="触发修剪的最大工具轮数")
    keep_recent_turns: int = Field(default=3, description="强制原样保留的最近工具轮数")


class ContextSettingsItem(BaseModel):
    """智能上下文管理配置"""

    llm_summary: LLMSummaryItem = Field(default_factory=LLMSummaryItem)
    vision_window_size: int = Field(default=3, description="多模态消息滑动窗口大小")
    tool_pruning: ToolPruningItem = Field(default_factory=ToolPruningItem)


class AgentSettingsItem(BaseModel):
    """Agent 推理引擎配置"""

    max_cycles: int = Field(default=10, description="工具调用单次最大循环次数")
    global_max_cycles: int = Field(default=30, description="整个生命周期跨 Agent 绝对循环上限")
    enable_parallel_calls: bool = Field(default=True, description="允许并行工具调用")
    reflexion_retries: int = Field(default=1, description="反思重试次数")
    enable_fallback_summary: bool = Field(default=True, description="达上限时大模型兜底总结")
    enable_hitl: bool = Field(default=False, description="是否允许智能体向人类求助")
    mcp_cleanup_timeout: int = Field(default=900, description="MCP 服务闲置清理超时时间 (秒)")


class ClientSettingsItem(BaseModel):
    """客户端底层网络连接设置"""

    timeout: int = Field(default=300, description="请求超时时间 (秒)")
    max_retries: int = Field(default=3, description="最大重试次数")
    retry_delay: int = Field(default=2, description="重试基础延迟 (秒)")
    structured_retries: int = Field(default=2, description="结构化校验重试次数")


class DebugLogItem(BaseModel):
    """调试日志开关选项"""

    show_tools: bool = Field(default=True, description="显示工具定义 JSON Schema")
    show_schema: bool = Field(default=True, description="显示结构化输出 Schema")
    show_safety: bool = Field(default=True, description="显示安全设置")


class SandboxSettingsItem(BaseModel):
    """沙箱环境配置"""

    enable_sandbox: bool = Field(default=False, description="全局沙箱功能硬开关")
    sandbox_type: str = Field(default="docker", description="沙箱底层驱动类型")
    docker_image: str = Field(default="zhenxun-sandbox:latest", description="沙箱镜像名")
    cleanup_timeout: int = Field(default=1800, description="沙箱空闲清理超时 (秒)")
    enable_vfs_helper: bool = Field(default=True, description="开启 VFS 路径防逃逸探针")


class GeminiProviderItem(BaseModel):
    """Gemini 专属高级配置"""

    safety_threshold: str = Field(default="BLOCK_NONE", description="安全过滤阈值")
    allow_mixed_tools: bool = Field(default=False, description="允许混合使用本地与云端工具")


class ProviderSettingsGroupItem(BaseModel):
    """厂商高级专属设置组"""

    gemini: GeminiProviderItem = Field(default_factory=GeminiProviderItem)


class AiConfigData(BaseModel):
    """AI 全局持久化完整配置"""

    providers: list[ProviderItem] = Field(default_factory=list, description="提供商列表")
    default_models: DefaultModelsItem = Field(default_factory=DefaultModelsItem, description="任务默认模型")
    model_groups: dict[str, list[str]] = Field(default_factory=dict, description="虚拟模型路由组")
    context_settings: ContextSettingsItem = Field(default_factory=ContextSettingsItem, description="上下文管理配置")
    agent_settings: AgentSettingsItem = Field(default_factory=AgentSettingsItem, description="Agent 引擎配置")
    client_settings: ClientSettingsItem = Field(default_factory=ClientSettingsItem, description="客户端网络设置")
    debug_log: DebugLogItem = Field(default_factory=DebugLogItem, description="调试日志开关")
    sandbox: SandboxSettingsItem = Field(default_factory=SandboxSettingsItem, description="沙箱配置")
    provider_settings: ProviderSettingsGroupItem = Field(
        default_factory=ProviderSettingsGroupItem, description="厂商专属高级配置"
    )


class ModelTestRequest(BaseModel):
    """模型连通性测试请求"""

    model: str = Field(..., description="待测试的模型名称 (如 Provider/ModelName)")


class ModelTestResponse(BaseModel):
    """模型测试结果响应"""

    success: bool = Field(..., description="是否连通成功")
    message: str = Field(..., description="详细测试信息或报错说明")
    latency_ms: float | None = Field(default=None, description="响应耗时 (毫秒)")


class AvailableModelItem(BaseModel):
    """可用模型项"""

    id: str = Field(..., description="Provider/Model 全标识")
    provider: str = Field(..., description="所属厂商")
    model_name: str = Field(..., description="模型名称")
    is_available: bool = Field(default=True, description="是否配置且可用")


class ModelsDevModelItem(BaseModel):
    """models.dev 在线模型信息"""

    id: str = Field(..., description="模型 ID (如 deepseek-chat)")
    name: str = Field(..., description="模型名称")
    description: str | None = Field(default=None, description="模型描述")
    context_limit: int | None = Field(default=None, description="上下文总 Token 限制")
    max_output_tokens: int | None = Field(default=None, description="最大输出 Token")
    reasoning: bool = Field(default=False, description="是否具备思考/推理模式")
    tool_call: bool = Field(default=True, description="是否支持工具/函数调用")
    temperature: bool = Field(default=True, description="是否支持温度参数调节")
    release_date: str | None = Field(default=None, description="发布日期")


class ModelsDevProviderItem(BaseModel):
    """models.dev 在线服务提供商信息"""

    id: str = Field(..., description="提供商 ID")
    name: str = Field(..., description="提供商展示名")
    api_base: str | None = Field(default=None, description="基础 API 地址")
    api_type: str = Field(default="openai", description="真寻映射协议类型")
    npm: str | None = Field(default=None, description="对应 npm 适配包")
    doc: str | None = Field(default=None, description="文档/价格链接")
    env: list[str] = Field(default_factory=list, description="推荐的环境变量名")
    models_count: int = Field(default=0, description="包含的模型总数")
    models: list[ModelsDevModelItem] = Field(default_factory=list, description="模型列表")


class ModelsDevCatalogResponse(BaseModel):
    """models.dev 目录整体响应"""

    total_providers: int = Field(default=0, description="提供商总数")
    total_models: int = Field(default=0, description="模型总数")
    cached_at: str | None = Field(default=None, description="缓存时间")
    providers: list[ModelsDevProviderItem] = Field(default_factory=list, description="提供商列表")


class ImportModelsDevRequest(BaseModel):
    """从 models.dev 导入服务商请求"""

    provider_id: str = Field(..., description="models.dev 中的提供商 ID")
    provider_name: str | None = Field(default=None, description="自定义提供商名称 (留空使用默认)")
    api_key: str = Field(default="YOUR_API_KEY", description="API 密钥")
    api_base: str | None = Field(default=None, description="覆盖的 API Base")
    api_type: str | None = Field(default=None, description="覆盖的 API Type")
    selected_model_names: list[str] = Field(default_factory=list, description="选中的模型名列表，若为空则导入全部")


class TelemetryItem(BaseModel):
    """大模型调用抓包遥测记录项"""

    id: str = Field(..., description="调用唯一标识")
    timestamp: float = Field(..., description="请求发起时间戳")
    api_type: str = Field(..., description="请求使用的协议类型")
    provider_name: str = Field(..., description="厂商名称")
    model_name: str = Field(..., description="模型名称")
    endpoint: str | None = Field(default=None, description="实际调用的目标 URL/端点")
    prompt_preview: str | None = Field(default=None, description="提示词摘要")
    response_preview: str | None = Field(default=None, description="响应文本摘要")
    latency_ms: float | None = Field(default=None, description="请求耗时 (毫秒)")
    input_tokens: int | None = Field(default=None, description="输入消耗 Token")
    output_tokens: int | None = Field(default=None, description="输出消耗 Token")
    status: str = Field(default="success", description="调用状态: success / error / pending")
    error_message: str | None = Field(default=None, description="错误信息 (若失败)")


class ProtocolHijackStatusResponse(BaseModel):
    """实验性协议劫持全局状态与协议清单响应"""

    enabled: bool = Field(default=False, description="协议劫持总开关是否开启")
    supported_protocols: list[str] = Field(
        default_factory=lambda: ["chat", "response", "claude"],
        description="当前支持适配与劫持的核心协议",
    )
    intercepted_count: int = Field(default=0, description="已拦截并记录的总调用次数")


class UpdateProtocolHijackRequest(BaseModel):
    """修改实验性协议劫持总开关请求"""

    enabled: bool = Field(..., description="是否开启协议适配与劫持")

