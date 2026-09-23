"""WebSocket 路由"""
import asyncio
from datetime import datetime
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from nonebot import get_driver, on_message
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.message import event_preprocessor
from nonebot_plugin_alconna import (
    At,
    AtAll,
    Audio,
    Emoji,
    File,
    Hyper,
    Image,
    Reference,
    RefNode,
    Reply,
    Text,
    UniMsg,
    Video,
    Voice,
)
from nonebot_plugin_uninfo import Uninfo
from starlette.websockets import WebSocketState

from zhenxun.models.group_member_info import GroupInfoUser
from zhenxun.services.log import logger
from zhenxun.utils.depends import UserName

from ..dependencies import authenticate_websocket
from ..services.log_service import LOG_STORAGE

router = APIRouter()

ws_log_router = APIRouter(prefix="/logs", tags=["WebSocket 日志"])
ws_status_router = APIRouter(prefix="/status", tags=["WebSocket 状态"])
ws_chat_router = APIRouter(prefix="/chat", tags=["WebSocket 聊天"])


@ws_log_router.websocket("")
async def logs_realtime(websocket: WebSocket):
    """实时日志 WebSocket

    订阅系统日志实时推送。
    """
    if not await authenticate_websocket(websocket):
        return
    await websocket.accept()
    queue = LOG_STORAGE.subscribe()

    try:
        # 只在连接时发送一次历史日志
        logs = LOG_STORAGE.get_logs(limit=50)
        for log in logs:
            await websocket.send_json(log)

        # 持续接收新日志
        while websocket.client_state == WebSocketState.CONNECTED:
            try:
                log_entry = await asyncio.wait_for(queue.get(), timeout=30)
                await websocket.send_json(log_entry)
            except asyncio.TimeoutError:
                # 发送心跳
                await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        logger.debug("日志 WebSocket 连接断开")
    except Exception as e:
        logger.error(f"日志 WebSocket 错误：{e!s}")
    finally:
        LOG_STORAGE.unsubscribe(queue)
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close()
        except Exception:
            pass


@ws_status_router.websocket("")
async def status_realtime(websocket: WebSocket):
    """实时状态 WebSocket

    推送系统状态信息，以及 bot 上下线事件。
    """
    from ..services.system_service import get_system_status

    if not await authenticate_websocket(websocket):
        return
    await websocket.accept()
    _status_connections.append(websocket)

    try:
        while websocket.client_state == WebSocketState.CONNECTED:
            # 获取系统状态
            status = await get_system_status()
            await websocket.send_json(
                {
                    "type": "status",
                    "data": {
                        "cpu": status.cpu,
                        "memory": status.memory,
                        "disk": status.disk,
                        "check_time": status.check_time.isoformat(),
                    },
                }
            )

            # 等待一段时间
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        logger.debug("状态 WebSocket 连接断开")
    except Exception as e:
        logger.error(f"状态 WebSocket 错误：{e!s}")
    finally:
        if websocket in _status_connections:
            _status_connections.remove(websocket)
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close()
        except Exception:
            pass


# 状态 WS 连接登记：用于 bot 上下线事件广播
_status_connections: list[WebSocket] = []


async def _broadcast_status_event(payload: dict) -> None:
    """向所有状态 WS 连接广播事件（bot 上下线等）"""
    for conn in list(_status_connections):
        try:
            if conn.client_state == WebSocketState.CONNECTED:
                await conn.send_json(payload)
        except Exception:
            pass


# 聊天 WebSocket 相关
_chat_connections: list[WebSocket] = []
_message_cache: dict = {}
MAX_CACHE_SIZE = 100

# 旧项目的聊天 WebSocket 兼容实现
_driver = get_driver()
_ws_chat_conn: WebSocket | None = None
_id2name: dict[str, dict[str, str]] = {}
_id_list: list = []


@_driver.on_bot_connect
async def _on_bot_connect(bot):
    """bot 接入时通知前端刷新 bot 列表（真实协议端与调试模拟端都会触发）"""
    logger.info(f"Bot 接入: {bot.self_id}", "WebUiNext")
    await _broadcast_status_event(
        {"type": "bot_update", "action": "connect", "self_id": str(bot.self_id)}
    )


@_driver.on_bot_disconnect
async def _on_bot_disconnect(bot):
    """bot 断开时通知前端刷新 bot 列表"""
    logger.info(f"Bot 断开: {bot.self_id}", "WebUiNext")
    await _broadcast_status_event(
        {
            "type": "bot_update",
            "action": "disconnect",
            "self_id": str(bot.self_id),
        }
    )


# 好友/群请求观察者：用事件预处理器而非 on_request 匹配器——
# 预处理器在匹配器分发之前运行，不会被其他 handler 的 matcher.stop() 拦截
async def _delayed_request_notify():
    try:
        # 等待 zhenxun 核心把请求落库，前端再拉取才拿得到
        await asyncio.sleep(1)
        await _broadcast_status_event({"type": "request_update"})
    except Exception:
        pass


