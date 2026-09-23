"""管理服务"""
import nonebot
from datetime import datetime, timedelta
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from tortoise.expressions import Q

from zhenxun.models.ban_console import BanConsole
from zhenxun.models.chat_history import ChatHistory
from zhenxun.models.fg_request import FgRequest
from zhenxun.models.friend_user import FriendUser
from zhenxun.models.group_console import GroupConsole
from zhenxun.models.group_member_info import GroupInfoUser
from zhenxun.models.level_user import LevelUser
from zhenxun.models.sign_user import SignUser
from zhenxun.models.statistics import Statistics
from zhenxun.models.user_console import UserConsole
from zhenxun.services.log import logger
from zhenxun.utils.enum import RequestHandleType, RequestType
from zhenxun.utils.message import MessageUtils
from zhenxun.utils.common_utils import CommonUtils
from zhenxun.utils.platform import PlatformUtils

from ..models.manage import (
    FriendRequestResult,
    GroupDetail,
    GroupMember,
    GroupRequestResult,
    GroupStatistics,
    MemberDetail,
    FriendDetail,
    FriendTrend,
    FriendTrendPoint,
)
from ..models.system import Friend, Group


def convert_module_format(data: str | list[str]) -> str | list[str]:
    """在 `<aaa,<bbb,<ccc,` 和 `["aaa", "bbb", "ccc"]` 之间转换

    参数:
        data: 要转换的数据

    返回:
        str | list[str]: 根据输入类型返回转换后的数据
    """
    if isinstance(data, str):
        return [item.strip(",").strip("<") for item in data.split("<") if item.strip()]
    else:
        return "".join(f"<{item}," for item in data)


