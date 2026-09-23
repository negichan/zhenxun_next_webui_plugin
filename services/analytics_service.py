"""数据分析服务"""
from datetime import datetime, timedelta
from typing import Literal

from tortoise.expressions import Q, RawSQL
from tortoise.functions import Count

from zhenxun.models.chat_history import ChatHistory
from zhenxun.models.group_console import GroupConsole
from zhenxun.models.sign_user import SignUser
from zhenxun.models.statistics import Statistics
from zhenxun.models.user_console import UserConsole

from ..models.analytics import (
    AnalyticsOverview,
    DetailedStatisticsTimeRange,
    FriendStatisticsTimeRange,
    GroupStatisticsTimeRange,
    MessageHeatmap,
    TrendData,
    TrendPoint,
    FavorabilityRank,
    GoldRank,
)

Granularity = Literal["hour", "day", "week", "month"]


class AnalyticsService:
    """数据分析服务"""

    @staticmethod
    def generate_time_ranges(
        start_time: datetime,
        end_time: datetime,
        granularity: Granularity,
    ) -> list[tuple[datetime, datetime]]:
        """生成时间范围列表

        参数:
            start_time: 起始时间
            end_time: 结束时间
            granularity: 时间粒度

        返回:
            list[tuple[datetime, datetime]]: 时间范围列表 [(start, end), ...]
        """
        ranges = []
        current = start_time

        while current < end_time:
            if granularity == "hour":
                next_time = current + timedelta(hours=1)
            elif granularity == "day":
                next_time = current + timedelta(days=1)
            elif granularity == "week":
                # 按周分组（周一为一周开始）
                days_until_monday = (7 - current.weekday()) % 7
                if days_until_monday == 0:
                    days_until_monday = 7
                next_time = current + timedelta(days=days_until_monday)
            elif granularity == "month":
                # 按月分组
                if current.month == 12:
                    next_time = current.replace(year=current.year + 1, month=1, day=1)
                else:
                    next_time = current.replace(month=current.month + 1, day=1)
            else:
                next_time = current + timedelta(days=1)

            # 确保不超过结束时间
            actual_end = min(next_time, end_time)
            ranges.append((current, actual_end))
            current = next_time

        return ranges

    @staticmethod
    async def get_trend_data(
        start_time: datetime,
        end_time: datetime,
        granularity: Granularity = "day",
        bot_id: str | None = None,
    ) -> TrendData:
        """获取趋势数据

        参数:
            start_time: 起始时间
            end_time: 结束时间
            granularity: 时间粒度 (hour/day/week/month)
            bot_id: Bot ID，可选

        返回:
            TrendData: 趋势数据
        """
        time_ranges = AnalyticsService.generate_time_ranges(
            start_time, end_time, granularity
        )

        data_points = []
        total_messages = 0
        total_calls = 0

        for range_start, range_end in time_ranges:
            # 查询消息数量
            msg_query = ChatHistory.filter(
                create_time__gte=range_start,
                create_time__lt=range_end,
            )
            if bot_id:
                msg_query = msg_query.filter(bot_id=bot_id)
            msg_count = await msg_query.count()

            # 查询插件调用次数
            call_query = Statistics.filter(
                create_time__gte=range_start,
                create_time__lt=range_end,
            )
            if bot_id:
                call_query = call_query.filter(bot_id=bot_id)
            call_count = await call_query.count()

            data_points.append(
                TrendPoint(
                    timestamp=range_start,
                    message_count=msg_count,
                    plugin_call_count=call_count,
                )
            )

            total_messages += msg_count
            total_calls += call_count

        return TrendData(
            data_points=data_points,
            total_message_count=total_messages,
            total_plugin_call_count=total_calls,
            granularity=granularity,
            start_time=start_time,
            end_time=end_time,
        )

    @staticmethod
    async def get_overview(
        start_time: datetime,
        end_time: datetime,
        bot_id: str | None = None,
    ) -> AnalyticsOverview:
        """获取区间概览 KPI

        参数:
            start_time: 起始时间
            end_time: 结束时间
            bot_id: Bot ID，可选

        返回:
            AnalyticsOverview: 区间概览（含上一等长周期对比）
        """
        span = end_time - start_time
        if span.total_seconds() <= 0:
            span = timedelta(days=1)

        prev_end = start_time
        prev_start = prev_end - span

        async def _count(model, start: datetime, end: datetime) -> int:
            query = model.filter(create_time__gte=start, create_time__lt=end)
            if bot_id:
                query = query.filter(bot_id=bot_id)
            return await query.count()

        message_count = await _count(ChatHistory, start_time, end_time)
        plugin_call_count = await _count(Statistics, start_time, end_time)
        prev_message_count = await _count(ChatHistory, prev_start, prev_end)
        prev_plugin_call_count = await _count(Statistics, prev_start, prev_end)

        # 按日聚合消息，找峰值
        msg_query = ChatHistory.filter(
            create_time__gte=start_time, create_time__lt=end_time
        )
        if bot_id:
            msg_query = msg_query.filter(bot_id=bot_id)
        daily_rows = (
            await msg_query.annotate(
                date=RawSQL("DATE(create_time)"), count=Count("id")
            )
            .group_by("date")
            .values("date", "count")
        )
        peak_message_count = 0
        peak_date = ""
        for row in daily_rows:
            count = row.get("count") or 0
            day = row.get("date")
            if count > peak_message_count:
                peak_message_count = count
                peak_date = str(day) if day is not None else ""

        days = max(1, span.total_seconds() / 86400)
        avg_daily_messages = int(message_count / days)

        group_msg_query = ChatHistory.filter(
            group_id__not_isnull=True,
            create_time__gte=start_time,
            create_time__lt=end_time,
        )
        if bot_id:
            group_msg_query = group_msg_query.filter(bot_id=bot_id)
        active_group_count = (
            await group_msg_query.annotate(count=Count("id"))
            .group_by("group_id")
            .values("group_id")
        )
        active_groups = len(active_group_count)

        user_msg_query = ChatHistory.filter(
            create_time__gte=start_time, create_time__lt=end_time
        )
        if bot_id:
            user_msg_query = user_msg_query.filter(bot_id=bot_id)
        active_users = (
            await user_msg_query.annotate(count=Count("id"))
            .group_by("user_id")
            .values("user_id")
        )

        return AnalyticsOverview(
            message_count=message_count,
            plugin_call_count=plugin_call_count,
            avg_daily_messages=avg_daily_messages,
            peak_message_count=peak_message_count,
            peak_date=peak_date,
            active_group_count=active_groups,
            active_user_count=len(active_users),
            prev_message_count=prev_message_count,
            prev_plugin_call_count=prev_plugin_call_count,
        )

    @staticmethod
    async def get_heatmap(
        start_time: datetime,
        end_time: datetime,
        bot_id: str | None = None,
    ) -> MessageHeatmap:
        """获取消息热力图（周一=0 × 小时 0-23）

        参数:
            start_time: 起始时间
            end_time: 结束时间
            bot_id: Bot ID，可选

        返回:
            MessageHeatmap: 7×24 矩阵
        """
        matrix = [[0 for _ in range(24)] for _ in range(7)]
        total = 0

        query = ChatHistory.filter(
            create_time__gte=start_time, create_time__lt=end_time
        )
        if bot_id:
            query = query.filter(bot_id=bot_id)

        # 仅取时间戳在内存聚合，跨 SQLite/MySQL/PG 行为一致
        times = await query.values_list("create_time", flat=True)
        for t in times:
            if t is None:
                continue
            # Python weekday(): Monday=0
            matrix[t.weekday()][t.hour] += 1
            total += 1

        max_count = max((max(row) for row in matrix), default=0)
        return MessageHeatmap(
            matrix=matrix,
            max_count=max_count,
            total=total,
        )

    @staticmethod
    async def get_detailed_statistics(
        start_time: datetime,
        end_time: datetime,
        bot_id: str | None = None,
    ) -> DetailedStatisticsTimeRange:
        """获取详细统计数据（带时间范围）

        参数:
            start_time: 起始时间
            end_time: 结束时间
            bot_id: Bot ID，可选

        返回:
            DetailedStatisticsTimeRange: 详细统计数据
        """
        # 群组统计
        group_stats = []
        try:
            # 按群组 ID 分组统计消息数量
            group_msg_query = ChatHistory.filter(
                group_id__not_isnull=True,
                create_time__gte=start_time,
                create_time__lt=end_time,
            )
            if bot_id:
                group_msg_query = group_msg_query.filter(bot_id=bot_id)

            group_msg_counts = await group_msg_query.annotate(
                count=Count("id")
            ).group_by("group_id").values("group_id", "count")

            # 按群组 ID 分组统计插件调用次数
            group_call_query = Statistics.filter(
                group_id__not_isnull=True,
                create_time__gte=start_time,
                create_time__lt=end_time,
            )
            if bot_id:
                group_call_query = group_call_query.filter(bot_id=bot_id)

            group_call_counts = await group_call_query.annotate(
                count=Count("id")
            ).group_by("group_id").values("group_id", "count")

            # 构建映射
            group_msg_map = {
                item["group_id"]: item["count"] for item in group_msg_counts
            }
            group_call_map = {
                item["group_id"]: item["count"] for item in group_call_counts
            }

            # 获取所有群组 ID
            all_group_ids = set(group_msg_map.keys()) | set(group_call_map.keys())

            # 获取群组名称并构建结果
            for group_id in all_group_ids:
                group_console = await GroupConsole.filter(group_id=group_id).first()
                group_name = (
                    group_console.group_name if group_console else f"群 {group_id}"
                )
                ava_url = f"http://p.qlogo.cn/gh/{group_id}/{group_id}/640/"

                group_stats.append(
                    GroupStatisticsTimeRange(
                        group_id=group_id,
                        group_name=group_name,
                        message_count=group_msg_map.get(group_id, 0),
                        plugin_call_count=group_call_map.get(group_id, 0),
                        ava_url=ava_url,
                    )
                )

            # 按消息数量降序排序
            group_stats.sort(key=lambda x: x.message_count, reverse=True)
        except Exception as e:
            print(f"获取群组统计失败：{e}")

        # 好友统计
        friend_stats = []
        try:
            # 按用户 ID 分组统计私聊消息数量
            friend_msg_query = ChatHistory.filter(
                group_id__isnull=True,
                create_time__gte=start_time,
                create_time__lt=end_time,
            )
            if bot_id:
                friend_msg_query = friend_msg_query.filter(bot_id=bot_id)

            friend_msg_counts = await friend_msg_query.annotate(
                count=Count("id")
            ).group_by("user_id").values("user_id", "count")

            # 按用户 ID 分组统计私聊插件调用次数
            friend_call_query = Statistics.filter(
                group_id__isnull=True,
                create_time__gte=start_time,
                create_time__lt=end_time,
            )
            if bot_id:
                friend_call_query = friend_call_query.filter(bot_id=bot_id)

            friend_call_counts = await friend_call_query.annotate(
                count=Count("id")
            ).group_by("user_id").values("user_id", "count")

            # 构建映射
            friend_msg_map = {
                item["user_id"]: item["count"] for item in friend_msg_counts
            }
            friend_call_map = {
                item["user_id"]: item["count"] for item in friend_call_counts
            }

            # 获取所有用户 ID
            all_user_ids = set(friend_msg_map.keys()) | set(friend_call_map.keys())

            # 获取用户名称并构建结果
            for user_id in all_user_ids:
                user_console = await UserConsole.filter(user_id=user_id).first()
                user_name = (
                    user_console.user_name if user_console else f"用户 {user_id}"
                )
                ava_url = f"http://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"

                friend_stats.append(
                    FriendStatisticsTimeRange(
                        user_id=user_id,
                        user_name=user_name,
                        message_count=friend_msg_map.get(user_id, 0),
                        plugin_call_count=friend_call_map.get(user_id, 0),
                        ava_url=ava_url,
                    )
                )

            # 按消息数量降序排序
            friend_stats.sort(key=lambda x: x.message_count, reverse=True)
        except Exception as e:
            print(f"获取好友统计失败：{e}")

        return DetailedStatisticsTimeRange(
            groups=group_stats,
            friends=friend_stats,
            start_time=start_time,
            end_time=end_time,
        )

    @staticmethod
    async def get_favorability_top10(
        bot_id: str | None = None,
    ) -> list[FavorabilityRank]:
        """获取好感度 top10 用户

        参数:
            bot_id: Bot ID，可选

        返回:
            list[FavorabilityRank]: 好感度排名列表
        """
        query = SignUser.all().filter(impression__gt=0)
        if bot_id:
            # 如果需要按 bot_id 过滤，可以通过 user_console 关联
            # 这里暂时不过滤，因为好感度是全局的
            pass

        # 按好感度降序排序，取前 10 名
        sign_users = (
            await query.order_by("-impression")
            .limit(10)
            .prefetch_related("user_console")
        )

        result = []
        for sign_user in sign_users:
            user_console = sign_user.user_console
            display_name = (
                user_console.user_name if user_console and user_console.user_name
                else str(sign_user.user_id)
            )
            result.append(
                FavorabilityRank(
                    user_id=str(user_console.user_id if user_console else sign_user.user_id),
                    user_name=display_name,
                    favorability=float(sign_user.impression),
                    ava_url=f"http://q1.qlogo.cn/g?b=qq&nk={sign_user.user_id}&s=640",
                )
            )

        return result

    @staticmethod
    async def get_gold_top10(
        bot_id: str | None = None,
    ) -> list[GoldRank]:
        """获取金币 top10 用户

        参数:
            bot_id: Bot ID，可选

        返回:
            list[GoldRank]: 金币排名列表
        """
        query = UserConsole.all().filter(gold__gt=0)

        # 按金币降序排序，取前 10 名
        users = await query.order_by("-gold").limit(10)

        result = []
        for user in users:
            display_name = user.user_name if user.user_name else str(user.user_id)
            result.append(
                GoldRank(
                    user_id=str(user.user_id),
                    user_name=display_name,
                    gold=user.gold,
                    ava_url=f"http://q1.qlogo.cn/g?b=qq&nk={user.user_id}&s=640",
                )
            )

        return result