@event_preprocessor
async def _notify_request_update(bot, event: Event, state):
    try:
        if event.get_type() == "request":
            asyncio.create_task(_delayed_request_notify())
    except Exception:
        pass


async def _delayed_contacts_notify():
    try:
        # 等待相关动作/事件处理完成，前端再拉取才有新数据
        await asyncio.sleep(1)
        await _broadcast_status_event({"type": "contacts_update"})
    except Exception:
        pass


@event_preprocessor
async def _notify_contacts_update(bot, event: Event, state):
    """好友/群组成员变化（真实协议端通过 notice 事件上报）时通知前端刷新"""
    try:
        if event.get_type() == "notice" and getattr(event, "notice_type", "") in (
            "friend_add",
            "group_increase",
            "group_decrease",
        ):
            asyncio.create_task(_delayed_contacts_notify())
    except Exception:
        pass

_chat_matcher = on_message(block=False, priority=1, rule=lambda: bool(_ws_chat_conn))


@_driver.on_shutdown
async def _():
    """关闭 WebSocket 连接"""
    if _ws_chat_conn and _ws_chat_conn.client_state == WebSocketState.CONNECTED:
        await _ws_chat_conn.close()


async def _message_handle(
    message: UniMsg,
    group_id: str | None,
):
    """消息处理（逐段识别并转发，前端按段渲染）"""
    time_str = str(datetime.now().replace(microsecond=0))
    messages = []
    for m in message:
        if isinstance(m, Text | str):
            messages.append({"type": "text", "msg": str(m), "time": time_str})
        elif isinstance(m, Image):
            if m.url:
                messages.append({"type": "image", "msg": m.url, "time": time_str})
        elif isinstance(m, Voice | Audio):
            if m.url:
                messages.append(
                    {"type": "record", "msg": m.url, "time": time_str}
                )
        elif isinstance(m, Video):
            if m.url:
                messages.append(
                    {"type": "video", "msg": m.url, "time": time_str}
                )
        elif isinstance(m, Emoji):
            messages.append(
                {"type": "face", "msg": str(m.id), "time": time_str}
            )
        elif isinstance(m, At):
            if m.target == "0":
                uname = "全体成员"
            elif m.display:
                uname = m.display
            else:
                uname = m.target
                if group_id not in _id2name:
                    _id2name[group_id] = {}
                if m.target in _id2name[group_id]:
                    uname = _id2name[group_id][m.target]
                elif group_user := await GroupInfoUser.get_or_none(
                    user_id=m.target, group_id=group_id
                ):
                    uname = group_user.user_name
                    if m.target not in _id2name[group_id]:
                        _id2name[group_id][m.target] = uname
            messages.append(
                {"type": "at", "msg": f"@{uname}", "qq": m.target, "time": time_str}
            )
        elif isinstance(m, AtAll):
            messages.append(
                {"type": "at", "msg": "@全体成员", "qq": "all", "time": time_str}
            )
        elif isinstance(m, Reply):
            messages.append({"type": "reply", "msg": str(m.id), "time": time_str})
        elif isinstance(m, Reference):
            # 引用消息：取被引用内容的文本部分拼摘要
            summary = ""
            for org in m.origin or []:
                try:
                    summary = "".join(
                        str(seg)
                        for seg in org
                        if seg.__class__.__name__ == "Text"
                    )
                except Exception:
                    pass
                if summary:
                    break
            messages.append(
                {
                    "type": "reply",
                    "msg": f"[引用] {summary}".strip(),
                    "time": time_str,
                }
            )
        elif isinstance(m, Hyper):
            # json / xml 卡片（分享、音乐、小程序等都是这个形态）
            raw = m.raw
            if not raw and m.content:
                try:
                    raw = json.dumps(m.content, ensure_ascii=False)
                except (TypeError, ValueError):
                    pass
            messages.append(
                {
                    "type": m.format if m.format in ("json", "xml") else "json",
                    "msg": raw or "[卡片消息]",
                    "time": time_str,
                }
            )
        elif isinstance(m, File):
            messages.append(
                {"type": "text", "msg": f"[文件:{m.name}]", "time": time_str}
            )
        elif isinstance(m, RefNode):
            # 合并转发消息：给出转发 id，节点内容前端点开再按需拉取
            payload: dict = {
                "type": "forward",
                "msg": str(m.id),
                "time": time_str,
            }
            if m.context:
                try:
                    nodes = json.loads(m.context)
                    if isinstance(nodes, list):
                        payload["count"] = len(nodes)
                except Exception:
                    pass
            messages.append(payload)
        else:
            # 兜底：能转字符串就转，转不了给占位
            fallback = str(m) if str(m) else "[未知消息]"
            messages.append({"type": "text", "msg": fallback, "time": time_str})
    return messages


