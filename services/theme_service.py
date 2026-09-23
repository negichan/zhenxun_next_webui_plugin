"""主题配置服务

管理员的全局主题配置，持久化到 data/web_ui/theme.json。
所有端通过 WS 的 theme_update 事件保持统一。
"""

import asyncio
import json
from pathlib import Path

THEME_FILE = Path().resolve() / "data" / "web_ui" / "theme.json"

DEFAULT_THEME: dict = {
    # custom = 自定义颜色主题；preset = 内置预设主题
    "source": "preset",
    "preset": "zhenxun-light",
    "primary": "#6366f1",
    # light | dark | system（跟随系统，由各端自行解析实际模式）
    "mode": "light",
    # 多端统一开关（操作端拨动后随 theme_update 广播到所有端）
    "sync": False,
}

_ALLOWED_MODES = {"light", "dark", "system"}


def _read_sync() -> dict:
    if not THEME_FILE.exists():
        return dict(DEFAULT_THEME)
    try:
        data = json.loads(THEME_FILE.read_text(encoding="utf-8"))
    except Exception:
        return dict(DEFAULT_THEME)
    if not isinstance(data, dict):
        return dict(DEFAULT_THEME)
    merged = dict(DEFAULT_THEME)
    merged.update({k: v for k, v in data.items() if k in DEFAULT_THEME})
    return merged


def _write_sync(data: dict) -> None:
    THEME_FILE.parent.mkdir(parents=True, exist_ok=True)
    THEME_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


async def get_theme() -> dict:
    """读取主题配置"""
    return await asyncio.to_thread(_read_sync)


async def update_theme(payload: dict) -> dict:
    """保存主题配置（白名单字段，非法值回退默认）"""
    current = await get_theme()

    if payload.get("source") in ("custom", "preset"):
        current["source"] = payload["source"]
    if isinstance(payload.get("preset"), str) and payload["preset"]:
        current["preset"] = payload["preset"]
    if isinstance(payload.get("primary"), str) and payload["primary"]:
        current["primary"] = payload["primary"]
    if payload.get("mode") in _ALLOWED_MODES:
        current["mode"] = payload["mode"]
    if isinstance(payload.get("sync"), bool):
        current["sync"] = payload["sync"]

    await asyncio.to_thread(_write_sync, current)
    return current
