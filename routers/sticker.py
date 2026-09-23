"""表情包资源懒加载路由

前端 QQ 默认表情图片直连 CDN，加载失败才回退到本路由；本路由若本地
(data/web_ui/stickers/qq) 无缓存，就从 CDN（koishijs/QFace，MIT）拉取并
原子写入本地，再用 FileResponse 下发。前端仓库不存放这些表情资源。
"""
import asyncio
import json

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path

from zhenxun.services.log import logger

router = APIRouter(prefix="/sticker", tags=["表情包"])

# 与 theme/debug_sim 同一数据目录约定
_STICKER_DATA = Path().resolve() / "data" / "web_ui" / "stickers"

# QQ 表情源仓库内前缀（_index.json 里 assets 的 path 已含 assets/qq_emoji 前缀）
_QQNT_REL_INDEX = "assets/qq_emoji/_index.json"
# 多个镜像：raw 优先，jsDelivr 兜底
_CDN_TEMPLATES = [
    "https://raw.githubusercontent.com/koishijs/QFace/master/public/{rel}",
    "https://cdn.jsdelivr.net/gh/koishijs/QFace@master/public/{rel}",
]

# id 允许数字与符号表情（如 ☀/🔥），仅拦截路径分隔与穿越
def _safe_emoji_id(emoji_id: str) -> bool:
    return (
        0 < len(emoji_id) <= 32
        and "/" not in emoji_id
        and "\\" not in emoji_id
        and "\x00" not in emoji_id
        and emoji_id not in (".", "..")
    )

# 按 id 维护下载锁，避免并发重复拉同一文件；索引只做一次内存缓存
_locks: dict[str, asyncio.Lock] = {}
_index_cache: list | None = None


def _get_lock(key: str) -> asyncio.Lock:
    lock = _locks.get(key)
    if lock is None:
        lock = _locks[key] = asyncio.Lock()
    return lock


async def _fetch_rel(rel: str) -> bytes:
    """跨镜像、跨代理模式抓取仓库文件

    先忽略环境变量里的（可能失效的）系统代理直连，再回退到跟随环境代理，
    覆盖"直连可通但环境代理挂了"和"必须走代理"两种网络形态。
    """
    last_err: Exception | None = None
    for template in _CDN_TEMPLATES:
        url = template.format(rel=rel)
        for trust_env in (False, True):
            try:
                async with httpx.AsyncClient(
                    timeout=30.0, follow_redirects=True, trust_env=trust_env
                ) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    return resp.content
            except Exception as e:  # noqa: BLE001 逐源尝试，最后统一报错
                last_err = e
    raise last_err if last_err else RuntimeError("无可用镜像")


async def _load_index() -> list:
    """加载 QQNT 表情索引：本地缓存优先，缺失则从 CDN 拉取后落盘"""
    global _index_cache
    if _index_cache is not None:
        return _index_cache
    local_index = _STICKER_DATA / "_qqnt_index.json"
    if local_index.exists():
        try:
            _index_cache = json.loads(local_index.read_text(encoding="utf-8"))
            return _index_cache
        except Exception:
            _index_cache = None
    _index_cache = json.loads((await _fetch_rel(_QQNT_REL_INDEX)).decode("utf-8"))
    local_index.parent.mkdir(parents=True, exist_ok=True)
    local_index.write_text(
        json.dumps(_index_cache, ensure_ascii=False), encoding="utf-8"
    )
    return _index_cache


def _resolve_source(index: list, emoji_id: str, prefer: str = "apng") -> str | None:
    """按 id 取条目，prefer=apng 优先动画(type=2)，prefer=png 优先静态(type=0)"""
    entry = next((e for e in index if str(e.get("emojiId")) == emoji_id), None)
    if entry is None or entry.get("isHide"):
        return None
    assets = entry.get("assets") or []
    apng = next((a for a in assets if a.get("type") == 2), None)
    png = next(
        (
            a
            for a in assets
            if a.get("type") == 0 and a["path"].endswith(f"/{emoji_id}.png")
        ),
        None,
    ) or next((a for a in assets if a.get("type") == 0), None)
    chosen = (apng or png) if prefer == "apng" else (png or apng)
    return chosen["path"] if chosen else None


async def _serve(emoji_id: str) -> FileResponse:
    if not _safe_emoji_id(emoji_id):
        raise HTTPException(status_code=400, detail="非法表情 ID")

    cache_dir = _STICKER_DATA / "qq"
    cache_dir.mkdir(parents=True, exist_ok=True)
    local = cache_dir / f"{emoji_id}.png"

    if not local.exists():
        async with _get_lock(emoji_id):
            if not local.exists():  # 拿锁后二次确认
                try:
                    index = await _load_index()
                    # APNG 优先（数字小表情基本都有动画），符号脸退回静态 PNG
                    rel = _resolve_source(index, emoji_id, "apng")
                    if not rel:
                        raise HTTPException(status_code=404, detail="表情不存在")
                    content = await _fetch_rel(rel)
                except HTTPException:
                    raise
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        f"QQ 表情拉取失败 {emoji_id}: {e!r}", "WebUiNext"
                    )
                    raise HTTPException(status_code=502, detail="表情拉取失败")
                tmp = local.with_name(local.name + ".tmp")
                tmp.write_bytes(content)
                tmp.replace(local)  # 原子落盘，避免中断留半截文件

    # APNG 与静态 PNG 同为 .png 扩展，浏览器按 acTL chunk 自动播放动画
    return FileResponse(
        local,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=604800"},
    )


@router.get("/qq/{emoji_id}.png", summary="QQ 默认表情（懒加载缓存）")
async def get_qq_sticker(emoji_id: str) -> FileResponse:
    return await _serve(emoji_id)
