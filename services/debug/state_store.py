"""调试模拟客户端的持久化状态（SQLite）

存放在 zhenxun 的 data/web_ui/debug_sim.db：
- 相比 JSON 文件：写入走原子事务，不会出现写一半文件损坏的问题
- 对外接口仍返回 {groups, members, friends} 字典，前后端无感知
- 首次运行时自动迁移旧的 debug_sim_state.json
"""
import json
import sqlite3
from pathlib import Path
from typing import Any

from nonebot.utils import run_sync
from zhenxun.services.log import logger

DB_FILE = Path().resolve() / "data" / "web_ui" / "debug_sim.db"
_LEGACY_JSON = Path().resolve() / "data" / "web_ui" / "debug_sim_state.json"


def _as_id(value: Any) -> Any:
    """纯数字 id 转回 int，保持与前端 number 类型的比较行为一致"""
    s = str(value)
    return int(s) if s.isdigit() else s


def _connect() -> sqlite3.Connection:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sim_groups (
            group_id TEXT PRIMARY KEY,
            group_name TEXT DEFAULT '',
            member_count INTEGER DEFAULT 0,
            max_member_count INTEGER DEFAULT 0
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sim_members (
            group_id TEXT,
            user_id TEXT,
            nickname TEXT DEFAULT '',
            card TEXT DEFAULT '',
            role TEXT DEFAULT 'member',
            PRIMARY KEY (group_id, user_id)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sim_friends (
            user_id TEXT PRIMARY KEY,
            nickname TEXT DEFAULT '',
            remark TEXT DEFAULT ''
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sim_users (
            user_id TEXT PRIMARY KEY,
            nickname TEXT DEFAULT '',
            avatar TEXT DEFAULT ''
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sim_meta (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        )"""
    )
    conn.commit()
    return conn


def _migrate_legacy_json(conn: sqlite3.Connection) -> None:
    """旧的 debug_sim_state.json 存在且库里为空时，导入一次"""
    try:
        if not _LEGACY_JSON.is_file():
            return
        (total,) = conn.execute("SELECT COUNT(*) FROM sim_groups").fetchone()
        if total:
            return
        data = json.loads(_LEGACY_JSON.read_text(encoding="utf-8"))
        _write_state(
            conn,
            data.get("groups") or [],
            data.get("members") or {},
            data.get("friends") or [],
        )
        logger.info("已从 debug_sim_state.json 迁移调试模拟状态", "WebUiNext")
    except Exception as e:
        logger.warning(f"迁移旧调试状态失败: {e}", "WebUiNext")


def _write_state(
    conn: sqlite3.Connection,
    groups: list,
    members: dict,
    friends: list,
    users: list | None = None,
    meta: dict | None = None,
) -> None:
    conn.execute("DELETE FROM sim_groups")
    conn.execute("DELETE FROM sim_members")
    conn.execute("DELETE FROM sim_friends")
    if users is not None:
        conn.execute("DELETE FROM sim_users")
    if meta is not None:
        conn.execute("DELETE FROM sim_meta")
    for g in groups or []:
        conn.execute(
            "INSERT INTO sim_groups (group_id, group_name, member_count, max_member_count) VALUES (?, ?, ?, ?)",
            (
                str(g.get("group_id")),
                str(g.get("group_name") or ""),
                int(g.get("member_count") or 0),
                int(g.get("max_member_count") or 0),
            ),
        )
    for gid, member_list in (members or {}).items():
        for m in member_list or []:
            conn.execute(
                "INSERT OR REPLACE INTO sim_members (group_id, user_id, nickname, card, role) VALUES (?, ?, ?, ?, ?)",
                (
                    str(gid),
                    str(m.get("user_id")),
                    str(m.get("nickname") or ""),
                    str(m.get("card") or ""),
                    str(m.get("role") or "member"),
                ),
            )
    for f in friends or []:
        conn.execute(
            "INSERT OR REPLACE INTO sim_friends (user_id, nickname, remark) VALUES (?, ?, ?)",
            (
                str(f.get("user_id")),
                str(f.get("nickname") or ""),
                str(f.get("remark") or ""),
            ),
        )
    for u in users or []:
        conn.execute(
            "INSERT OR REPLACE INTO sim_users (user_id, nickname, avatar) VALUES (?, ?, ?)",
            (
                str(u.get("user_id")),
                str(u.get("nickname") or ""),
                str(u.get("avatar") or ""),
            ),
        )
    for key, value in (meta or {}).items():
        conn.execute(
            "INSERT OR REPLACE INTO sim_meta (key, value) VALUES (?, ?)",
            (str(key), str(value)),
        )


@run_sync
def get_state() -> dict[str, Any]:
    """获取调试模拟状态（群聊 + 成员 + 好友）"""
    conn = _connect()
    try:
        _migrate_legacy_json(conn)
        groups = [
            {
                "group_id": _as_id(gid),
                "group_name": group_name,
                "member_count": member_count,
                "max_member_count": max_member_count,
            }
            for gid, group_name, member_count, max_member_count in conn.execute(
                "SELECT group_id, group_name, member_count, max_member_count FROM sim_groups"
            )
        ]
        members: dict[str, list] = {}
        for gid, uid, nickname, card, role in conn.execute(
            "SELECT group_id, user_id, nickname, card, role FROM sim_members"
        ):
            members.setdefault(str(gid), []).append(
                {
                    "user_id": _as_id(uid),
                    "nickname": nickname,
                    "card": card,
                    "role": role,
                }
            )
        friends = [
            {"user_id": _as_id(uid), "nickname": nickname, "remark": remark}
            for uid, nickname, remark in conn.execute(
                "SELECT user_id, nickname, remark FROM sim_friends"
            )
        ]
        users = [
            {"user_id": _as_id(uid), "nickname": nickname, "avatar": avatar}
            for uid, nickname, avatar in conn.execute(
                "SELECT user_id, nickname, avatar FROM sim_users"
            )
        ]
        meta = {
            key: value
            for key, value in conn.execute(
                "SELECT key, value FROM sim_meta"
            )
        }
        return {
            "groups": groups,
            "members": members,
            "friends": friends,
            "users": users,
            "my_user_id": _as_id(meta.get("my_user_id", "")),
            "bot_id": _as_id(meta.get("bot_id", "")),
        }
    finally:
        conn.close()


@run_sync
def save_state(
    groups: list,
    members: dict,
    friends: list | None = None,
    users: list | None = None,
    meta: dict | None = None,
) -> bool:
    """保存调试模拟状态（单事务全量替换；users/meta 为 None 时保留原表）"""
    conn = _connect()
    try:
        _write_state(conn, groups, members, friends, users, meta)
        conn.commit()
        return True
    except Exception as e:
        logger.warning(f"保存调试模拟状态失败: {e}", "WebUiNext")
        return False
    finally:
        conn.close()
