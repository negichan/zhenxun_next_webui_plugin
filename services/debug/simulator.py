"""OneBot v11 模拟客户端（后端进程内实现）

职责：
- 反向 WS 连上 nonebot 的 /onebot/v11/ws（带 X-Self-ID / Authorization 头）
- 连接后推送 lifecycle，按配置心跳
- 应答框架下发的动作请求（get_login_info / get_group_list / send_msg 等）
- 暴露 send_event 供上层把消息事件推给真寻

消息内容（真寻的回复、发来的动作）通过回调交给 WebSocket 路由层展示。
世界状态（好友/群/成员）在 SimState 里维护，页面可调增删。
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import websockets

from zhenxun.services.log import logger

ONEBOT_WS_PATH = "/onebot/v11/ws"


def _now() -> int:
    return int(time.time())


def _message_id_seq() -> int:
    # 消息 id 用时间戳 + 随机后缀，避免与真实 id 撞车
    _message_id_seq.counter = getattr(_message_id_seq, "counter", 0) + 1
    return _message_id_seq.counter


@dataclass
class SimFriend:
    user_id: int
    nickname: str
    remark: str = ""


@dataclass
class SimGroup:
    group_id: int
    group_name: str
    member_count: int = 0
    max_member_count: int = 200


@dataclass
class SimMember:
    user_id: int
    nickname: str
    card: str = ""
    role: str = "member"  # owner / admin / member


@dataclass
class SimState:
    """模拟世界状态：页面可编辑，action 应答从这里取数"""

    friends: list[SimFriend] = field(default_factory=list)
    groups: list[SimGroup] = field(default_factory=list)
    members: dict[int, list[SimMember]] = field(default_factory=dict)

    # 模拟客户端发出去的消息（send_msg 应答后记录，供 get_msg 查询）
    sent_messages: dict[int, dict] = field(default_factory=dict)


class OneBotV11Simulator:
    """OneBot v11 模拟客户端（进程内运行）"""

    def __init__(
        self,
        url: str,
        self_id: str,
        access_token: str | None = None,
        heartbeat_interval: int = 30,
        on_action: Callable[[str, dict], None] | None = None,
        on_bot_message: Callable[[dict], None] | None = None,
        on_state: Callable[[bool], None] | None = None,
    ) -> None:
        self.url = url
        self.self_id = self_id
        self.access_token = access_token
        self.heartbeat_interval = heartbeat_interval
        self.on_action = on_action
        self.on_bot_message = on_bot_message
        self.on_state = on_state

        self.state = SimState()
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._recv_task: asyncio.Task | None = None
        self._explicitly_closed = False

    # ==================== 生命周期 ====================

    @property
    def connected(self) -> bool:
        return bool(self._ws and self._ws.state == websockets.protocol.State.OPEN)

    async def connect(self) -> None:
        if self.connected:
            return
        self._explicitly_closed = False

        headers = {"X-Self-ID": self.self_id, "X-Client-Role": "Universal"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        try:
            self._ws = await websockets.connect(
                self.url,
                additional_headers=headers,
                # 真寻的回复可能是图片等大块消息，默认 1MB 限制会断开连接
                max_size=None,
            )
        except TypeError:
            # websockets 旧版用 extra_headers
            self._ws = await websockets.connect(
                self.url, extra_headers=headers, max_size=None
            )
        except Exception as e:
            raise ConnectionError(f"连接 OneBot 端点失败: {e}") from e

        # 连接建立，推送 lifecycle
        await self._send(self._build_lifecycle())
        self._start_heartbeat()
        self._recv_task = asyncio.create_task(self._recv_loop())
        self.on_state and self.on_state(True)

    async def disconnect(self) -> None:
        self._explicitly_closed = True
        self._stop_heartbeat()
        if self._recv_task:
            self._recv_task.cancel()
            self._recv_task = None
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        self.on_state and self.on_state(False)

    async def _recv_loop(self) -> None:
        try:
            assert self._ws is not None
            async for raw in self._ws:
                try:
                    packet = json.loads(raw)
                except Exception:
                    continue
                action = packet.get("action")
                if not action:
                    continue
                self.on_action and self.on_action(action, packet.get("params") or {})
                response = self._handle_action(packet)
                if self.connected:
                    await self._send(response)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"模拟客户端接收异常: {e}", "WebUiNext")
        finally:
            self.on_state and self.on_state(False)

    async def _send(self, packet: dict) -> bool:
        if not self.connected or not self._ws:
            return False
        try:
            await self._ws.send(json.dumps(packet, ensure_ascii=False))
            return True
        except Exception:
            return False

    def _start_heartbeat(self) -> None:
        self._stop_heartbeat()

        async def _loop():
            while True:
                await asyncio.sleep(max(1, self.heartbeat_interval))
                if not self.connected:
                    break
                await self._send(self._build_heartbeat())

        self._heartbeat_task = asyncio.create_task(_loop())

    def _stop_heartbeat(self) -> None:
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

    # ==================== 事件构造 ====================

    def _build_lifecycle(self) -> dict:
        return {
            "post_type": "meta_event",
            "meta_event_type": "lifecycle",
            "sub_type": "connect",
            "time": _now(),
            "self_id": int(self.self_id),
        }

    def _build_heartbeat(self) -> dict:
        return {
            "post_type": "meta_event",
            "meta_event_type": "heartbeat",
            "status": {"online": True, "good": True},
            "interval": self.heartbeat_interval,
            "time": _now(),
            "self_id": int(self.self_id),
        }

    async def send_private_message(
        self,
        user_id: int,
        nickname: str,
        message: list[dict] | str,
    ) -> bool:
        """以"我的身份"向模拟 bot 发送私聊消息事件"""
        event = {
            "post_type": "message",
            "message_type": "private",
            "sub_type": "friend",
            "message_id": _message_id_seq(),
            "user_id": int(user_id),
            "message": message,
            "raw_message": self._raw_text(message),
            "font": 0,
            "sender": {
                "user_id": int(user_id),
                "nickname": nickname,
                "sex": "unknown",
                "age": 0,
            },
            "time": _now(),
            "self_id": int(self.self_id),
        }
        return await self._send(event)

    async def send_group_message(
        self,
        group_id: int,
        user_id: int,
        nickname: str,
        card: str,
        message: list[dict] | str,
    ) -> bool:
        """以"我的身份"在模拟群里发消息事件"""
        event = {
            "post_type": "message",
            "message_type": "group",
            "sub_type": "normal",
            "message_id": _message_id_seq(),
            "group_id": int(group_id),
            "user_id": int(user_id),
            "message": message,
            "raw_message": self._raw_text(message),
            "font": 0,
            "sender": {
                "user_id": int(user_id),
                "nickname": nickname,
                "card": card or nickname,
                "sex": "unknown",
                "age": 0,
                "area": "",
                "role": "member",
            },
            "time": _now(),
            "self_id": int(self.self_id),
        }
        return await self._send(event)

    @staticmethod
    def _raw_text(message: list[dict] | str) -> str:
        if isinstance(message, str):
            return message
        parts: list[str] = []
        for seg in message:
            t = seg.get("type")
            d = seg.get("data") or {}
            if t == "text":
                parts.append(str(d.get("text", "")))
            elif t == "at":
                parts.append(f"@{d.get('qq', '')}")
            elif t == "face":
                parts.append(f"[表情{d.get('id', '')}]")
            elif t == "image":
                parts.append(f"[图片:{d.get('url') or d.get('file', '')}]")
            elif t == "reply":
                parts.append(f"[回复{d.get('id', '')}]")
            elif t == "record":
                parts.append("[语音]")
            elif t == "video":
                parts.append("[视频]")
            elif t == "json":
                parts.append(f"[JSON:{d.get('data', '')}]")
            else:
                parts.append(f"[{t}]")
        return "".join(parts)

    # ==================== 动作应答 ====================

    def _handle_action(self, packet: dict) -> dict:
        action = packet.get("action", "").replace("_async", "")
        params = packet.get("params") or {}
        echo = packet.get("echo")
        ok = lambda data: self._ok(data, echo)
        fail = lambda msg: self._fail(msg, echo)

        match action:
            # ---------- 消息 ----------
            case "send_msg" | "send_private_msg" | "send_group_msg":
                message_type = params.get("message_type") or (
                    "group" if params.get("group_id") else "private"
                )
                self.on_bot_message and self.on_bot_message(
                    {
                        "message_type": message_type,
                        "user_id": params.get("user_id"),
                        "group_id": params.get("group_id"),
                        "message": params.get("message"),
                        "text": self._raw_text(params.get("message") or ""),
                    }
                )
                message_id = self._record_sent(
                    message_type=message_type,
                    user_id=params.get("user_id"),
                    group_id=params.get("group_id"),
                    message=params.get("message"),
                )
                return ok({"message_id": message_id})

            case "send_private_forward_msg" | "send_group_forward_msg":
                self.on_bot_message and self.on_bot_message(
                    {
                        "message_type": (
                            "group"
                            if action == "send_group_forward_msg"
                            else "private"
                        ),
                        "user_id": params.get("user_id"),
                        "group_id": params.get("group_id"),
                        "message": "[合并转发消息]",
                        "text": "[合并转发消息]",
                    }
                )
                return ok(
                    {
                        "message_id": self._record_sent(
                            message_type="group",
                            message=params.get("messages"),
                        )
                    }
                )

            case "delete_msg":
                self.state.sent_messages.pop(int(params.get("message_id", 0)), None)
                return ok(None)

            case "get_msg":
                sent = self.state.sent_messages.get(int(params.get("message_id", 0)))
                if not sent:
                    return fail(f"消息不存在: {params.get('message_id')}")
                return ok(sent)

            case "get_forward_msg":
                return ok({"messages": []})

            case "send_like" | "mark_msg_as_read" | "set_msg_emoji_like":
                return ok(None)

            # ---------- 群操作 ----------
            case (
                "set_group_kick"
                | "set_group_ban"
                | "set_group_anonymous_ban"
                | "set_group_whole_ban"
                | "set_group_admin"
                | "set_group_anonymous"
                | "set_group_card"
                | "set_group_name"
                | "set_group_leave"
                | "set_group_special_title"
                | "send_group_sign"
            ):
                return ok(None)

            case "get_group_info" | "get_group_info_ex":
                group = self._find_group(params.get("group_id"))
                if not group:
                    return fail(f"群不存在: {params.get('group_id')}")
                return ok(self._group_to_dict(group))

            case "get_group_list":
                return ok([self._group_to_dict(g) for g in self.state.groups])

            case "get_group_member_info":
                member = self._find_member(params.get("group_id"), params.get("user_id"))
                if not member:
                    return fail(
                        f"群成员不存在: 群{params.get('group_id')} 用户{params.get('user_id')}"
                    )
                return ok(self._member_to_dict(member))

            case "get_group_member_list":
                members = self.state.members.get(int(params.get("group_id", 0)), [])
                return ok([self._member_to_dict(m) for m in members])

            case "get_group_msg_history" | "get_friend_msg_history":
                return ok({"messages": []})

            case "get_essence_msg_list":
                return ok([])

            case "set_essence_msg" | "delete_essence_msg":
                return ok(None)

            # ---------- 好友 / 请求 ----------
            case "set_friend_add_request" | "set_group_add_request":
                return ok(None)

            case "get_stranger_info":
                friend = next(
                    (
                        f
                        for f in self.state.friends
                        if f.user_id == int(params.get("user_id", 0))
                    ),
                    None,
                )
                return ok(
                    {
                        "user_id": friend.user_id if friend else int(params.get("user_id", 0)),
                        "nickname": friend.nickname if friend else f"用户{params.get('user_id', '')}",
                        "sex": "unknown",
                        "age": 0,
                    }
                )

            case "get_friend_list":
                return ok(
                    [
                        {
                            "user_id": f.user_id,
                            "nickname": f.nickname,
                            "remark": f.remark,
                            "sex": "unknown",
                            "age": 0,
                        }
                        for f in self.state.friends
                    ]
                )

            # ---------- 登录 / 版本 / 状态 ----------
            case "get_login_info":
                return ok({"user_id": int(self.self_id), "nickname": "模拟客户端"})

            case "get_version_info" | "get_version_info_ex":
                return ok(
                    {
                        "app_name": "zhenxun-webui-simulator",
                        "app_version": "0.1.0",
                        "protocol_version": "v11",
                    }
                )

            case "get_status":
                return ok({"online": True, "good": True})

            case "can_send_image" | "can_send_record":
                return ok({"yes": True})

            # ---------- 媒体 / 扩展 ----------
            case "get_image":
                return ok(
                    {
                        "size": 1024,
                        "filename": "simulated.png",
                        "url": "https://example.com/simulated.png",
                    }
                )

            case "get_record":
                return ok({"file": params.get("file") or "", "url": "", "base64": ""})

            case "get_online_clients" | "get_word_slices":
                return ok([])

            case "check_url_safely":
                return ok({"level": 1})

            case "set_qq_profile" | "set_diy_online_status":
                return ok(None)

            case "get_latest_events":
                return ok([])

            case "ocr_image" | ".ocr_image":
                return ok({"texts": [], "language": ""})

            case _:
                return fail(f"模拟客户端不支持的动作: {action}")

    def _ok(self, data: Any, echo: str | None) -> dict:
        resp = {"status": "ok", "retcode": 0, "data": data}
        if echo is not None:
            resp["echo"] = echo
        return resp

    def _fail(self, message: str, echo: str | None) -> dict:
        resp = {"status": "failed", "retcode": 1404, "data": None, "message": message}
        if echo is not None:
            resp["echo"] = echo
        return resp

    def _record_sent(
        self,
        message_type: str,
        user_id: int | None = None,
        group_id: int | None = None,
        message: Any = None,
    ) -> int:
        message_id = _message_id_seq()
        self.state.sent_messages[message_id] = {
            "message_id": message_id,
            "real_id": message_id,
            "time": _now(),
            "message_type": message_type,
            "user_id": user_id,
            "group_id": group_id,
            "sender": {"user_id": int(self.self_id), "nickname": "模拟客户端"},
            "message": message,
            "raw_message": self._raw_text(message or ""),
        }
        return message_id

    def _find_group(self, group_id: Any) -> SimGroup | None:
        gid = int(group_id or 0)
        return next((g for g in self.state.groups if g.group_id == gid), None)

    def _find_member(self, group_id: Any, user_id: Any) -> SimMember | None:
        gid = int(group_id or 0)
        uid = int(user_id or 0)
        return next(
            (m for m in self.state.members.get(gid, []) if m.user_id == uid),
            None,
        )

    @staticmethod
    def _group_to_dict(group: SimGroup) -> dict:
        return {
            "group_id": group.group_id,
            "group_name": group.group_name,
            "member_count": group.member_count,
            "max_member_count": group.max_member_count,
        }

    @staticmethod
    def _member_to_dict(member: SimMember) -> dict:
        return {
            "user_id": member.user_id,
            "nickname": member.nickname,
            "card": member.card,
            "sex": "unknown",
            "age": 0,
            "area": "",
            "join_time": _now(),
            "last_sent_time": _now(),
            "level": "",
            "role": member.role,
            "title": "",
        }
