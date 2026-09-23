"""系统服务"""
from datetime import datetime
import platform

import cpuinfo
from nonebot.utils import run_sync
import psutil

from zhenxun.configs.config import BotConfig
from zhenxun.models.bot_console import BotConsole
from zhenxun.models.group_console import GroupConsole
from zhenxun.utils.http_utils import AsyncHttpx

from ..models.system import BotStatus, SystemHealth, SystemStatus
from ..utils.formatters import format_uptime

BAIDU_URL = "https://www.baidu.com/"
GOOGLE_URL = "https://www.google.com/"
_cpu_percent_last = 0.0


def _get_status_level(value: float) -> tuple[str, str]:
    """获取状态级别"""
    if value > 90:
        return "critical", "error"
    if value > 70:
        return "high", "warning"
    return "normal", "healthy"


def _disk_usage_aggregate() -> tuple[float, float]:
    """聚合所有固定磁盘的 (used, total) 字节数

    跳过光驱/可移动设备/网络驱动器和常见虚拟文件系统；
    无权限或被独占的盘单个跳过，不影响整体
    """
    total = 0.0
    used = 0.0
    for part in psutil.disk_partitions():
        opts = getattr(part, "opts", "") or ""
        if "cdrom" in opts or "removable" in opts or "remote" in opts:
            continue
        if part.fstype in ("squashfs", "tmpfs", "devtmpfs", "iso9660", "overlay"):
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except Exception:
            continue
        total += usage.total
        used += usage.used
    return used, total


@run_sync
def get_system_status() -> SystemStatus:
    """获取系统状态"""
    global _cpu_percent_last
    cpu = psutil.cpu_percent(interval=0.5)
    if cpu == 0.0:
        cpu = _cpu_percent_last
    _cpu_percent_last = cpu

    disk_used, disk_total = _disk_usage_aggregate()
    disk = round(disk_used / disk_total * 100, 1) if disk_total else 0.0

    return SystemStatus(
        cpu=cpu,
        memory=psutil.virtual_memory().percent,
        disk=disk,
        check_time=datetime.now().replace(microsecond=0),
    )


@run_sync
def get_system_health() -> SystemHealth:
    """获取系统健康状态"""
    cpu = psutil.cpu_percent(interval=0.5)
    memory = psutil.virtual_memory().percent
    disk_used, disk_total = _disk_usage_aggregate()
    disk = round(disk_used / disk_total * 100, 1) if disk_total else 0.0

    cpu_status, cpu_health = _get_status_level(cpu)
    memory_status, memory_health = _get_status_level(memory)
    disk_status, disk_health = _get_status_level(disk)

    # 总体健康状态
    status = "healthy"
    if "error" in [cpu_health, memory_health, disk_health]:
        status = "error"
    elif "warning" in [cpu_health, memory_health, disk_health]:
        status = "warning"

    # 生成优化建议
    recommendations = []
    if cpu > 80:
        recommendations.append("CPU 使用率较高，建议检查高负载进程")
    if memory > 80:
        recommendations.append("内存使用率较高，建议检查内存占用")
    if disk > 80:
        recommendations.append("磁盘使用率较高，建议清理无用文件")

    return SystemHealth(
        status=status,
        cpu_status=cpu_status,
        memory_status=memory_status,
        disk_status=disk_status,
        recommendations=recommendations,
    )


async def get_bot_status() -> BotStatus:
    """获取 Bot 状态"""
    import nonebot

    bots = nonebot.get_bots()
    is_running = len(bots) > 0

    # 获取运行时长
    uptime = 0
    start_time = datetime.now()
    try:
        from zhenxun.models.bot_connect_log import BotConnectLog
        latest_connect = await BotConnectLog.filter(type=1).order_by("-connect_time").first()
        if latest_connect and latest_connect.connect_time:
            start_time = latest_connect.connect_time
            uptime = int((datetime.now() - start_time).total_seconds())
    except Exception:
        pass

    # 获取群组数量
    group_count = 0
    try:
        group_count = await GroupConsole.all().count()
    except Exception:
        pass

    return BotStatus(
        is_running=is_running,
        uptime=uptime,
        uptime_formatted=format_uptime(uptime),
        group_count=group_count,
        friend_count=0,
        message_count=0,
        start_time=start_time,
    )


async def check_network() -> dict[str, bool]:
    """检查网络连通性"""
    baidu, google = True, True
    try:
        await AsyncHttpx.get(BAIDU_URL, timeout=5)
    except Exception:
        baidu = False
    try:
        await AsyncHttpx.get(GOOGLE_URL, timeout=5)
    except Exception:
        google = False
    return {"baidu": baidu, "google": google}


@run_sync
def get_system_info() -> dict:
    """获取详细系统信息

    各项独立容错：某一项采集失败（如部分 Windows 没有 wmic 导致
    cpuinfo 抛异常）不应拖垮整个接口，否则前端拿到全 0
    """
    from pathlib import Path

    system = platform.uname()

    cpu_brand = "Unknown"
    try:
        cpu_brand = cpuinfo.get_cpu_info().get("brand_raw", "Unknown")
    except Exception:
        pass

    cpu_cores = 0
    try:
        cpu_cores = psutil.cpu_count(logical=False) or 0
    except Exception:
        pass

    cpu_freq = 0.0
    try:
        freq = psutil.cpu_freq()
        cpu_freq = round(freq.current, 2) if freq else 0
    except Exception:
        pass

    memory_total = 0.0
    try:
        memory_total = round(psutil.virtual_memory().total / (1024**3), 2)
    except Exception:
        pass

    # 磁盘聚合所有固定磁盘（跳过无权限/光驱/可移动/网络盘）
    disk_total = 0.0
    try:
        _, disk_total_bytes = _disk_usage_aggregate()
        disk_total = round(disk_total_bytes / (1024**3), 2)
    except Exception:
        pass

    # 读取版本信息
    version = "unknown"
    version_file = Path("__version__")
    if version_file.exists():
        try:
            content = version_file.read_text("utf-8").strip()
            version = content.split(":", 1)[1].strip() if ":" in content else content
        except Exception:
            pass

    return {
        "version": version,
        "system": f"{system.system} {system.release}",
        "arch": system.machine,
        "cpu_brand": cpu_brand,
        "cpu_cores": cpu_cores,
        "cpu_freq_mhz": cpu_freq,
        "memory_total": memory_total,
        "disk_total": disk_total,
        "nickname": BotConfig.self_nickname,
    }


async def restart_bot() -> bool:
    """重启 Bot"""
    import nonebot

    bots = nonebot.get_bots()
    if not bots:
        return False

    bot = list(bots.values())[0]
    await bot.call_api("set_restart")
    return True
