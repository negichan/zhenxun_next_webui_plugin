"""OneBot 模拟客户端桥接 WebSocket

浏览器原生 WebSocket 无法设置 X-Self-ID / Authorization 请求头，
而 nonebot 的 OneBot V11 反向 WS 端点(/onebot/v11/ws)只认请求头，
因此浏览器无法直连。

这里只做一层轻量桥接：
    浏览器 -> /zhenxun/ws/v1/debug/onebot (本端点, 参数走 query)
           -> ws://127.0.0.1:<port>/onebot/v11/ws (本进程, header 补齐)
消息内容原样双向透传，协议逻辑全部在前端完成。

另外：bot 回复（send_msg 动作）不会产生入站事件，聊天页的 on_message
监听器收不到，所以桥接层会把回复动作额外转发给聊天页 WebSocket。
"""
import asyncio
import base64
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

import websockets
from fastapi import APIRouter, WebSocket
from nonebot import get_driver
from pydantic import BaseModel
from starlette.websockets import WebSocketState
from zhenxun.configs.config import BotConfig

from zhenxun.services.log import logger

from ..dependencies import AuthenticatedUser, authenticate_websocket
from ..responses import APIResponse, success_response
from ..services.debug import get_state, save_state
from ..services.debug import chat_store

router = APIRouter(prefix="/debug", tags=["WebSocket 调试"])

ONEBOT_WS_PATH = "/onebot/v11/ws"

# bot 回复里可能带 CQ 码图片
_CQ_IMAGE_RE = re.compile(r"\[CQ:image,[^\]]*?url=([^,\]]+)\]")
_SEND_ACTIONS = {"send_msg", "send_private_msg", "send_group_msg"}
# 会改变好友/群组成员数量的动作，触发前端刷新联系人数据
_CONTACT_ACTIONS = {
    "set_friend_add_request",
    "set_group_add_request",
    "set_group_leave",
    "set_group_kick",
}


async def _notify_contacts_changed() -> None:
    """通知前端好友/群组数据已变化"""
    from . import websocket as ws_router

    try:
        await asyncio.sleep(1)
        await ws_router._broadcast_status_event({"type": "contacts_update"})
    except Exception:
        pass


async def _resolve_image_url(url: str) -> str:
    """把 base64:// 与本地文件路径转成浏览器可显示的 data URL"""
    try:
        if url.startswith("base64://"):
            return f"data:image/png;base64,{url[len('base64://'):]}"
        if url.startswith("file://"):
            raw = unquote(url[len("file://"):])
            path = Path(raw)
            if not path.exists():
                # Windows file:///C:/x 去掉前导斜杠
                path = Path(raw.lstrip("/\\"))
            data = await asyncio.to_thread(path.read_bytes)
            return f"data:image/png;base64,{base64.b64encode(data).decode()}"
    except Exception:
        return url
    return url


async def _segments_to_chat_messages(message, time_str: str) -> list[dict]:
    """把 OneBot 消息（段数组或 CQ 码字符串）转成聊天页的消息格式"""
    messages: list[dict] = []
    if isinstance(message, str):
        idx = 0
        for m in _CQ_IMAGE_RE.finditer(message):
            if m.start() > idx and message[idx : m.start()].strip():
                messages.append(
                    {"type": "text", "msg": message[idx : m.start()], "time": time_str}
                )
            messages.append(
                {
                    "type": "img",
                    "msg": await _resolve_image_url(m.group(1).replace("&amp;", "&")),
                    "time": time_str,
                }
            )
            idx = m.end()
        rest = message[idx:]
        if rest.strip() or not messages:
            messages.append({"type": "text", "msg": rest, "time": time_str})
        return messages

    if isinstance(message, list):
        for seg in message:
            if not isinstance(seg, dict):
                continue
            seg_type = seg.get("type")
            data = seg.get("data") or {}
            if seg_type == "text":
                messages.append(
                    {"type": "text", "msg": str(data.get("text", "")), "time": time_str}
                )
            elif seg_type in ("image", "img"):
                url = data.get("url") or data.get("file") or ""
                if url:
                    messages.append(
                        {
                            "type": "img",
                            "msg": await _resolve_image_url(str(url)),
                            "time": time_str,
                        }
                    )
            elif seg_type == "at":
                messages.append(
                    {"type": "text", "msg": f"@{data.get('qq', '')}", "time": time_str}
                )
    return messages


