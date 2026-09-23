"""前端 dist 自动拉取 / 手动更新

- 启动时若本地 data/web_ui/dist 缺产物，从本项目 GitHub Release 拉最新构建包；
- 管理端「检查更新 / 立即更新」按钮强制重新拉取，带旧版本备份与失败回滚；
- 全程走 AsyncHttpx（自动继承 system_proxy），适配局域网内直连 GitHub 不稳；
- 任何异常只告警，不阻塞 bot 启动。
"""
import asyncio
import shutil
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from zhenxun.services.log import logger
from zhenxun.utils.http_utils import AsyncHttpx

# 前端仓库（GitHub Actions 里 Release WebUI 工作流发布 webui-dist.zip）
_REPO = "negichan/zhenxun_new_webui"
_RELEASE_API = f"https://api.github.com/repos/{_REPO}/releases/latest"
_ASSET_NAME = "webui-dist.zip"
_VERSION_FILE = ".version"
_API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "zhenxun-new-webui",
}

_WEBUI_DIR = Path().resolve() / "data" / "web_ui"
_DIST_PATH = _WEBUI_DIR / "dist"

_lock = asyncio.Lock()
# (tag, asset_url, fetched_at)
_latest_cache: tuple[str, str, datetime] | None = None
_LATEST_TTL = timedelta(minutes=5)


def dist_ready() -> bool:
    """dist 是否已有前端产物（以 index.html 为准）"""
    return (_DIST_PATH / "index.html").exists()


def _read_local_version() -> str | None:
    f = _DIST_PATH / _VERSION_FILE
    if f.exists():
        try:
            return f.read_text(encoding="utf-8").strip() or None
        except Exception:
            return None
    return None


def _write_local_version(version: str) -> None:
    """写入本地版本标记文件，供后续版本比对；失败忽略"""
    try:
        _DIST_PATH.mkdir(parents=True, exist_ok=True)
        (_DIST_PATH / _VERSION_FILE).write_text(version, encoding="utf-8")
    except Exception:
        pass


async def _get_latest() -> tuple[str | None, str | None]:
    """获取最新 Release 的 tag 与 zip 资产下载地址（5 分钟缓存）"""
    global _latest_cache
    now = datetime.utcnow()
    if _latest_cache and now - _latest_cache[2] < _LATEST_TTL:
        return _latest_cache[0], _latest_cache[1]
    data = await AsyncHttpx.get_json(_RELEASE_API, headers=_API_HEADERS)
    if not isinstance(data, dict):
        return None, None
    tag = data.get("tag_name") or None
    assets = data.get("assets") or []
    named = next((a for a in assets if a.get("name") == _ASSET_NAME), None) or next(
        (a for a in assets if str(a.get("name", "")).lower().endswith(".zip")), None
    )
    url = named.get("browser_download_url") if named else None
    if tag and url:
        _latest_cache = (tag, url, now)
        return tag, url
    return None, None


def _extract_to(zip_path: Path, dest: Path) -> None:
    """解压 zip 到 dest（zip 内部根即 index.html，无外层包装目录）"""
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            name = member.filename
            if name.startswith(("/", "\\")) or ".." in Path(name).parts:
                continue  # 防路径穿越
            target = dest / name
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)


async def _pull_release(tag: str, url: str) -> tuple[bool, str]:
    """下载并安全替换 dist：先下到临时目录校验，再备份旧版、换新版，失败回滚"""
    incoming = _WEBUI_DIR / ".dist_incoming"
    backup = _WEBUI_DIR / ".dist_backup"
    tmp_zip = _WEBUI_DIR / _ASSET_NAME
    try:
        logger.info(f"开始拉取前端 {tag}: {url}", "WebUiNext")
        if not await AsyncHttpx.download_file(url, tmp_zip, follow_redirects=True):
            return False, "下载失败"
        if incoming.exists():
            shutil.rmtree(incoming, ignore_errors=True)
        _extract_to(tmp_zip, incoming)
        if not (incoming / "index.html").exists():
            return False, "解压后缺少 index.html，放弃本次更新"
        (incoming / _VERSION_FILE).write_text(tag, encoding="utf-8")

        had_old = dist_ready()
        if had_old:
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            shutil.move(str(_DIST_PATH), str(backup))
        try:
            shutil.copytree(incoming, _DIST_PATH, dirs_exist_ok=True)
        except Exception:
            if had_old and backup.exists() and not dist_ready():
                shutil.move(str(backup), str(_DIST_PATH))  # 回滚
                logger.warning("前端更新失败，已回滚旧版本", "WebUiNext")
            raise
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        logger.info(f"前端已更新到 {tag}，刷新 /next 生效", "WebUiNext")
        return True, f"已更新到 {tag}"
    except Exception as e:  # noqa: BLE001
        logger.warning(f"前端 dist 拉取异常: {e!r}", "WebUiNext")
        return False, f"更新异常: {e!r}"
    finally:
        shutil.rmtree(incoming, ignore_errors=True)
        tmp_zip.unlink(missing_ok=True)


async def ensure_dist() -> bool:
    """启动引导：本地无前端产物时才拉取"""
    if dist_ready():
        return True
    async with _lock:
        if dist_ready():  # 双检：并发只拉一次
            return True
        tag, url = await _get_latest()
        if not (tag and url):
            logger.warning("未找到前端 Release，跳过自动拉取", "WebUiNext")
            return False
        ok, _ = await _pull_release(tag, url)
        return ok


async def update_dist() -> tuple[bool, str]:
    """手动强制更新到最新 Release"""
    async with _lock:
        tag, url = await _get_latest()
        if not (tag and url):
            return False, "无法获取最新版本信息（网络或 GitHub API 限制）"
        local = _read_local_version()
        if local == tag and dist_ready():
            return True, f"已是最新版本 {tag}"
        return await _pull_release(tag, url)


async def get_version_info() -> dict:
    """返回本地版本、最新版本与是否有更新

    dist 已存在但缺 .version（手动替换过）时，用最新 Release tag 回填，
    避免 UI 长期显示"版本未知"；后续再更新则由拉取流程写入准确 tag。
    """
    tag, _ = await _get_latest()
    local = _read_local_version()
    if local is None and tag and dist_ready():
        _write_local_version(tag)
        local = tag
    has_update = bool(tag) and (local != tag)
    return {"local": local, "latest": tag, "has_update": has_update}
