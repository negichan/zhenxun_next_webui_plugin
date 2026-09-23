"""系统相关模型"""
from datetime import datetime

from pydantic import BaseModel, Field


class SystemStatus(BaseModel):
    """系统状态"""
    cpu: float = Field(..., description="CPU 使用率百分比")
    memory: float = Field(..., description="内存使用率百分比")
    disk: float = Field(..., description="磁盘使用率百分比")
    check_time: datetime = Field(..., description="检查时间")


class SystemHealth(BaseModel):
    """系统健康状态"""
    status: str = Field(..., description="健康状态：healthy, warning, error")
    cpu_status: str = Field(..., description="CPU 状态：normal, high, critical")
    memory_status: str = Field(..., description="内存状态：normal, high, critical")
    disk_status: str = Field(..., description="磁盘状态：normal, high, critical")
    recommendations: list[str] = Field(default_factory=list, description="优化建议")


class SystemFolderSize(BaseModel):
    """文件夹大小信息"""
    name: str = Field(..., description="文件夹/文件名")
    size: float = Field(..., description="大小（MB）")
    full_path: str | None = Field(None, description="完整路径")
    is_dir: bool = Field(..., description="是否为文件夹")


class BotStatus(BaseModel):
    """Bot 状态"""
    self_id: str | None = Field(None, description="Bot ID")
    nickname: str | None = Field(None, description="Bot 昵称")
    ava_url: str | None = Field(None, description="Bot 头像 URL")
    is_running: bool = Field(..., description="是否运行中")
    uptime: int = Field(..., description="运行时长（秒）")
    uptime_formatted: str = Field(..., description="格式化后的运行时长")
    group_count: int = Field(..., description="群组数量")
    friend_count: int = Field(..., description="好友数量")
    message_count: int = Field(..., description="消息数量")
    start_time: datetime = Field(..., description="启动时间")


class BotStatusListData(BaseModel):
    """Bot 状态列表"""
    current: BotStatus | None = Field(None, description="当前选中的 Bot 状态")
    bots: list[BotStatus] = Field(default_factory=list, description="Bot 状态列表")
    total: int = Field(..., description="Bot 总数")


class BotInfo(BaseModel):
    self_id: str
    """SELF ID"""
    nickname: str
    """昵称"""
    ava_url: str
    """头像url"""
    platform: str
    """平台"""
    friend_count: int = 0
    """好友数量"""
    group_count: int = 0
    """群聊数量"""
    received_messages: int = 0
    """今日消息接收"""
    day_call: int = 0
    """今日调用插件次数"""
    connect_date: str | None = None
    """连接日期"""
    messages_total: int = 0
    """消息总数"""
    total_call: int = 0
    """插件调用总数"""


class Friend(BaseModel):
    """好友信息"""
    user_id: str = Field(..., description="用户 ID")
    nickname: str = Field(..., description="昵称")
    ava_url: str = Field(..., description="头像 URL")


class Group(BaseModel):
    """群组信息"""
    group_id: str = Field(..., description="群组 ID")
    group_name: str = Field(..., description="群组名称")
    ava_url: str = Field(..., description="群头像 URL")


class ConnectionLogInfo(BaseModel):
    """Bot 连接日志"""

    id: int = Field(..., description="记录 ID")
    bot_id: str = Field(..., description="Bot ID")
    platform: str | None = Field(None, description="平台")
    type: int = Field(..., description="1: 连接, 0: 断开")
    connect_time: datetime = Field(..., description="连接/断开时间")
