"""仪表盘服务"""
from datetime import datetime, timedelta

from tortoise.functions import Count

from zhenxun.models.chat_history import ChatHistory
from zhenxun.models.group_console import GroupConsole
from zhenxun.models.statistics import Statistics
from zhenxun.models.user_console import UserConsole

from ..models.dashboard import (
    DashboardOverview,
    DashboardResult,
    DashboardStats,
    DetailedStatistics,
    FriendStatistics,
    GroupStatistics,
    QuickAction,
    StatItem,
)
from .system_service import get_system_health

# 模块级缓存，避免重复定义
QUICK_ACTIONS = [
    QuickAction(name="重启 Bot", description="重启机器人服务", icon="refresh", action_type="restart"),
    QuickAction(name="清理缓存", description="清理系统缓存", icon="clean", action_type="clear_cache"),
    QuickAction(name="查看日志", description="查看系统日志", icon="file-text", action_type="view_logs"),
    QuickAction(name="备份数据", description="备份数据库", icon="database", action_type="backup"),
]


def _calc_trend(current: int, previous: int) -> tuple[str, float | None]:
    """计算趋势"""
    if previous == 0:
        return ("stable", None) if current == 0 else ("up", 100.0)
    change = ((current - previous) / previous) * 100
    if change > 5:
        return ("up", change)
    if change < -5:
        return ("down", change)
    return ("stable", change)