async def _forward_bot_reply_to_chat(raw: str, self_id: str) -> None:
    """把 bot 的回复动作转发给聊天页 WebSocket

    调试模拟模式下 bot 回复不会产生入站消息事件，聊天页只能从这里拿到
    """
    from . import websocket as ws_router

    try:
        packet = json.loads(raw)
    except Exception:
        return
    if not isinstance(packet, dict) or packet.get("action") not in _SEND_ACTIONS:
        return

    ws = ws_router._ws_chat_conn
    if not ws or ws.client_state != WebSocketState.CONNECTED:
        return

    params = packet.get("params") or {}
    time_str = str(datetime.now().replace(microsecond=0))
    group_id = params.get("group_id")
    user_id = params.get("user_id") or params.get("target_id") or ""
    messages = await _segments_to_chat_messages(params.get("message"), time_str)
    if not messages:
        return

    payload = {
        "object_id": str(group_id) if group_id else str(user_id or self_id),
        "user_id": str(self_id),
        "group_id": str(group_id) if group_id else None,
        "message": messages,
        "name": BotConfig.self_nickname,
        "ava_url": f"http://q1.qlogo.cn/g?b=qq&nk={self_id}&s=160",
    }

    # 聊天记录落库（会话 key 与前端一致：群聊 group:xxx，私聊固定 bot）
    asyncio.create_task(
        chat_store.save_chat_messages(
            self_id,
            f"group:{group_id}" if group_id else "bot",
            [
                {
                    "sender": "bot",
                    "sender_id": str(self_id),
                    "sender_name": BotConfig.self_nickname,
                    "message": messages,
                    "time": time_str,
                    "ts": datetime.now().timestamp() * 1000,
                }
            ],
        )
    )
    try:
        await ws.send_json(payload)
    except Exception:
        pass


def _loopback_url() -> str:
    """构造本进程 OneBot 反向 WS 端点地址"""
    try:
        port = get_driver().config.port or 8080
    except Exception:
        port = 8080
    return f"ws://127.0.0.1:{port}{ONEBOT_WS_PATH}"


# ==================== 多端共享桥接 Hub ====================
# 一个 bot 号只允许一条反向 WS 连接（nonebot 对重复 X-Self-ID 直接拒绝），
# 所以桥接按 self_id 维护一条共享的 OneBot 连接，所有打开调试端的浏览器
# 都挂到这条连接上：下行（OneBot→浏览器）广播给每一端，上行（浏览器→
# OneBot）事件透传、动作响应只转发首个（多端会各自应答同一个请求）


@dataclass
class _BridgeEntry:
    """同一 bot 号的所有浏览器共享的一条 OneBot 连接"""

    onebot: "websockets.WebSocketClientProtocol"
    browsers: set = field(default_factory=set)
    # lifecycle.connect 每条 OneBot 连接只透传一次，避免 bot 重复处理上线事件
    connect_forwarded: bool = False
    # 已转发过响应的 echo（多端对同一动作请求各应答一次，只放行首个）
    replied_echoes: set = field(default_factory=set)


_bridges: dict[str, _BridgeEntry] = {}
_bridges_lock = asyncio.Lock()


async def _broadcast_text(
    entry: _BridgeEntry, text: str, exclude=None
) -> None:
    """把文本包发给所有（可选排除某个）浏览器，并清理失效连接"""
    dead = []
    for ws in list(entry.browsers):
        if ws is exclude:
            continue
        try:
            await ws.send_text(text)
        except Exception:
            dead.append(ws)
    for ws in dead:
        entry.browsers.discard(ws)


