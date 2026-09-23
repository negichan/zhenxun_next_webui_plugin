"""主页服务"""
from datetime import datetime, timedelta, timezone

from zhenxun.models.bot_connect_log import BotConnectLog
from zhenxun.models.chat_history import ChatHistory
from zhenxun.models.group_console import GroupConsole
from zhenxun.models.statistics import Statistics
import nonebot
from zhenxun.configs.config import BotConfig
import asyncio

from zhenxun.utils.platform import PlatformUtils
from ..models.system import BotStatus, BotStatusListData, BotInfo
from ..utils.formatters import format_uptime
from nonebot.adapters import Bot
from zhenxun.services.log import logger


class MainService:
    """主页服务"""

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime:
        """统一时间对象时区，避免 aware/naive 混用"""
        if value is None:
            return datetime.now()
        if value.tzinfo is None:
            return value
        return value.astimezone().replace(tzinfo=None)

    @staticmethod
    async def _get_latest_connect_times() -> dict[str, datetime]:
        """获取每个 Bot 最近连接时间"""
        try:
            from zhenxun.models.bot_connect_log import BotConnectLog

            logs = await BotConnectLog.filter(type=1).order_by("-connect_time").all()
            latest_connects: dict[str, datetime] = {}
            for log in logs:
                bot_id = str(log.bot_id)
                if bot_id not in latest_connects and log.connect_time:
                    latest_connects[bot_id] = log.connect_time
            return latest_connects
        except Exception:
            return {}

    @classmethod
    async def __build_bot_info(cls, bot: Bot) -> BotInfo:
        """构建Bot信息

        参数:
            bot: Bot

        返回:
            BotInfo: Bot信息
        """
        now = datetime.now()
        platform = PlatformUtils.get_platform(bot) or ""
        if platform == "qq":
            try:
                login_info = await bot.get_login_info()
                nickname = login_info.get("nickname") or str(bot.self_id)
                ava_url = login_info.get("face_url") or ""
            except Exception as e:
                # 模拟端/部分实现未提供 get_login_info 时不能让整张列表 500
                logger.warning(
                    "获取 bot 登录信息失败，使用兜底展示...", "WebUi", e=e
                )
                nickname = str(bot.self_id)
                ava_url = ""
            if not ava_url and str(bot.self_id).isdigit():
                # 普通 QQ bot（数字账号）：直接用 QQ 头像地址
                ava_url = f"http://q1.qlogo.cn/g?b=qq&nk={bot.self_id}&s=160"
            if not ava_url:
                # 官方 bot（uid 非数字）：走 qqapp 头像地址
                ava_url = (
                    PlatformUtils.get_user_avatar_url(
                        bot.self_id, "qq", BotConfig.get_qbot_uid(bot.self_id)
                    )
                    or ""
                )
        else:
            nickname = bot.self_id
            ava_url = ""
        bot_info = BotInfo(
            self_id=bot.self_id, nickname=nickname, ava_url=ava_url, platform=platform
        )
        try:
            group, friend = await asyncio.gather(
                PlatformUtils.get_group_list(bot, True),
                PlatformUtils.get_friend_list(bot),
            )
            bot_info.group_count = len(group[0])
            bot_info.friend_count = len(friend[0])
        except Exception as e:
            logger.warning("获取bot好友/群组信息失败...", "WebUi", e=e)
            bot_info.group_count = 0
            bot_info.friend_count = 0
        bot_info.day_call = await Statistics.filter(
            create_time__gte=now - timedelta(hours=now.hour, minutes=now.minute),
            bot_id=bot.self_id,
        ).count()
        bot_info.received_messages = await ChatHistory.filter(
            bot_id=bot_info.self_id,
            create_time__gte=now - timedelta(hours=now.hour, minutes=now.minute),
        ).count()
        bot_info.messages_total = await ChatHistory.filter(
            bot_id=bot_info.self_id,
        ).count()
        bot_info.total_call = await Statistics.filter(
            bot_id=bot_info.self_id,
        ).count()
        return bot_info

    @classmethod
    async def _build_bot_info_safe(cls, bot: Bot) -> BotInfo:
        """单个 bot 信息构建：限时 + 兜底，模拟端不响应时快速退化不拖垮整表"""
        try:
            # 模拟端/不响应协议的 bot 会让 get_login_info/get_*_list 卡到
            # nonebot 默认 30s 超时；快速失败(4s)走兜底
            return await asyncio.wait_for(cls.__build_bot_info(bot), timeout=4)
        except Exception as e:
            logger.warning(
                f"构建 bot 信息失败，使用兜底展示：{bot.self_id}",
                "WebUi",
                e=e,
            )
            return BotInfo(
                self_id=str(bot.self_id),
                nickname=str(bot.self_id),
                ava_url="",
                platform=PlatformUtils.get_platform(bot) or "",
            )

    @classmethod
    async def get_bot_list(cls) -> list[BotInfo]:
        """获取bot列表

        并发构建每个 bot（互不阻塞），单个卡死只拖自己那 4s、且各自兜底，
        整表最坏 ~4s 返回，保证 bot 上下线通知能及时刷新。

        返回:
            list[BotInfo]: Bot列表
        """
        bots = list(nonebot.get_bots().values())
        if not bots:
            return []
        return list(
            await asyncio.gather(
                *(cls._build_bot_info_safe(bot) for bot in bots)
            )
        )

    @staticmethod
    async def _build_bot_status(bot, latest_connects: dict[str, datetime], group_count: int) -> BotStatus:
        """构建单个 Bot 状态"""
        self_id = getattr(bot, "self_id", None)
        nickname: str | None = None
        ava_url: str | None = None

        try:
            bot_info = await bot.get_login_info()
            nickname = bot_info.get("nickname")
            ava_url = bot_info.get("face_url")
        except Exception:
            pass

        if not ava_url and self_id:
            ava_url = f"http://q1.qlogo.cn/g?b=qq&nk={self_id}&s=640"

        start_time = MainService._normalize_datetime(
            latest_connects.get(str(self_id), datetime.now(timezone.utc))
        )
        uptime = int((datetime.now() - start_time).total_seconds())

        return BotStatus(
            self_id=str(self_id) if self_id is not None else None,
            nickname=nickname,
            ava_url=ava_url,
            is_running=True,
            uptime=uptime,
            uptime_formatted=format_uptime(uptime),
            group_count=group_count,
            friend_count=0,
            message_count=0,
            start_time=start_time,
        )

    @staticmethod
    async def get_bot_status_list(bot_id: str | None = None) -> BotStatusListData:
        """获取 Bot 状态列表"""
        import nonebot

        bots = nonebot.get_bots()
        latest_connects = await MainService._get_latest_connect_times()

        group_count = 0
        try:
            group_count = await GroupConsole.all().count()
        except Exception:
            pass

        bot_statuses: list[BotStatus] = []
        for bot in bots.values():
            bot_statuses.append(
                await MainService._build_bot_status(bot, latest_connects, group_count)
            )

        current = None
        if bot_id:
            current = next((item for item in bot_statuses if item.self_id == str(bot_id)), None)
        if current is None and bot_statuses:
            current = bot_statuses[0]

        return BotStatusListData(current=current, bots=bot_statuses, total=len(bot_statuses))

    @staticmethod
    async def get_bot_status(bot_id: str | None = None) -> BotStatus:
        """获取 Bot 状态"""
        bot_status_list = await MainService.get_bot_status_list(bot_id)
        if bot_status_list.current:
            return bot_status_list.current

        return BotStatus(
            self_id=None,
            nickname=None,
            ava_url=None,
            is_running=False,
            uptime=0,
            uptime_formatted=format_uptime(0),
            group_count=0,
            friend_count=0,
            message_count=0,
            start_time=datetime.now(),
        )

    @staticmethod
    async def get_chat_statistics(bot_id: str | None = None) -> dict:
        """获取聊天统计"""

        now = datetime.now()
        query = ChatHistory.all()
        if bot_id: query = query.filter(bot_id=bot_id)
        return {"all": await query.count(),
                "day": await query.filter(create_time__gte=now.replace(hour=0, minute=0, second=0)).count(),
                "week": await query.filter(create_time__gte=now - timedelta(days=7)).count(),
                "month": await query.filter(create_time__gte=now - timedelta(days=30)).count(),
                "year": await query.filter(create_time__gte=now - timedelta(days=365)).count(), }

    @staticmethod
    async def get_plugin_statistics(bot_id: str | None = None) -> dict:
        """获取插件调用统计"""
        now = datetime.now()
        query = Statistics.all()
        if bot_id:
            query = query.filter(bot_id=bot_id)

        return {
            "all": await query.count(),
            "day": await query.filter(create_time__gte=now.replace(hour=0, minute=0, second=0)).count(),
            "week": await query.filter(create_time__gte=now - timedelta(days=7)).count(),
            "month": await query.filter(create_time__gte=now - timedelta(days=30)).count(),
            "year": await query.filter(create_time__gte=now - timedelta(days=365)).count(),
        }

    @staticmethod
    async def get_active_groups(
        start_time: str | None = None,
        end_time: str | None = None,
        date_type: str = "week",
        bot_id: str | None = None,
    ) -> list[dict]:
        """获取活跃群组

        参数:
            start_time: 起始时间 (ISO 8601 格式)，可选
            end_time: 结束时间 (ISO 8601 格式)，可选
            date_type: 日期类型 (day/week/month/year)，当未提供 start_time/end_time 时使用
            bot_id: Bot ID

        返回:
            list[dict]: 活跃群组列表
        """
        query = ChatHistory.all()
        if bot_id:
            query = query.filter(bot_id=bot_id)

        # 如果提供了 start_time 和 end_time，使用自定义时间范围
        if start_time and end_time:
            try:
                start_dt = datetime.fromisoformat(start_time)
                end_dt = datetime.fromisoformat(end_time)
                query = query.filter(create_time__gte=start_dt, create_time__lte=end_dt)
            except ValueError:
                # 如果解析失败，回退到 date_type
                pass
        else:
            # 使用 date_type
            now = datetime.now()
            if date_type == "day":
                query = query.filter(
                    create_time__gte=now
                    - timedelta(hours=now.hour, minutes=now.minute, seconds=now.second)
                )
            elif date_type == "week":
                query = query.filter(
                    create_time__gte=now
                    - timedelta(
                        days=7, hours=now.hour, minutes=now.minute, seconds=now.second
                    )
                )
            elif date_type == "month":
                query = query.filter(
                    create_time__gte=now
                    - timedelta(
                        days=30, hours=now.hour, minutes=now.minute, seconds=now.second
                    )
                )
            elif date_type == "year":
                query = query.filter(
                    create_time__gte=now
                    - timedelta(
                        days=365, hours=now.hour, minutes=now.minute, seconds=now.second
                    )
                )

        # 按群组分组统计
        from tortoise.functions import Count

        data_list = (
            await query.annotate(count=Count("id"))
            .filter(group_id__not_isnull=True)
            .group_by("group_id")
            .order_by("-count")
            .limit(10)
            .values_list("group_id", "count")
        )

        # 获取群组名称
        id2name = {}
        if data_list:
            group_ids = [x[0] for x in data_list]
            groups = await GroupConsole.filter(group_id__in=group_ids).all()
            for group in groups:
                id2name[group.group_id] = group.group_name

        result = []
        for group_id, count in data_list:
            result.append(
                {
                    "group_id": group_id,
                    "name": id2name.get(group_id) or str(group_id),
                    "chat_num": count,
                    "ava_img": f"http://p.qlogo.cn/gh/{group_id}/{group_id}/640/",
                }
            )

        return result

    @staticmethod
    async def get_hot_plugins(
        start_time: str | None = None,
        end_time: str | None = None,
        date_type: str = "week",
        bot_id: str | None = None,
    ) -> list[dict]:
        """获取热门插件

        参数:
            start_time: 起始时间 (ISO 8601 格式)，可选
            end_time: 结束时间 (ISO 8601 格式)，可选
            date_type: 日期类型 (day/week/month/year)，当未提供 start_time/end_time 时使用
            bot_id: Bot ID

        返回:
            list[dict]: 热门插件列表
        """
        from tortoise.functions import Count

        from zhenxun.models.plugin_info import PluginInfo

        query = Statistics.all()
        if bot_id:
            query = query.filter(bot_id=bot_id)

        # 如果提供了 start_time 和 end_time，使用自定义时间范围
        if start_time and end_time:
            try:
                start_dt = datetime.fromisoformat(start_time)
                end_dt = datetime.fromisoformat(end_time)
                query = query.filter(create_time__gte=start_dt, create_time__lte=end_dt)
            except ValueError:
                # 如果解析失败，回退到 date_type
                pass
        else:
            # 使用 date_type
            now = datetime.now()
            if date_type == "day":
                query = query.filter(
                    create_time__gte=now
                    - timedelta(hours=now.hour, minutes=now.minute, seconds=now.second)
                )
            elif date_type == "week":
                query = query.filter(
                    create_time__gte=now
                    - timedelta(
                        days=7, hours=now.hour, minutes=now.minute, seconds=now.second
                    )
                )
            elif date_type == "month":
                query = query.filter(
                    create_time__gte=now
                    - timedelta(
                        days=30, hours=now.hour, minutes=now.minute, seconds=now.second
                    )
                )
            elif date_type == "year":
                query = query.filter(
                    create_time__gte=now
                    - timedelta(
                        days=365, hours=now.hour, minutes=now.minute, seconds=now.second
                    )
                )

        # 按插件名分组统计
        data_list = (
            await query.annotate(count=Count("id"))
            .filter(plugin_name__not_isnull=True)
            .group_by("plugin_name")
            .order_by("-count")
            .limit(10)
            .values_list("plugin_name", "count")
        )

        # 获取插件名称
        module2name = {}
        if data_list:
            modules = [x[0] for x in data_list]
            plugins = await PluginInfo.filter(module__in=modules).all()
            module2name = {p.module: p.name for p in plugins}

        result = []
        for plugin_name, count in data_list:
            result.append(
                {
                    "plugin_name": module2name.get(plugin_name) or plugin_name,
                    "call_count": count,
                }
            )

        return result

    @staticmethod
    async def get_connection_log(limit: int = 200) -> list[dict]:
        """获取 Bot 连接日志

        参数:
            limit: 返回条数上限

        返回:
            list[dict]: 连接日志列表（按时间倒序）
        """
        limit = max(1, min(limit, 1000))
        records = await BotConnectLog.all().order_by("-id").limit(limit)
        return [
            {
                "id": r.id,
                "bot_id": r.bot_id,
                "platform": r.platform,
                "type": r.type if r.type is not None else 1,
                "connect_time": r.connect_time,
            }
            for r in records
        ]
