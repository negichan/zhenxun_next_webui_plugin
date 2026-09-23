"""调试端聊天记录持久化（SQLite，与模拟状态同库 debug_sim.db）

消息在桥接层统一落库：用户消息在浏览器上行时记、bot 回复在下行转发时记，
各端打开会话时从后端拉取历史，跨设备/跨浏览器可见。
每个会话只保留最近 MAX_PER_CONVERSATION 条，防止无限膨胀。
"""
import json
import sqlite3
from typing import Any

from nonebot.utils import run_sync
from zhenxun.services.log import logger

from .state_store import DB_FILE

MAX_PER_CONVERSATION = 500


def _connect() -> sqlite3.Connection:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS debug_chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            self_id TEXT NOT NULL,
            conversation TEXT NOT NULL,
            sender TEXT NOT NULL DEFAULT 'user',
            sender_id TEXT DEFAULT '',
            sender_name TEXT DEFAULT '',
            message TEXT NOT NULL DEFAULT '[]',
            time TEXT DEFAULT '',
            ts REAL NOT NULL DEFAULT 0
        )"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_chat_conv
            ON debug_chat_messages (self_id, conversation, ts)"""
    )
    conn.commit()
    return conn


@run_sync
def _save_messages(
    self_id: str, conversation: str, rows: list[dict[str, Any]]
) -> bool:
    conn = _connect()
    try:
        conn.executemany(
            """INSERT INTO debug_chat_messages
                (self_id, conversation, sender, sender_id, sender_name,
                 message, time, ts)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    self_id,
                    conversation,
                    r["sender"],
                    r.get("sender_id", ""),
                    r.get("sender_name", ""),
                    json.dumps(r.get("message", []), ensure_ascii=False),
                    r.get("time", ""),
                    r.get("ts", 0),
                )
                for r in rows
            ],
        )
        # 每个会话只保留最近 MAX_PER_CONVERSATION 条
        conn.execute(
            """DELETE FROM debug_chat_messages WHERE id IN (
                SELECT id FROM debug_chat_messages
                WHERE self_id = ? AND conversation = ?
                ORDER BY ts DESC LIMIT -1 OFFSET ?
            )""",
            (self_id, conversation, MAX_PER_CONVERSATION),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.warning(f"保存调试聊天记录失败: {e}")
        return False
    finally:
        conn.close()


async def save_chat_messages(
    self_id: str, conversation: str, rows: list[dict[str, Any]]
) -> bool:
    if not rows:
        return False
    return await _save_messages(self_id, conversation, rows)


@run_sync
def _get_history(
    self_id: str, conversation: str, limit: int
) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        cursor = conn.execute(
            """SELECT id, sender, sender_id, sender_name, message, time, ts
                FROM debug_chat_messages
                WHERE self_id = ? AND conversation = ?
                ORDER BY ts DESC, id DESC LIMIT ?""",
            (self_id, conversation, limit),
        )
        result = []
        for row in cursor.fetchall():
            try:
                message = json.loads(row[4])
            except Exception:
                message = []
            result.append(
                {
                    "id": row[0],
                    "sender": row[1],
                    "sender_id": row[2],
                    "sender_name": row[3],
                    "message": message,
                    "time": row[5],
                    "ts": row[6],
                }
            )
        result.reverse()
        return result
    finally:
        conn.close()


async def get_chat_history(
    self_id: str, conversation: str, limit: int = 200
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 500))
    return await _get_history(self_id, conversation, limit)
