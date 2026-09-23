"""仪表盘相关模型"""
from pydantic import BaseModel, Field


class DashboardOverview(BaseModel):
    """仪表盘概览"""
    bot_status: str = Field(..., description="Bot 状态：online, offline")
    uptime: int = Field(..., description="运行时长（秒）")
    uptime_formatted: str = Field(..., description="格式化后的运行时长")
    group_count: int = Field(..., description="群组数量")
    friend_count: int = Field(..., description="好友数量")
    message_count_today: int = Field(..., description="今日消息数量")
    plugin_count: int = Field(..., description="插件总数")
    enabled_plugin_count: int = Field(..., description="启用的插件数量")


class StatItem(BaseModel):
    """统计项"""
    label: str = Field(..., description="标签")
    value: int | float = Field(..., description="值")
    trend: str | None = Field(None, description="趋势：up, down, stable")
    change: float | None = Field(None, description="变化量")


class DashboardStats(BaseModel):
    """仪表盘统计"""
    message_stats: StatItem = Field(..., description="消息统计")
    user_stats: StatItem = Field(..., description="用户统计")
    group_stats: StatItem = Field(..., description="群组统计")
    error_stats: StatItem = Field(..., description="错误统计")


class QuickAction(BaseModel):
    """快捷操作"""
    name: str = Field(..., description="操作名称")
    description: str = Field(..., description="操作描述")
    icon: str = Field(..., description="图标")
    action_type: str = Field(..., description="操作类型")


class DashboardResult(BaseModel):
    """仪表盘结果"""
    overview: DashboardOverview = Field(..., description="概览")
    stats: DashboardStats = Field(..., description="统计")
    quick_actions: list[QuickAction] = Field(default_factory=list, description="快捷操作")
    system_health: str = Field(..., description="系统健康状态")


class GroupStatistics(BaseModel):
    """群组统计"""
    group_id: str = Field(..., description="群组 ID")
    group_name: str = Field(..., description="群组名称")
    message_count: int = Field(..., description="消息数量")
    plugin_call_count: int = Field(..., description="插件调用次数")


class FriendStatistics(BaseModel):
    """好友统计"""
    user_id: str = Field(..., description="用户 ID")
    user_name: str = Field(..., description="用户名称")
    message_count: int = Field(..., description="消息数量")
    plugin_call_count: int = Field(..., description="插件调用次数")


class DetailedStatistics(BaseModel):
    """详细统计数据"""
    groups: list[GroupStatistics] = Field(default_factory=list, description="群组统计列表")
    friends: list[FriendStatistics] = Field(default_factory=list, description="好友统计列表")

class CommitResult(BaseModel):
    """仓库提交"""
    sha: str = Field(...,description="sha")
    author: str = Field(...,description="作者")
    avatar_url: str = Field(...,description="作者头像")
    date: str = Field(...,description="时间")
    message: str = Field(...,description="消息")


