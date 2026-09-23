"""调试模拟服务：管理 OneBot 模拟客户端的进程级单例"""
from __future__ import annotations

import asyncio
from typing import Any

from .simulator import OneBotV11Simulator, SimFriend, SimGroup, SimMember

# 默认世界状态：没有前端指令时也可用，保证模拟客户端开箱即用
_DEFAULT_STATE: dict[str, Any] = {
    "friends": [
        {"user_id": 10000, "nickname": "模拟好友一号", "remark": "一号"},
        {"user_id": 10001, "nickname": "模拟好友二号", "remark": ""},
    ],
    "groups": [
        {"group_id": 70000, "group_name": "模拟群一号", "member_count": 2, "max_member_count": 200},
        {"group_id": 70001, "group_name": "模拟群二号", "member_count": 1, "max_member_count": 500},
    ],
    "members": {
        70000: [
            {"user_id": 10000, "nickname": "模拟好友一号", "card": "一号", "role": "owner"},
            {"user_id": 10001, "nickname": "模拟好友二号", "card": "", "role": "member"},
        ],
        70001: [
            {"user_id": 10000, "nickname": "模拟好友一号", "card": "群主", "role": "owner"},
        ],
    },
}


class DebugSimulatorManager:
    """管理模拟客户端的进程级单例，供 WebSocket 路由和群聊管理调用"""

    _instance: OneBotV11Simulator | None = None
    _frontend_clients: set = set()  # 前端 WS 连接集合（broadcast 用）
    _loop: Any = None

    @classmethod
    def get(cls) -> OneBotV11Simulator | None:
        return cls._instance

    @classmethod
    def create(
        cls,
        url: str,
        self_id: str,
        access_token: str | None = None,
        heartbeat_interval: int = 30,
        on_action: Any = None,
        on_bot_message: Any = None,
        on_state: Any = None,
    ) -> OneBotV11Simulator:
        cls._instance = OneBotV11Simulator(
            url=url,
            self_id=self_id,
            access_token=access_token,
            heartbeat_interval=heartbeat_interval,
            on_action=on_action,
            on_bot_message=on_bot_message,
            on_state=on_state,
        )
        # 世界状态默认预置，否则 get_group_list 等应答是空的，页面没法交互
        cls._instance.state.friends = [SimFriend(**f) for f in _DEFAULT_STATE["friends"]]
        cls._instance.state.groups = [SimGroup(**g) for g in _DEFAULT_STATE["groups"]]
        cls._instance.state.members = {
            gid: [SimMember(**m) for m in members]
            for gid, members in _DEFAULT_STATE["members"].items()
        }
        return cls._instance

    @classmethod
    async def shutdown(cls) -> None:
        if cls._instance:
            try:
                await cls._instance.disconnect()
            except Exception:
                pass
            cls._instance = None

    @classmethod
    def broadcast_to_frontend(cls, packet: dict) -> None:
        """把 UI 事件广播给所有已连接的前端 WebSocket

        连接已断开的目标静默从广播集合里移除，发送失败不抛错
        （异步任务通过回调回收，不产生 "Task exception was never retrieved"）
        """
        import json

        text = json.dumps(packet, ensure_ascii=False)
        loop = cls._loop
        if not loop or loop.is_closed():
            return

        dead = set()

        for ws in cls._frontend_clients:

            async def _send_one(target_ws, payload: str) -> None:
                try:
                    await target_ws.send_text(payload)
                except Exception:
                    dead.add(target_ws)

            try:
                task = loop.create_task(_send_one(ws, text))

                def _reap(t: Any, ws: Any = ws) -> None:
                    # 异常必须被消费，否则会报 "Task exception was never retrieved"
                    try:
                        t.exception()
                    except asyncio.CancelledError:
                        pass

                task.add_done_callback(_reap)
            except Exception:
                dead.add(ws)

        cls._frontend_clients -= dead

    @classmethod
    def register_frontend(cls, ws: Any, loop: Any) -> None:
        cls._frontend_clients.add(ws)
        cls._loop = loop

    @classmethod
    def unregister_frontend(cls, ws: Any) -> None:
        cls._frontend_clients.discard(ws)

    # ==================== 世界状态操作 ====================

    @classmethod
    def add_friend(cls, user_id: int, nickname: str) -> None:
        sim = cls._instance
        if not sim:
            return
        if any(f.user_id == user_id for f in sim.state.friends):
            return
        sim.state.friends.append(SimFriend(user_id=user_id, nickname=nickname))

    @classmethod
    def add_group(cls, group_id: int, group_name: str) -> None:
        sim = cls._instance
        if not sim:
            return
        if any(g.group_id == group_id for g in sim.state.groups):
            return
        sim.state.groups.append(
            SimGroup(group_id=group_id, group_name=group_name)
        )

    @classmethod
    def add_group_member(
        cls, group_id: int, user_id: int, nickname: str, role: str = "member"
    ) -> None:
        sim = cls._instance
        if not sim:
            return
        members = sim.state.members.setdefault(group_id, [])
        if any(m.user_id == user_id for m in members):
            return
        members.append(
            SimMember(user_id=user_id, nickname=nickname, role=role)
        )
        group = next((g for g in sim.state.groups if g.group_id == group_id), None)
        if group:
            group.member_count = len(members)

    @classmethod
    def remove_group_member(cls, group_id: int, user_id: int) -> None:
        sim = cls._instance
        if not sim:
            return
        members = sim.state.members.get(group_id, [])
        sim.state.members[group_id] = [
            m for m in members if m.user_id != user_id
        ]
        group = next((g for g in sim.state.groups if g.group_id == group_id), None)
        if group:
            group.member_count = len(sim.state.members[group_id])

    @classmethod
    def remove_group(cls, group_id: int) -> None:
        sim = cls._instance
        if not sim:
            return
        sim.state.groups = [
            g for g in sim.state.groups if g.group_id != group_id
        ]
        sim.state.members.pop(group_id, None)

    @classmethod
    def snapshot_state(cls) -> dict:
        """当前模拟世界状态，供前端同步展示"""
        sim = cls._instance
        if not sim:
            return {"friends": [], "groups": []}
        return {
            "friends": [
                {"user_id": f.user_id, "nickname": f.nickname, "remark": f.remark}
                for f in sim.state.friends
            ],
            "groups": [
                {
                    "group_id": g.group_id,
                    "group_name": g.group_name,
                    "member_count": g.member_count,
                    "max_member_count": g.max_member_count,
                    "members": [
                        {
                            "user_id": m.user_id,
                            "nickname": m.nickname,
                            "card": m.card,
                            "role": m.role,
                        }
                        for m in sim.state.members.get(g.group_id, [])
                    ],
                }
                for g in sim.state.groups
            ],
        }