class ManageService:
    """管理服务"""

    @staticmethod
    def _normalize_forward_segment(seg: dict) -> dict | None:
        """把 OneBot 原始段归一为 {type, content}（content 为可展示串/URL/id）"""
        if not isinstance(seg, dict):
            return None
        t = seg.get("type")
        d = seg.get("data") or {}
        if t == "text":
            return {"type": "text", "content": str(d.get("text", ""))}
        if t == "image":
            return {"type": "image", "content": str(d.get("url") or d.get("file") or "")}
        if t in ("record", "voice"):
            return {"type": "record", "content": str(d.get("url") or d.get("file") or "")}
        if t == "video":
            return {"type": "video", "content": str(d.get("url") or d.get("file") or "")}
        if t == "face":
            return {"type": "face", "content": str(d.get("id", ""))}
        if t == "at":
            qq = str(d.get("qq", ""))
            return {"type": "at", "content": "全体成员" if qq == "all" else f"@{qq}"}
        if t in ("json", "xml"):
            return {"type": t, "content": str(d.get("data", ""))}
        if t:
            return {"type": "text", "content": f"[{t}]"}
        return None

    @staticmethod
    async def get_forward_messages(
        bot_id: str | None = None, forward_id: str = ""
    ) -> list[dict]:
        """拉取合并转发的节点列表，归一为 {user_id, nickname, time, segments}"""
        try:
            if bot_id:
                bot = nonebot.get_bot(bot_id)
            else:
                bots = nonebot.get_bots()
                if not bots:
                    return []
                bot = list(bots.values())[0]
            result = await bot.call_api("get_forward_msg", message_id=forward_id)
        except Exception as e:
            logger.error(f"获取转发消息失败：{e}", "ManageService:get_forward_messages")
            return []

        data = (result or {}).get("data") or {}
        nodes = data.get("messages") or data.get("nodes") or []
        out: list[dict] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            raw = node.get("message") or node.get("content") or []
            if isinstance(raw, str):
                segments = [{"type": "text", "content": raw}]
            else:
                segments = [
                    s
                    for s in (
                        ManageService._normalize_forward_segment(seg) for seg in raw
                    )
                    if s
                ]
            sender = node.get("sender") or {}
            out.append(
                {
                    "user_id": str(node.get("user_id", "")),
                    "nickname": str(
                        sender.get("card") or sender.get("nickname") or "未知"
                    ),
                    "time": node.get("time") or node.get("sender", {}).get("time"),
                    "segments": segments,
                }
            )
        return out

    @staticmethod
    def _forward_seg_to_onebot(seg: dict) -> MessageSegment | None:
        """把前端 {type, content} 段转成 OneBot v11 MessageSegment

        图片/语音的 content 为 base64:// 负载。
        """
        if not isinstance(seg, dict):
            return None
        t = seg.get("type")
        content = str(seg.get("content") or "")
        if t == "text" and content.strip():
            return MessageSegment.text(content)
        if t == "image" and content:
            return MessageSegment.image(content)
        if t in ("record", "voice") and content:
            return MessageSegment.record(content)
        if t == "face" and content.strip():
            try:
                return MessageSegment.face(int(content.strip()))
            except ValueError:
                return MessageSegment.text(f"[表情:{content}]")
        if t == "at" and content.strip():
            qq = content.strip()
            return (
                MessageSegment.at("all")
                if qq in ("all", "All")
                else MessageSegment.at(qq)
            )
        if t == "video" and content:
            return MessageSegment.video(content)
        if t == "json" and content.strip():
            return MessageSegment.json(content)
        if t == "xml" and content.strip():
            return MessageSegment.xml(content)
        if t == "node" and content.strip():
            try:
                return MessageSegment.node(int(content.strip()))
            except ValueError:
                return MessageSegment.text("[合并转发]")
        if content.strip():
            return MessageSegment.text(content)
        return None

    @staticmethod
    def _forward_seg_to_dict(seg: dict) -> dict | None:
        """前端 {type, content} 段 -> OneBot v11 原始段 dict

        供 go-cqhttp 系转发节点的 content 数组使用；图片/语音 content 为 base64://。
        """
        if not isinstance(seg, dict):
            return None
        t = seg.get("type")
        content = str(seg.get("content") or "")
        if t == "text" and content.strip():
            return {"type": "text", "data": {"text": content}}
        if t == "image" and content:
            return {"type": "image", "data": {"file": content}}
        if t in ("record", "voice") and content:
            return {"type": "record", "data": {"file": content}}
        if t == "face" and content.strip():
            return {"type": "face", "data": {"id": content.strip()}}
        if t == "at" and content.strip():
            qq = "all" if content.strip() in ("all", "All") else content.strip()
            return {"type": "at", "data": {"qq": qq}}
        if t == "video" and content:
            return {"type": "video", "data": {"file": content}}
        if t == "json" and content.strip():
            return {"type": "json", "data": {"data": content}}
        if t == "xml" and content.strip():
            return {"type": "xml", "data": {"data": content}}
        if t == "node" and content.strip():
            return {"type": "node", "data": {"id": content.strip()}}
        if content.strip():
            return {"type": "text", "data": {"text": content}}
        return None

    @staticmethod
    async def send_forward_messages(
        bot_id: str | None = None,
        user_id: str | None = None,
        group_id: str | None = None,
        nodes: list[dict] | None = None,
    ) -> bool:
        """合并转发：按兼容性分层尝试，命中即返回，全失败则逐条兜底。

        1) go-cqhttp 专有 send_group_forward_msg / send_private_forward_msg
           —— NapCat / LLOneBot / go-cqhttp 等主流实现已内置，节点用 uin/name/content
        2) 官方 v11 node 段（user_id/nickname/content）经 send_group_msg / send_private_msg
        3) 逐条发送每个节点内容，保证内容仍能转发出去（如 Lagrange 系两种都不支持）

        参数:
            nodes: [{name, uin, segments:[{type, content}]}]
        """
        try:
            if bot_id:
                bot = nonebot.get_bot(bot_id)
            else:
                bots = nonebot.get_bots()
                if not bots:
                    return False
                bot = list(bots.values())[0]

            if not nodes:
                return False
            if not group_id and not user_id:
                return False

            try:
                bot_uin = int(bot.self_id)
            except (TypeError, ValueError):
                bot_uin = 0

            def _uin(node: dict) -> int:
                try:
                    return int(node.get("uin") or bot_uin)
                except (TypeError, ValueError):
                    return bot_uin

            def _segs_dict(node: dict) -> list[dict]:
                segs = [
                    s
                    for s in (
                        ManageService._forward_seg_to_dict(seg)
                        for seg in (node.get("segments") or [])
                    )
                    if s
                ]
                return segs or [{"type": "text", "data": {"text": "[空消息]"}}]

            def _segs_msg(node: dict) -> Message:
                segs = [
                    s
                    for s in (
                        ManageService._forward_seg_to_onebot(seg)
                        for seg in (node.get("segments") or [])
                    )
                    if s
                ]
                return Message(segs or [MessageSegment.text("[空消息]")])

            async def _send_plain(message: Message) -> None:
                if group_id:
                    await bot.send_group_msg(group_id=int(group_id), message=message)
                else:
                    await bot.send_private_msg(user_id=int(user_id), message=message)

            # 1) go-cqhttp 专有合并转发动作（主流实现的事实标准）
            try:
                gocq_nodes = [
                    {
                        "type": "node",
                        "data": {
                            "uin": str(_uin(n)),
                            "name": str(n.get("name") or bot.self_id),
                            "content": _segs_dict(n),
                        },
                    }
                    for n in nodes
                ]
                if group_id:
                    await bot.call_api(
                        "send_group_forward_msg",
                        group_id=int(group_id),
                        messages=gocq_nodes,
                    )
                else:
                    await bot.call_api(
                        "send_private_forward_msg",
                        user_id=int(user_id),
                        messages=gocq_nodes,
                    )
                return True
            except Exception as e:
                logger.warning(
                    f"go-cqhttp 合并转发动作不可用，尝试官方 node 段：{e}",
                    "ManageService:send_forward_messages",
                )

            # 2) 官方 v11 node 段经普通发送接口
            try:
                merged = Message()
                for n in nodes:
                    merged += MessageSegment.node_custom(
                        user_id=_uin(n),
                        nickname=str(n.get("name") or bot.self_id),
                        content=_segs_msg(n),
                    )
                await _send_plain(merged)
                return True
            except Exception as e:
                logger.warning(
                    f"官方 node 段合并转发不可用，回退逐条：{e}",
                    "ManageService:send_forward_messages",
                )

            # 3) 逐条兜底
            ok = 0
            for n in nodes:
                try:
                    await _send_plain(_segs_msg(n))
                    ok += 1
                except Exception as e2:
                    logger.error(
                        f"回退逐条发送失败：{e2}",
                        "ManageService:send_forward_messages",
                    )
            return ok > 0
        except Exception as e:
            logger.error(
                f"合并转发发送失败：{e}", "ManageService:send_forward_messages"
            )
            return False

    @staticmethod
    async def send_segments(
        bot_id: str | None = None,
        user_id: str | None = None,
        group_id: str | None = None,
        segments: list[dict] | None = None,
    ) -> bool:
        """逐条转发：把归一 {type, content} 段用 nonebot MessageSegment 全量构造后发送。

        覆盖 text/image/record/video/face/at/json/xml/node，比 zxmsg 文本通道更全，
        供聊天页逐条转发任意类型消息使用。
        """
        try:
            if bot_id:
                bot = nonebot.get_bot(bot_id)
            else:
                bots = nonebot.get_bots()
                if not bots:
                    return False
                bot = list(bots.values())[0]

            if not group_id and not user_id:
                return False

            segs = [
                s
                for s in (
                    ManageService._forward_seg_to_onebot(seg)
                    for seg in (segments or [])
                )
                if s
            ]
            if not segs:
                return False
            msg = Message(segs)

            if group_id:
                await bot.send_group_msg(group_id=int(group_id), message=msg)
            else:
                await bot.send_private_msg(user_id=int(user_id), message=msg)
            return True
        except Exception as e:
            logger.error(f"分段发送失败：{e}", "ManageService:send_segments")
            return False

    @staticmethod
    async def send_message(
        bot_id: str | None = None,
        user_id: str | None = None,
        group_id: str | None = None,
        message: str = "",
    ) -> bool:
        """发送消息

        参数:
            bot_id: Bot ID
            user_id: 用户 ID
            group_id: 群组 ID
            message: 消息内容

        返回:
            bool: 是否发送成功
        """
        try:
            if bot_id:
                bot = nonebot.get_bot(bot_id)
            else:
                bots = nonebot.get_bots()
                if not bots:
                    return False
                bot = list(bots.values())[0]

            # 构建消息
            message_obj = MessageUtils.build_message(message)

            # 获取目标
            target = PlatformUtils.get_target(
                user_id=user_id, group_id=group_id
            )

            if not target:
                return False

            # 发送消息
            await message_obj.send(target=target, bot=bot)
            return True
        except Exception as e:
            logger.error(f"发送消息失败：{e}", "ManageService:send_message")
            return False

    @staticmethod
    async def get_friend_list(bot_id: str | None = None) -> list[Friend]:
        """获取好友列表

        参数:
            bot_id: Bot ID

        返回:
            list[Friend]: 好友列表
        """
        if bot_id:
            bot = nonebot.get_bot(bot_id)
        else:
            bots = nonebot.get_bots()
            if not bots:
                return []
            bot = list(bots.values())[0]

        friend_list, _ = await PlatformUtils.get_friend_list(bot)
        result = []
        for f in friend_list:
            # QQ 头像 URL，使用 referrerpolicy="no-referrer" 防止防盗链
            ava_url = f"http://q1.qlogo.cn/g?b=qq&nk={f.user_id}&s=640"
            result.append(
                Friend(
                    user_id=str(f.user_id),
                    nickname=f.user_name or "",
                    ava_url=ava_url,
                )
            )
        return result

    @staticmethod
    async def get_group_list(bot_id: str | None = None) -> list[Group]:
        """获取群组列表

        参数:
            bot_id: Bot ID

        返回:
            list[Group]: 群组列表
        """
        if bot_id:
            bot = nonebot.get_bot(bot_id)
        else:
            bots = nonebot.get_bots()
            if not bots:
                return []
            bot = list(bots.values())[0]

        group_list, _ = await PlatformUtils.get_group_list(bot)
        result = []
        for g in group_list:
            # 使用 https://p.qlogo.cn 支持 no-referer 防盗链
            ava_url = f"http://p.qlogo.cn/gh/{g.group_id}/{g.group_id}/640/"
            result.append(
                Group(
                    group_id=str(g.group_id),
                    group_name=g.group_name or "",
                    ava_url=ava_url,
                )
            )
        return result

    @staticmethod
    async def leave_group(bot_id: str | None = None, group_id: str | None = None) -> bool:
        """退群

        参数:
            bot_id: Bot ID
            group_id: 群组 ID

        返回:
            bool: 是否成功
        """
        try:
            if bot_id:
                bot = nonebot.get_bot(bot_id)
            else:
                bots = nonebot.get_bots()
                if not bots:
                    return False
                bot = list(bots.values())[0]

            if not group_id:
                return False

            await bot.set_group_leave(group_id=int(group_id))
            # 删除群组数据
            await GroupConsole.filter(group_id=group_id).delete()
            return True
        except Exception as e:
            logger.error(f"退群失败：{e}", "ManageService:leave_group")
            return False

    @staticmethod
    async def delete_friend(bot_id: str | None = None, user_id: str | None = None) -> bool:
        """移除好友

        参数:
            bot_id: Bot ID
            user_id: 用户 ID

        返回:
            bool: 是否成功
        """
        try:
            if bot_id:
                bot = nonebot.get_bot(bot_id)
            else:
                bots = nonebot.get_bots()
                if not bots:
                    return False
                bot = list(bots.values())[0]

            if not user_id:
                return False

            await bot.delete_friend(user_id=int(user_id))
            return True
        except Exception as e:
            logger.error(f"移除好友失败：{e}", "ManageService:delete_friend")
            return False

    @staticmethod
    async def rename_group(
        bot_id: str | None = None,
        group_id: str | None = None,
        group_name: str | None = None,
    ) -> bool:
        """修改群名（OneBot set_group_name）

        参数:
            bot_id: Bot ID
            group_id: 群组 ID
            group_name: 新群名

        返回:
            bool: 是否成功
        """
        try:
            if bot_id:
                bot = nonebot.get_bot(bot_id)
            else:
                bots = nonebot.get_bots()
                if not bots:
                    return False
                bot = list(bots.values())[0]

            if not group_id or not group_name:
                return False

            await bot.call_api(
                "set_group_name", group_id=int(group_id), group_name=group_name
            )
            # 同步本地群组数据的群名
            group = await GroupConsole.get_or_none(group_id=group_id)
            if group:
                group.group_name = group_name
                await group.save(update_fields=["group_name"])
            return True
        except Exception as e:
            logger.error(f"修改群名失败：{e}", "ManageService:rename_group")
            return False

    @staticmethod
    async def set_friend_remark(
        bot_id: str | None = None,
        user_id: str | None = None,
        remark: str | None = None,
    ) -> bool:
        """设置好友备注（OneBot 扩展 set_friend_remark，协议端不支持时失败）

        参数:
            bot_id: Bot ID
            user_id: 用户 ID
            remark: 备注内容

        返回:
            bool: 是否成功
        """
        try:
            if bot_id:
                bot = nonebot.get_bot(bot_id)
            else:
                bots = nonebot.get_bots()
                if not bots:
                    return False
                bot = list(bots.values())[0]

            if not user_id:
                return False

            await bot.call_api(
                "set_friend_remark", user_id=int(user_id), remark=remark or ""
            )
            return True
        except Exception as e:
            logger.error(f"设置好友备注失败：{e}", "ManageService:set_friend_remark")
            return False

    @staticmethod
    async def get_group_detail(
        bot_id: str | None = None, group_id: str | None = None
    ) -> GroupDetail | None:
        """获取群组详情

        参数:
            bot_id: Bot ID
            group_id: 群组 ID

        返回:
            GroupDetail | None: 群组详情
        """
        try:
            if not group_id:
                return None

            # 获取群组数据
            group = await GroupConsole.get_or_none(group_id=group_id)
            if not group:
                return None

            # 获取群成员数量
            member_count = 0
            max_member_count = 0
            if bot_id:
                bot = nonebot.get_bot(bot_id)
            else:
                bots = nonebot.get_bots()
                if bots:
                    bot = list(bots.values())[0]
                    group_list, _ = await PlatformUtils.get_group_list(bot)
                    for g in group_list:
                        if str(g.group_id) == group_id:
                            member_count = g.member_count or 0
                            max_member_count = g.max_member_count or 0
                            break

            # 使用 http://p.qlogo.cn 支持 no-referer 防盗链
            ava_url = f"http://p.qlogo.cn/gh/{group_id}/{group_id}/640/"

            return GroupDetail(
                group_id=group_id,
                group_name=group.group_name or "",
                ava_url=ava_url,
                member_count=member_count,
                max_member_count=max_member_count,
                level=group.level,
                status=group.status,
                is_super=group.is_super,
                block_task=bool(group.block_task),
                block_plugin=bool(group.block_plugin),
            )
        except Exception as e:
            logger.error(f"获取群组详情失败：{e}", "ManageService:get_group_detail")
            return None

    @staticmethod
    async def update_group(request) -> bool:
        """更新群组设置

        参数:
            request: UpdateGroupRequest

        返回:
            bool: 是否成功
        """
        try:
            group = await GroupConsole.get_or_none(group_id=request.group_id)
            if not group:
                return False

            update_fields = []
            if request.status is not None:
                group.status = request.status
                update_fields.append("status")
            if request.level is not None:
                group.level = request.level
                update_fields.append("level")
            if request.is_super is not None:
                group.is_super = request.is_super
                update_fields.append("is_super")
            if request.block_task is not None:
                # 获取所有任务模块
                task_modules = await GroupConsole._get_task_modules(default_status=False)
                if request.block_task:
                    # 禁用所有任务
                    group.block_task = convert_module_format(task_modules)
                else:
                    # 启用所有任务
                    group.block_task = ""
                update_fields.append("block_task")
            if request.block_plugin is not None:
                # 获取所有插件模块
                plugin_modules = await GroupConsole._get_plugin_modules(
                    default_status=False
                )
                if request.block_plugin:
                    # 禁用所有插件
                    group.block_plugin = convert_module_format(plugin_modules)
                else:
                    # 启用所有插件
                    group.block_plugin = ""
                update_fields.append("block_plugin")

            if update_fields:
                await group.save(update_fields=update_fields)
            return True
        except Exception as e:
            logger.error(f"更新群组设置失败：{e}", "ManageService:update_group")
            return False

    @staticmethod
    async def get_group_members(
        bot_id: str | None = None, group_id: str | None = None
    ) -> list[GroupMember]:
        """获取群成员列表

        参数:
            bot_id: Bot ID
            group_id: 群组 ID

        返回:
            list[GroupMember]: 群成员列表
        """
        try:
            if not group_id:
                return []

            if bot_id:
                bot = nonebot.get_bot(bot_id)
            else:
                bots = nonebot.get_bots()
                if not bots:
                    return []
                bot = list(bots.values())[0]

            # 获取群成员列表

            #目前仅支持onebot11
            #这个为onebot12的目前无法用 member_list = await bot.get_group_member_list(group_id=int(group_id))
            member_list = await bot.call_api(
        "get_group_member_list",
        group_id=group_id
    )
            result = []
            for m in member_list:
                user_id = str(m.get("user_id", ""))
                result.append(
                    GroupMember(
                        user_id=user_id,
                        nickname=m.get("nickname", ""),
                        remark=m.get("card", "") or m.get("nickname", ""),
                        # 调试模拟端会给成员带上自定义头像（dataURL），优先使用
                        ava_url=m.get("avatar")
                        or f"http://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640",
                        role=m.get("role", "member"),
                    )
                )
            return result
        except Exception as e:
            logger.error(f"获取群成员列表失败：{e}", "ManageService:get_group_members")
            return []

    @staticmethod
    async def get_member_detail(
            group_id: str | None = None,
            user_id: str | None = None
    ) -> MemberDetail | None:
        """获取成员详情（以 friend_detail 风格为准）"""
        try:
            if not group_id or not user_id:
                return None

            # =========================
            # 1️⃣ 获取群成员列表（核心：替代 ORM 查询）
            # =========================
            bot = nonebot.get_bot()

            member_list, _ = await PlatformUtils.get_friend_list(bot)

            member = next(
                (x for x in member_list if x.user_id == user_id),
                None
            )

            if not member:
                return None

            # =========================
            # 2️⃣ 基础信息（按他逻辑）
            # =========================
            nickname = getattr(member, "user_name", "") or ""
            print(nickname)

            ava_url = f"http://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"

            # =========================
            # 3️⃣ 好感度 / 权限
            # =========================
            favorability = await LevelUser.get_user_level(user_id, group_id)

            # =========================
            # 4️⃣ ban 状态
            # =========================
            is_banned = await BanConsole.is_ban(user_id)


            # =========================
            # 6️⃣ 返回（保持你的结构）
            # =========================
            return MemberDetail(
                user_id=user_id,
                nickname=nickname,
                remark="",
                ava_url=ava_url,

                gold=0,  # 兜底（如果你后面有金币系统可以替换）

                favorability=favorability,
                is_banned=is_banned,
            )

        except Exception as e:
            logger.error(f"获取成员详情失败：{e}", "ManageService:get_member_detail")
            return None

    @staticmethod
    async def update_member(request) -> bool:
        """更新成员数据

        参数:
            request: UpdateMemberRequest

        返回:
            bool: 是否成功
        """
        try:
            db_group = await GroupConsole.get_group_db(request.group_id) or GroupConsole(
                group_id=request.group_id
            )

            if request.level is not None:
                db_group.level = request.level
            if request.status is not None:
                db_group.status = request.status

                await db_group.save()
            return True
        except Exception as e:
            logger.error(f"更新成员数据失败：{e}", "ManageService:update_member")
            return False

    @staticmethod
    async def get_group_plugins(group_id: str | None = None) -> list[dict]:
        """获取群功能开关列表（修复版：对齐标准逻辑）"""
        try:
            if not group_id:
                return []

            group = await GroupConsole.get_or_none(group_id=group_id)
            if not group:
                return []

            # =========================
            # 1️⃣ 获取插件 + name 映射（标准逻辑）
            # =========================
            from zhenxun.models.plugin_info import PluginInfo
            from zhenxun.utils.enum import PluginType

            plugins = await PluginInfo.all()
            module2name = {p.module: p.name for p in plugins}

            # =========================
            # 2️⃣ 正确解析 block plugin
            # =========================
            block_plugin = set(
                CommonUtils.convert_module_format(group.block_plugin or "")
            )

            super_block_plugin = set(
                CommonUtils.convert_module_format(group.superuser_block_plugin or "")
            )

            # =========================
            # 3️⃣ plugin 列表（normal + dependant）
            # =========================
            normal_plugins = await PluginInfo.filter(
                plugin_type__in=[PluginType.NORMAL, PluginType.DEPENDANT]
            ).all()

            result = []

            # =========================
            # 4️⃣ 插件部分（对齐别人逻辑）
            # =========================
            for p in normal_plugins:
                module = p.module

                # super block 优先级更高
                is_blocked = module in block_plugin or module in super_block_plugin

                result.append({
                    "module": module,
                    "plugin_name": module2name.get(module) or p.name,
                    "is_blocked": is_blocked,
                    "is_task": False,
                })

            # =========================
            # 5️⃣ task 部分（保持你原结构）
            # =========================
            from zhenxun.models.task_info import TaskInfo

            tasks = await TaskInfo.all()

            task_block_set = set(
                CommonUtils.convert_module_format(group.block_task or "")
            )

            for t in tasks:
                module = t.module

                is_blocked = module in task_block_set

                result.append({
                    "module": module,
                    "plugin_name": t.name,
                    "is_blocked": is_blocked,
                    "is_task": True,
                })

            return result

        except Exception as e:
            logger.error(f"获取群功能开关列表失败：{e}", "ManageService:get_group_plugins")
            return []

    @staticmethod
    async def toggle_group_plugin(request) -> dict:
        """群插件开关（支持 is_task 分类的增量模型）"""
        try:
            db_group = await GroupConsole.get_group_db(request.group_id)
            if not db_group:
                db_group = GroupConsole(group_id=request.group_id)

            module = request.module
            is_task = request.is_task

            # =========================
            # 1️⃣ 选择目标字段
            # =========================
            if is_task:
                current_block = CommonUtils.convert_module_format(
                    db_group.block_task or ""
                ) or []
            else:
                current_block = CommonUtils.convert_module_format(
                    db_group.block_plugin or ""
                ) or []

            # =========================
            # 2️⃣ toggle 逻辑（不变）
            # =========================
            if module in current_block:
                current_block.remove(module)
            else:
                current_block.append(module)

            # =========================
            # 3️⃣ 写回对应字段
            # =========================
            if is_task:
                db_group.block_task = CommonUtils.convert_module_format(current_block)
            else:
                db_group.block_plugin = CommonUtils.convert_module_format(current_block)

            await db_group.save()

            return {
                "success": True,
                "data": {
                    "group_id": request.group_id,
                    "module": module,
                    "is_task": is_task,
                    "is_blocked": module in current_block,
                    "block_list": current_block,
                },
                "message": "ok",
            }

        except Exception as e:
            logger.error(f"切换群插件失败：{e}", "ManageService:toggle_group_plugin")
            return {
                "success": False,
                "data": None,
                "message": str(e),
            }

    @staticmethod
    async def get_group_statistics(
        bot_id: str | None = None, group_id: str | None = None
    ) -> GroupStatistics | None:
        """获取群数据统计

        参数:
            bot_id: Bot ID
            group_id: 群组 ID

        返回:
            GroupStatistics | None: 统计数据
        """
        try:
            if not group_id:
                return None

            group = await GroupConsole.get_or_none(group_id=group_id)
            if not group:
                return None

            # 这里需要从数据库获取发言统计和插件调用统计
            # 简化实现，返回默认值
            return GroupStatistics(
                group_id=group_id,
                group_name=group.group_name or "",
                chat_count=0,
                call_count=0,
                member_count=0,
                active_members=0,
            )
        except Exception as e:
            logger.error(f"获取群数据统计失败：{e}", "ManageService:get_group_statistics")
            return None

    @staticmethod
    async def get_request_list(bot_id: str | None = None) -> dict:
        """获取请求列表

        参数:
            bot_id: Bot ID

        返回:
            dict: 包含 friend 和 group 请求列表的字典
        """
        try:
            # 获取未处理的好友请求
            friend_requests = await FgRequest.filter(
                request_type=RequestType.FRIEND,
                handle_type__isnull=True
            ).order_by("-id")

            # 获取未处理的群请求
            group_requests = await FgRequest.filter(
                request_type=RequestType.GROUP,
                handle_type__isnull=True
            ).order_by("-id")

            friend_result = []
            for req in friend_requests:
                if bot_id and req.bot_id != bot_id:
                    continue
                ava_url = f"http://q1.qlogo.cn/g?b=qq&nk={req.user_id}&s=640"
                friend_result.append(
                    FriendRequestResult(
                        bot_id=req.bot_id,
                        oid=req.id,
                        id=str(req.user_id),
                        flag=req.flag,
                        nickname=req.nickname,
                        comment=req.comment,
                        ava_url=ava_url,
                        type="friend",
                    )
                )

            group_result = []
            for req in group_requests:
                if bot_id and req.bot_id != bot_id:
                    continue
                ava_url = f"http://q1.qlogo.cn/g?b=qq&nk={req.user_id}&s=640"
                group_result.append(
                    GroupRequestResult(
                        bot_id=req.bot_id,
                        oid=req.id,
                        id=str(req.user_id),
                        flag=req.flag,
                        nickname=req.nickname,
                        comment=req.comment,
                        ava_url=ava_url,
                        type="group",
                        invite_group=req.group_id or "",
                        group_name=None,
                    )
                )

            return {"friend": friend_result, "group": group_result}
        except Exception as e:
            logger.error(f"获取请求列表失败：{e}", "ManageService:get_request_list")
            return {"friend": [], "group": []}

    @staticmethod
    async def handle_request(
        bot_id: str | None = None,
        request_id: int | None = None,
        action: str = "approve"
    ) -> bool:
        """处理请求

        参数:
            bot_id: Bot ID
            request_id: 请求 ID
            action: 操作类型 (approve/refused/ignore)

        返回:
            bool: 是否成功
        """
        try:
            if not request_id:
                return False

            req = await FgRequest.get_or_none(id=request_id)
            if not req:
                return False

            if bot_id and req.bot_id != bot_id:
                return False

            # 获取 bot
            if bot_id:
                bot = nonebot.get_bot(bot_id)
            else:
                bots = nonebot.get_bots()
                if not bots:
                    return False
                bot = list(bots.values())[0]

            # 根据操作类型处理
            if action == "approve":
                await FgRequest.approve(bot, request_id)
            elif action == "refused":
                await FgRequest.refused(bot, request_id)
            elif action == "ignore":
                await FgRequest.ignore(request_id)
            else:
                return False

            return True
        except Exception as e:
            logger.error(f"处理请求失败：{e}", "ManageService:handle_request")
            return False

    @staticmethod
    async def clear_request(request_type: str) -> bool:
        """清空请求

        参数:
            request_type: 请求类型 (friend/group)

        返回:
            bool: 是否成功
        """
        try:
            if request_type == "friend":
                await FgRequest.filter(
                    request_type=RequestType.FRIEND,
                    handle_type__isnull=True
                ).update(handle_type=RequestHandleType.EXPIRE)
            elif request_type == "group":
                await FgRequest.filter(
                    request_type=RequestType.GROUP,
                    handle_type__isnull=True
                ).update(handle_type=RequestHandleType.EXPIRE)
            else:
                return False
            return True
        except Exception as e:
            logger.error(f"清空请求失败：{e}", "ManageService:clear_request")
            return False

    @staticmethod
    async def get_friend_detail(user_id: str | None = None,bot_id: str | None = None,) -> FriendDetail | None:
        """获取好友详情

        参数:
            user_id: 用户 ID

        返回:
            FriendDetail | None: 好友详情
        """
        try:
            if not user_id:
                return None
            if not bot_id:
                return None

            bot = nonebot.get_bot(bot_id)
            friend_list, _ = await PlatformUtils.get_friend_list(bot)
            fd = [x for x in friend_list if x.user_id == user_id]
            if not fd:
                return None

            # 获取用户信息
            user_console = await UserConsole.get_or_none(user_id=user_id)


            # 获取签到数据（好感度）
            sign_user = await SignUser.get_or_none(user_id=user_id)

            # 构建头像 URL
            ava_url = f"http://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"
            user = fd[0]

            return FriendDetail(
                user_id=user_id,
                nickname=user.user_name,
                ava_url=ava_url,
                gold=user_console.gold if user_console else 0,
                favorability=float(sign_user.impression) if sign_user else 0.0,
            )
        except Exception as e:
            logger.error(f"获取好友详情失败：{e}", "ManageService:get_friend_detail")
            return None

    @staticmethod
    async def update_friend(request) -> bool:
        """更新好友数据

        参数:
            request: UpdateFriendRequest

        返回:
            bool: 是否成功
        """
        try:
            user_id = request.user_id

            # 更新金币
            if request.gold is not None:
                user_console = await UserConsole.get_user(user_id)
                current_gold = user_console.gold
                diff = request.gold - current_gold
                if diff > 0:
                    await UserConsole.add_gold(user_id, diff, "web_ui_edit")
                elif diff < 0:
                    from zhenxun.utils.enum import GoldHandle
                    await UserConsole.reduce_gold(
                        user_id, abs(diff), GoldHandle.PLUGIN, "web_ui_edit"
                    )

            # 更新好感度
            if request.favorability is not None:
                sign_user = await SignUser.get_user(user_id)
                sign_user.impression = request.favorability
                await sign_user.save(update_fields=["impression"])

            return True
        except Exception as e:
            logger.error(f"更新好友数据失败：{e}", "ManageService:update_friend")
            return False

    @staticmethod
    async def get_friend_trend(
        user_id: str | None = None, days: int = 7
    ) -> FriendTrend:
        """获取好友趋势数据

        参数:
            user_id: 用户 ID
            days: 天数

        返回:
            FriendTrend: 趋势数据
        """
        try:
            if not user_id:
                return FriendTrend()

            end_time = datetime.now()
            start_time = end_time - timedelta(days=days)

            data_points = []
            total_chat = 0
            total_call = 0

            for i in range(days):
                day_start = start_time + timedelta(days=i)
                day_end = day_start + timedelta(days=1)

                # 查询私聊消息数（group_id 为空）
                chat_count = await ChatHistory.filter(
                    user_id=user_id,
                    group_id__isnull=True,
                    create_time__gte=day_start,
                    create_time__lt=day_end,
                ).count()

                # 查询私聊插件调用数
                call_count = await Statistics.filter(
                    user_id=user_id,
                    group_id__isnull=True,
                    create_time__gte=day_start,
                    create_time__lt=day_end,
                ).count()

                data_points.append(
                    FriendTrendPoint(
                        date=day_start.strftime("%m-%d"),
                        chat_count=chat_count,
                        call_count=call_count,
                    )
                )

                total_chat += chat_count
                total_call += call_count

            return FriendTrend(
                data=data_points,
                total_chat=total_chat,
                total_call=total_call,
            )
        except Exception as e:
            logger.error(f"获取好友趋势失败：{e}", "ManageService:get_friend_trend")
            return FriendTrend()