async def _upstream_to_onebot(
    entry: _BridgeEntry, sender, raw: str, self_id: str = ""
) -> None:
    """浏览器 → OneBot：动作响应按 echo 去重后透传；消息事件透传的同时
    广播给其他浏览器——OneBot 里用户消息只进框架，多端要看到彼此发的
    消息只能靠桥接层转发"""
    try:
        packet = json.loads(raw)
    except Exception:
        packet = None

    if (
        isinstance(packet, dict)
        and packet.get("post_type") == "message"
    ):
        try:
            peer_text = json.dumps(
                {"type": "bridge_peer_message", "event": packet},
                ensure_ascii=False,
            )
        except Exception:
            peer_text = None
        if peer_text:
            await _broadcast_text(entry, peer_text, exclude=sender)

        # 用户消息落库（会话 key 与前端一致）
        group_id = packet.get("group_id")
        user_id = str(packet.get("user_id") or "")
        time_str = str(datetime.now().replace(microsecond=0))
        msgs = await _segments_to_chat_messages(
            packet.get("message"), time_str
        )
        if msgs and self_id:
            asyncio.create_task(
                chat_store.save_chat_messages(
                    self_id,
                    f"group:{group_id}" if group_id else "bot",
                    [
                        {
                            "sender": "user",
                            "sender_id": user_id,
                            "sender_name": str(
                                (packet.get("sender") or {}).get("nickname")
                                or user_id
                            ),
                            "message": msgs,
                            "time": time_str,
                            "ts": datetime.now().timestamp() * 1000,
                        }
                    ],
                )
            )

    if isinstance(packet, dict) and packet.get("echo") is not None:
        echo = packet["echo"]
        if echo in entry.replied_echoes:
            return
        entry.replied_echoes.add(echo)
        if len(entry.replied_echoes) > 1000:
            entry.replied_echoes.clear()
        await entry.onebot.send(raw)
        return
    if (
        isinstance(packet, dict)
        and packet.get("post_type") == "meta_event"
        and packet.get("meta_event_type") == "lifecycle"
        and not entry.connect_forwarded
    ):
        entry.connect_forwarded = True
    await entry.onebot.send(raw)


async def _onebot_downstream(self_id: str, entry: _BridgeEntry) -> None:
    """OneBot → 浏览器：动作请求广播给每一端，bot 回复转发聊天页只发一次"""
    try:
        async for message in entry.onebot:
            await _broadcast_text(entry, message)
            await _forward_bot_reply_to_chat(message, self_id)
            try:
                packet = json.loads(message)
                if (
                    isinstance(packet, dict)
                    and packet.get("action") in _CONTACT_ACTIONS
                ):
                    asyncio.create_task(_notify_contacts_changed())
            except Exception:
                pass
    except Exception:
        pass
    finally:
        # OneBot 连接断开：清掉注册并断开所有浏览器（前端自动重连后重建共享连接）
        async with _bridges_lock:
            if _bridges.get(self_id) is entry:
                _bridges.pop(self_id)
        for ws in list(entry.browsers):
            try:
                await ws.send_json(
                    {"type": "bridge_error", "message": "OneBot 连接已断开"}
                )
            except Exception:
                pass
            try:
                await ws.close()
            except Exception:
                pass
        logger.info(
            f"OneBot 模拟客户端桥接已断开 self_id={self_id}", "WebUiNext"
        )


# ==================== 模拟世界状态持久化 ====================


class SimStatePayload(BaseModel):
    """调试页提交的模拟世界状态

    my_user_id/bot_id 传 None 表示保留云端原值：身份选择（谁是用户/谁是
    bot）只有新模拟端初次同步时上传，之后各端保持各自的选择互不覆盖
    """

    groups: list = []
    members: dict = {}
    friends: list = []
    users: list = []
    my_user_id: str | None = None
    bot_id: str | None = None


async def _broadcast_state_to_all() -> None:
    """把最新模拟状态推给所有连接中的调试端（跨端实时同步群/成员/好友）"""
    if not _bridges:
        return
    try:
        state = await get_state()
    except Exception:
        return
    try:
        text = json.dumps(
            {"type": "bridge_state", "state": state}, ensure_ascii=False
        )
    except Exception:
        return
    for entry in list(_bridges.values()):
        await _broadcast_text(entry, text)


@router.get("/state", summary="获取调试模拟状态")
async def get_sim_state(user: AuthenticatedUser):
    return success_response(data=await get_state())


@router.get("/chat-history", summary="获取调试端聊天历史")
async def get_debug_chat_history(
    user: AuthenticatedUser,
    self_id: str,
    conversation: str,
    limit: int = 200,
) -> APIResponse[list[dict]]:
    """按会话获取调试端聊天历史（时间正序）"""
    return success_response(
        data=await chat_store.get_chat_history(self_id, conversation, limit)
    )