@_chat_matcher.handle()
async def _(
    message: UniMsg, event: MessageEvent, session: Uninfo, uname: str = UserName()
):
    """监听聊天消息并推送给 WebSocket 客户端"""
    global _ws_chat_conn, _id2name, _id_list

    if _ws_chat_conn and _ws_chat_conn.client_state == WebSocketState.CONNECTED:
        msg_id = event.message_id
        if msg_id in _id_list:
            return
        _id_list.append(msg_id)
        if len(_id_list) > 50:
            _id_list = _id_list[40:]

        # bot 自己发送的回复（如指令响应）也要展示给聊天页；
        # 前端对"自己视角"的重复消息有时间窗去重，WebUI 主动发送的回显不会被重复显示

        gid = session.group.id if session.group else None
        messages = await _message_handle(message, gid)

        from zhenxun.configs.config import Config as gConfig
        ava_url = gConfig.get_config(
            "web-ui", "ava_url", f"http://q1.qlogo.cn/g?b=qq&nk={session.user.id}&s=160"
        )

        data = {
            "object_id": gid or session.user.id,
            "user_id": session.user.id,
            "group_id": gid,
            "message": messages,
            "name": uname,
            "ava_url": (
                ava_url.format(session.user.id)
                if isinstance(ava_url, str)
                else ava_url
            ),
        }
        await _ws_chat_conn.send_json(data)


@ws_chat_router.websocket("")
async def chat_realtime(websocket: WebSocket):
    """实时聊天 WebSocket

    接收和推送聊天消息。
    """
    global _ws_chat_conn

    if not await authenticate_websocket(websocket):
        return
    await websocket.accept()
    _ws_chat_conn = websocket
    _chat_connections.append(websocket)

    try:
        while websocket.client_state == WebSocketState.CONNECTED:
            try:
                data = await asyncio.wait_for(websocket.receive_json(), timeout=0.5)
                # 处理发送消息（只发送到QQ，不广播回前端）
                await _handle_websocket_message(data)
            except asyncio.TimeoutError:
                pass
            except Exception:
                pass
    except WebSocketDisconnect:
        logger.debug("聊天 WebSocket 连接断开")
    except Exception as e:
        logger.error(f"聊天 WebSocket 错误：{e!s}")
    finally:
        _ws_chat_conn = None
        if websocket in _chat_connections:
            _chat_connections.remove(websocket)
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close()
        except Exception:
            pass


async def _handle_send_message(data: dict) -> bool:
    """处理发送消息到 QQ

    参数:
        data: WebSocket 接收的消息数据，包含 self_id, group_id, user_id, message

    返回:
        bool: 是否发送成功
    """
    from ..services.manage_service import ManageService

    try:
        self_id = data.get("self_id")
        group_id = data.get("group_id")
        user_id = data.get("user_id")
        message = data.get("message")

        if not message:
            logger.warning("WebSocket 消息发送失败：消息内容为空")
            return False

        # 调用 ManageService.send_message 发送消息
        result = await ManageService.send_message(
            bot_id=self_id,
            user_id=user_id,
            group_id=group_id,
            message=message,
        )
        return result
    except Exception as e:
        logger.error(f"WebSocket 消息发送失败：{e}", "WebSocket")
        return False


async def _handle_send_forward(data: dict) -> bool:
    """处理合并转发（mode=forward）：把归一节点交给 ManageService 发送"""
    from ..services.manage_service import ManageService

    try:
        return await ManageService.send_forward_messages(
            bot_id=data.get("self_id"),
            user_id=data.get("user_id"),
            group_id=data.get("group_id"),
            nodes=data.get("nodes") or [],
        )
    except Exception as e:
        logger.error(f"WebSocket 合并转发失败：{e}", "WebSocket")
        return False


async def _handle_send_segments(data: dict) -> bool:
    """处理逐条转发的结构化段（mode=segments）：全量段类型交给 ManageService 发送"""
    from ..services.manage_service import ManageService

    try:
        return await ManageService.send_segments(
            bot_id=data.get("self_id"),
            user_id=data.get("user_id"),
            group_id=data.get("group_id"),
            segments=data.get("segments") or [],
        )
    except Exception as e:
        logger.error(f"WebSocket 分段发送失败：{e}", "WebSocket")
        return False


async def _handle_websocket_message(data: dict):
    """处理 WebSocket 接收的消息

    只发送到 QQ，不广播回 WebSocket（前端已经本地显示）
    """
    mode = data.get("mode")
    if mode == "forward":
        await _handle_send_forward(data)
        return
    if mode == "segments":
        await _handle_send_segments(data)
        return
    await _handle_send_message(data)
