"""日志服务"""
import asyncio
from collections import deque
from collections.abc import AsyncGenerator
from datetime import datetime
import re


def extract_log_level(message: str) -> str:
    """从日志消息中提取日志级别

    参数:
        message: 日志消息

    返回:
        str: 日志级别
    """
    level_patterns = [
        r"\[([A-Z]{4,})\]",  # 匹配 [DEBUG], [INFO], [WARNING], [ERROR]
        r"\b(DEBUG|INFO|WARNING|ERROR|CRITICAL)\b",  # 匹配独立的级别单词
    ]

    for pattern in level_patterns:
        match = re.search(pattern, message)
        if match:
            level = match.group(1)
            if level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
                return level

    return "INFO"  # 默认级别


def extract_log_module(message: str) -> str | None:
    """从日志消息中提取模块名

    参数:
        message: 日志消息

    返回:
        str | None: 模块名
    """
    # 匹配 "nonebot | " 或 "zhenxun | " 等格式
    match = re.search(r"\]\s+(\w+)\s+\|", message)
    if match:
        return match.group(1)
    return None


def clean_log_message(message: str) -> str:
    """清理日志消息，去除时间和级别等重复信息

    参数:
        message: 日志消息

    返回:
        str: 清理后的消息
    """
    clean = message

    # 去除开头的日期时间格式：03-20 21:11:38 或 2024-03-20 21:11:38.123
    clean = re.sub(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?\s*", "", clean)
    clean = re.sub(r"^\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s*", "", clean)

    # 去除 [LEVEL] 格式
    clean = re.sub(r"\s*\[([A-Z]{4,})\]\s*", " ", clean)

    # 去除 | LEVEL | 格式
    clean = re.sub(r"\s*\|\s*([A-Z]{4,})\s*\|\s*", " ", clean)

    # 去除模块名 | 格式（如 "zhenxun | " 或 "nonebot | "）
    clean = re.sub(r"^\s*(\w+)\s*\|\s*", "", clean)

    # 清理多余空格
    clean = " ".join(clean.split())

    return clean


class LogStorage:
    """日志存储"""

    def __init__(self, max_size: int = 1000):
        """初始化日志存储

        参数:
            max_size: 最大存储条数
        """
        self._logs = deque(maxlen=max_size)
        self._subscribers: list[asyncio.Queue] = []
        self._seq = 0  # 日志序列号

    async def add(self, message: str) -> None:
        """添加日志

        参数:
            message: 日志消息
        """
        self._seq += 1
        level = extract_log_level(message)
        module = extract_log_module(message)
        log_entry = {
            "seq": self._seq,
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": clean_log_message(message),
            "module": module,
        }
        self._logs.append(log_entry)

        # 通知所有订阅者
        for subscriber in self._subscribers:
            try:
                subscriber.put_nowait(log_entry)
            except asyncio.QueueFull:
                pass

    def get_logs(self, limit: int = 100) -> list[dict]:
        """获取日志

        参数:
            limit: 获取条数

        返回:
            list[dict]: 日志列表
        """
        logs = list(self._logs)
        if limit > 0 and limit < len(logs):
            logs = logs[-limit:]
        return logs

    def subscribe(self) -> asyncio.Queue:
        """订阅日志

        返回:
            asyncio.Queue: 日志队列
        """
        queue = asyncio.Queue(maxsize=100)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """取消订阅

        参数:
            queue: 日志队列
        """
        if queue in self._subscribers:
            self._subscribers.remove(queue)


# 全局日志存储实例
LOG_STORAGE = LogStorage()


class LogService:
    """日志服务"""

    @staticmethod
    def get_logs(limit: int = 100, level: str | None = None) -> list[dict]:
        """获取日志

        参数:
            limit: 获取条数
            level: 日志级别过滤

        返回:
            list[dict]: 日志列表
        """
        logs = LOG_STORAGE.get_logs(limit)

        if level:
            logs = [
                log
                for log in logs
                if log.get("level") == level.upper()
            ]

        return logs

    @staticmethod
    async def stream_logs(
        limit: int = 100,
    ) -> AsyncGenerator[dict, None]:
        """流式获取日志

        参数:
            limit: 获取条数

        Yield:
            dict: 日志条目
        """
        queue = LOG_STORAGE.subscribe()
        try:
            while True:
                log_entry = await queue.get()
                yield log_entry
        finally:
            LOG_STORAGE.unsubscribe(queue)