@router.post("/state", summary="保存调试模拟状态")
async def save_sim_state(
    user: AuthenticatedUser, payload: SimStatePayload
) -> APIResponse[bool]:
    meta: dict | None = None
    if payload.my_user_id is not None or payload.bot_id is not None:
        meta = {}
        if payload.my_user_id is not None:
            meta["my_user_id"] = payload.my_user_id
        if payload.bot_id is not None:
            meta["bot_id"] = payload.bot_id
    result = await save_state(
        payload.groups,
        payload.members,
        payload.friends,
        payload.users,
        meta,
    )
    if result:
        # 任何一端保存了状态，推给所有端刷新本地模拟世界
        await _broadcast_state_to_all()
    return success_response(data=result, message="保存成功")


async def _connect_onebot(url: str, headers: dict) -> "websockets.WebSocketClientProtocol":
    """连接 OneBot 端点，兼容 websockets 新旧版本的 header 参数名"""
    try:
        return await websockets.connect(
            url, additional_headers=headers, max_size=None
        )
    except TypeError:
        return await websockets.connect(
            url, extra_headers=headers, max_size=None
        )


@router.websocket("/onebot")
async def onebot_bridge(websocket: WebSocket):
    """OneBot 模拟客户端桥接（多端共享一条 OneBot 连接）

    Query 参数:
        self_id: 模拟的 bot QQ 号（必填，转为 X-Self-ID 头）
        access_token: OneBot 访问令牌（可选，转为 Authorization 头；仅首个
            接入端生效，共享连接用它建连）
    """
    self_id = websocket.query_params.get("self_id")
    access_token = websocket.query_params.get("access_token")

    # WebUI 登录态鉴权（access_token 是 OneBot 上游令牌，与此无关）
    if not await authenticate_websocket(websocket):
        return

    await websocket.accept()

    if not self_id:
        await websocket.send_json(
            {"type": "bridge_error", "message": "缺少 self_id 参数"}
        )
        await websocket.close(code=1008)
        return

    target = _loopback_url()

    # 检查 + 建连必须在锁内完成，否则两个浏览器同时首连会各建一条，
    # 第二条在 nonebot 端撞 Duplicate X-Self-ID
    async with _bridges_lock:
        entry = _bridges.get(self_id)
        if entry is None:
            headers = {"X-Self-ID": self_id, "X-Client-Role": "Universal"}
            if access_token:
                headers["Authorization"] = f"Bearer {access_token}"
            # 旧连接刚关闭时 nonebot 端注销可能有毫秒级延迟，短暂重试避开
            client = None
            last_err: Exception | None = None
            for _ in range(3):
                try:
                    client = await _connect_onebot(target, headers)
                    break
                except Exception as e:
                    last_err = e
                    await asyncio.sleep(0.4)
            if client is None:
                logger.warning(
                    f"OneBot 桥接连接失败 {target}: {last_err}", "WebUiNext"
                )
                try:
                    await websocket.send_json(
                        {
                            "type": "bridge_error",
                            "message": f"连接 OneBot 端点失败: {last_err}",
                        }
                    )
                except Exception:
                    pass
                await websocket.close()
                return
            entry = _BridgeEntry(onebot=client)
            _bridges[self_id] = entry
            asyncio.create_task(_onebot_downstream(self_id, entry))
            logger.info(
                f"OneBot 模拟客户端桥接已建立 self_id={self_id}", "WebUiNext"
            )
        entry.browsers.add(websocket)

    # 接入即推一份当前状态，让新端打开后立刻拿到最新模拟世界
    try:
        state = await get_state()
        await websocket.send_text(
            json.dumps(
                {"type": "bridge_state", "state": state}, ensure_ascii=False
            )
        )
    except Exception:
        pass

    try:
        while True:
            raw = await websocket.receive_text()
            await _upstream_to_onebot(entry, websocket, raw, self_id)
    except Exception:
        pass
    finally:
        async with _bridges_lock:
            entry.browsers.discard(websocket)
            last = not entry.browsers
            if last and _bridges.get(self_id) is entry:
                _bridges.pop(self_id)
        if last:
            try:
                await entry.onebot.close()
            except Exception:
                pass