class DashboardService:
    """仪表盘服务"""

    @staticmethod
    async def get_dashboard() -> DashboardResult:
        """获取仪表盘数据"""
        overview = await DashboardService._get_overview()
        stats = await DashboardService._get_stats()
        health = await get_system_health()

        return DashboardResult(
            overview=overview,
            stats=stats,
            quick_actions=QUICK_ACTIONS,
            system_health=health.status,
        )

    @staticmethod
    async def _get_overview() -> DashboardOverview:
        """获取概览数据"""
        import nonebot

        bots = nonebot.get_bots()
        bot_status = "online" if bots else "offline"

        # 运行时长
        uptime = 0
        uptime_formatted = "0 秒"
        try:
            from zhenxun.models.bot_console import BotConsole
            from zhenxun.utils.formatters import format_uptime

            bot_console = await BotConsole.first()
            if bot_console and bot_console.create_time:
                uptime = int((datetime.now() - bot_console.create_time).total_seconds())
                uptime_formatted = format_uptime(uptime)
        except Exception:
            pass

        # 群组和好友数量
        group_count = 0
        friend_count = 0
        try:
            group_count = await GroupConsole.all().count()
        except Exception:
            pass

        # 今日消息数量
        message_count_today = 0
        try:
            now = datetime.now()
            message_count_today = await ChatHistory.filter(
                create_time__gte=now.replace(hour=0, minute=0, second=0)
            ).count()
        except Exception:
            pass

        # 插件数量
        plugin_count = 0
        enabled_plugin_count = 0
        try:
            from zhenxun.models.db_plugin_info import DbPluginInfo

            plugin_count = await DbPluginInfo.filter(load_status=True).count()
            enabled_plugin_count = await DbPluginInfo.filter(
                load_status=True, status=True
            ).count()
        except Exception:
            pass

        return DashboardOverview(
            bot_status=bot_status,
            uptime=uptime,
            uptime_formatted=uptime_formatted,
            group_count=group_count,
            friend_count=friend_count,
            message_count_today=message_count_today,
            plugin_count=plugin_count,
            enabled_plugin_count=enabled_plugin_count,
        )

    @staticmethod
    async def _get_stats() -> DashboardStats:
        """获取统计数据"""
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0)
        yesterday_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0)

        # 消息统计
        message_total = 0
        message_yesterday = 0
        try:
            message_total = await ChatHistory.filter(create_time__gte=today_start).count()
            message_yesterday = await ChatHistory.filter(
                create_time__gte=yesterday_start,
                create_time__lt=today_start,
            ).count()
        except Exception:
            pass

        # 用户统计
        user_count = 0
        try:
            user_count = await UserConsole.all().count()
        except Exception:
            pass

        # 群组统计
        group_count = 0
        try:
            group_count = await GroupConsole.all().count()
        except Exception:
            pass

        # 错误统计
        error_count = 0
        try:
            from zhenxun.models.bot_connect_log import BotConnectLog

            error_count = await BotConnectLog.filter(
                create_time__gte=now - timedelta(days=7)
            ).count()
        except Exception:
            pass

        message_trend, message_change = _calc_trend(message_total, message_yesterday)

        return DashboardStats(
            message_stats=StatItem(
                label="消息数量",
                value=message_total,
                trend=message_trend,
                change=message_change,
            ),
            user_stats=StatItem(label="用户数量", value=user_count, trend="stable"),
            group_stats=StatItem(label="群组数量", value=group_count, trend="stable"),
            error_stats=StatItem(label="错误数量", value=error_count, trend="stable"),
        )

    @staticmethod
    async def get_detailed_statistics() -> DetailedStatistics:
        """获取详细统计数据（群组/好友消息和调用情况）"""
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0)

        # 获取群组消息统计
        group_stats = await DashboardService._get_group_statistics(today_start)

        # 获取好友（私聊）消息统计
        friend_stats = await DashboardService._get_friend_statistics(today_start)

        return DetailedStatistics(groups=group_stats, friends=friend_stats)

    @staticmethod
    async def _get_group_statistics(today_start: datetime) -> list[GroupStatistics]:
        """获取群组统计数据"""
        group_stats = []
        try:
            # 按群组 ID 分组统计消息数量
            group_msg_counts = await ChatHistory.filter(
                group_id__not_isnull=True,
                create_time__gte=today_start
            ).annotate(count=Count("id")).group_by("group_id").values("group_id", "count")

            # 按群组 ID 分组统计插件调用次数
            group_call_counts = await Statistics.filter(
                group_id__not_isnull=True,
                create_time__gte=today_start
            ).annotate(count=Count("id")).group_by("group_id").values("group_id", "count")

            # 构建映射
            group_msg_map = {item["group_id"]: item["count"] for item in group_msg_counts}
            group_call_map = {item["group_id"]: item["count"] for item in group_call_counts}
            all_group_ids = set(group_msg_map.keys()) | set(group_call_map.keys())

            # 获取群组名称并构建结果
            for group_id in all_group_ids:
                group_console = await GroupConsole.filter(group_id=group_id).first()
                group_name = group_console.group_name if group_console else f"群 {group_id}"
                group_stats.append(GroupStatistics(
                    group_id=group_id,
                    group_name=group_name,
                    message_count=group_msg_map.get(group_id, 0),
                    plugin_call_count=group_call_map.get(group_id, 0),
                ))

            group_stats.sort(key=lambda x: x.message_count, reverse=True)
        except Exception as e:
            print(f"获取群组统计失败：{e}")

        return group_stats

    @staticmethod
    async def _get_friend_statistics(today_start: datetime) -> list[FriendStatistics]:
        """获取好友统计数据"""
        friend_stats = []
        try:
            # 按用户 ID 分组统计私聊消息数量
            friend_msg_counts = await ChatHistory.filter(
                group_id__isnull=True,
                create_time__gte=today_start
            ).annotate(count=Count("id")).group_by("user_id").values("user_id", "count")

            # 按用户 ID 分组统计私聊插件调用次数
            friend_call_counts = await Statistics.filter(
                group_id__isnull=True,
                create_time__gte=today_start
            ).annotate(count=Count("id")).group_by("user_id").values("user_id", "count")

            # 构建映射
            friend_msg_map = {item["user_id"]: item["count"] for item in friend_msg_counts}
            friend_call_map = {item["user_id"]: item["count"] for item in friend_call_counts}
            all_user_ids = set(friend_msg_map.keys()) | set(friend_call_map.keys())

            # 获取用户名称并构建结果
            for user_id in all_user_ids:
                user_console = await UserConsole.filter(user_id=user_id).first()
                user_name = user_console.user_name if user_console else f"用户 {user_id}"
                friend_stats.append(FriendStatistics(
                    user_id=user_id,
                    user_name=user_name,
                    message_count=friend_msg_map.get(user_id, 0),
                    plugin_call_count=friend_call_map.get(user_id, 0),
                ))

            friend_stats.sort(key=lambda x: x.message_count, reverse=True)
        except Exception as e:
            print(f"获取好友统计失败：{e}")

        return friend_stats
