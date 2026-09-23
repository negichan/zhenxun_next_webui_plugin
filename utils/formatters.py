"""格式化工具函数"""
from datetime import datetime
import math


def format_file_size(size_bytes: int | None) -> str:
    """格式化文件大小"""
    if size_bytes is None or size_bytes == 0:
        return "0 B" if size_bytes == 0 else "-"
    k = 1024
    sizes = ["B", "KB", "MB", "GB", "TB"]
    i = math.floor(math.log(size_bytes) / math.log(k))
    return f"{round(size_bytes / math.pow(k, i) * 100) / 100} {sizes[i]}"


def format_datetime(timestamp: float | None, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """格式化时间戳"""
    return datetime.fromtimestamp(timestamp).strftime(fmt) if timestamp else ""


def format_uptime(seconds: int) -> str:
    """格式化运行时长"""
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if days > 0:
        parts.append(f"{days}天")
    if hours > 0:
        parts.append(f"{hours}小时")
    if minutes > 0:
        parts.append(f"{minutes}分")
    if secs > 0 or not parts:
        parts.append(f"{secs}秒")
    return " ".join(parts)


