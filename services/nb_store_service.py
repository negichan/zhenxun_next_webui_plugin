"""NoneBot 插件商店服务

移植自 molanp/zhenxun_plugin_nb_store（MIT License），为 WebUI 插件市场
NoneBot 源提供列表 / 安装 / 更新 / 卸载能力：
    - 插件列表来自 NoneBot 官方注册表 registry.nonebot.dev/plugins.json
    - 安装 = 从 PyPI 拉取 wheel，解压代码到 nonebot_plugins/<模块名>/
    - 依赖写入该目录 requirements.txt 并交给 VirtualEnvPackageManager 安装
    - 本地版本记录在 data/web_ui/nb_store_versions.json
"""

import asyncio
import contextlib
import csv
import html.parser
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urljoin
import zipfile

import nonebot

from zhenxun.models.plugin_info import PluginInfo
from zhenxun.services.log import logger
from zhenxun.utils.http_utils import AsyncHttpx
from zhenxun.utils.manager.virtual_env_package_manager import (
    VirtualEnvPackageManager,
)

from ..exceptions import APIException, NotFoundException

LOG_COMMAND = "WebUI-NB商店"

NB_PLUGIN_DIR = Path() / "nonebot_plugins"
NB_PLUGIN_DIR.mkdir(parents=True, exist_ok=True)
NB_REGISTRY_URL = "https://registry.nonebot.dev/plugins.json"
NB_VER_FILE = Path().resolve() / "data" / "web_ui" / "nb_store_versions.json"

# 注册表缓存（秒）
_CACHE_TTL = 300
_registry_cache: tuple[float, list[dict]] | None = None

_versions: dict[str, str] | None = None
_ver_lock = asyncio.Lock()

try:
    from packaging.version import parse as _parse_version
except ImportError:  # pragma: no cover
    _parse_version = None

# 安装的 NB 插件目录注册进 nonebot（同 nb_store 做法），重启后生效
with contextlib.suppress(Exception):
    nonebot.load_plugins(str(NB_PLUGIN_DIR))


# ==================== 版本记录 ====================
async def _load_versions_unlocked() -> dict[str, str]:
    """读取本地版本记录（调用方需持锁）"""
    global _versions
    if _versions is None:

        def _load() -> dict:
            try:
                data = json.loads(NB_VER_FILE.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except (FileNotFoundError, json.JSONDecodeError):
                return {}

        _versions = await asyncio.to_thread(_load)
    return _versions


async def _save_versions_unlocked(versions: dict[str, str]) -> None:
    """写入本地版本记录（调用方需持锁）"""

    def _write() -> None:
        NB_VER_FILE.parent.mkdir(parents=True, exist_ok=True)
        NB_VER_FILE.write_text(
            json.dumps(versions, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    await asyncio.to_thread(_write)


async def get_local_versions() -> dict[str, str]:
    async with _ver_lock:
        return dict(await _load_versions_unlocked())


async def set_version(module_name: str, version: str) -> None:
    async with _ver_lock:
        versions = await _load_versions_unlocked()
        versions[module_name] = version
        await _save_versions_unlocked(versions)


async def remove_version(module_name: str) -> None:
    async with _ver_lock:
        versions = await _load_versions_unlocked()
        versions.pop(module_name, None)
        await _save_versions_unlocked(versions)


# ==================== 注册表 ====================
async def _fetch_registry() -> list[dict]:
    """拉取 NoneBot 官方注册表（带 TTL 缓存，全量返回不过滤类型）"""
    global _registry_cache
    now = time.time()
    if _registry_cache and now - _registry_cache[0] < _CACHE_TTL:
        return _registry_cache[1]
    response = await AsyncHttpx.get(NB_REGISTRY_URL, timeout=30)
    if response.status_code != 200:
        logger.warning(
            f"获取 NoneBot 插件列表失败: {response.status_code}", LOG_COMMAND
        )
        if _registry_cache:
            return _registry_cache[1]
        return []
    data = json.loads(response.text)
    _registry_cache = (now, data)
    logger.info(f"获取 NoneBot 插件列表成功，共 {len(data)} 项", LOG_COMMAND)
    return data


async def _installed_modules() -> dict[str, str]:
    """已安装的 NB 插件: 模块名 -> 本地版本"""
    modules = await PluginInfo.filter(
        load_status=True, module_path__startswith="nonebot_plugins."
    ).values_list("module", flat=True)
    versions = await get_local_versions()
    return {module: versions.get(module, "Unknown") for module in modules}


async def get_nb_plugin_list() -> list[dict]:
    """插件市场 NoneBot 源列表（含安装状态与更新标记）"""
    registry = await _fetch_registry()
    installed = await _installed_modules()
    result = []
    for detail in registry:
        module = detail.get("module_name", "")
        local_version = installed.get(module)
        version = detail.get("version", "")
        result.append(
            {
                "name": detail.get("name", ""),
                "module_name": module,
                "project_link": detail.get("project_link", ""),
                "homepage": detail.get("homepage", ""),
                "desc": detail.get("desc", ""),
                "tags": detail.get("tags") or [],
                "author": detail.get("author", ""),
                "version": version,
                "is_official": detail.get("is_official", False),
                "time": detail.get("time", ""),
                "valid": detail.get("valid", False),
                "installed": local_version is not None,
                "local_version": local_version,
                "has_update": bool(
                    local_version
                    and local_version != "Unknown"
                    and local_version != version
                ),
            }
        )
    return result


# ==================== wheel 处理（移植自 nb_store/utils.py） ====================
class _SimpleIndexParser(html.parser.HTMLParser):
    """解析 PyPI simple 索引页中的 .whl 链接"""

    def __init__(self):
        super().__init__()
        self.links: list[str] = []
        self._current_href: str | None = None
        self._is_anchor = False

    def handle_starttag(self, tag, attrs):
        self._is_anchor = tag == "a"
        if self._is_anchor:
            self._current_href = dict(attrs).get("href")

    def handle_data(self, data):
        if (
            self._is_anchor
            and self._current_href
            and data.lower().endswith(".whl")
        ):
            self.links.append(self._current_href)

    def handle_endtag(self, tag):
        if tag == "a":
            self._is_anchor = False
            self._current_href = None


async def _get_pip_index_url() -> str:
    """获取 pip 镜像索引地址"""
    with contextlib.suppress(Exception):
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "pip", "config", "get", "global.index-url"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if url := result.stdout.strip():
            return url if url.endswith("/") else f"{url}/"
    with contextlib.suppress(Exception):
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "pip", "config", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.splitlines():
            if "index-url" in line:
                return line.split("=", 1)[-1].strip()
    return "https://pypi.org/simple/"


async def _get_whl_download_url(package: str) -> str | None:
    """获取最新的 whl 下载地址（清华源自动切阿里云避免 403）"""
    index_url = await _get_pip_index_url()
    if "pypi.tuna.tsinghua.edu.cn" in index_url:
        logger.warning(
            "为避免清华 pip 的 403 错误，已自动切换为阿里云镜像", LOG_COMMAND
        )
        index_url = "https://mirrors.aliyun.com/pypi/simple"
    if not index_url.endswith("/"):
        index_url += "/"
    url = urljoin(index_url, package.replace("_", "-").lower())
    if not url.endswith("/"):
        url += "/"
    html = await AsyncHttpx.get(
        url, timeout=15, headers={"User-Agent": "pip/25.0.0"}
    )
    parser = _SimpleIndexParser()
    parser.feed(html.text)
    if not parser.links:
        return None
    if _parse_version:

        def _key(link: str):
            try:
                return _parse_version(link.split("-")[1])
            except Exception:
                return _parse_version("0")

        parser.links.sort(key=_key, reverse=True)
    else:
        parser.links.sort(reverse=True)
    return urljoin(url, parser.links[0])


def _extract_whl(zf: zipfile.ZipFile, dest_dir: Path) -> list[str]:
    """解压 RECORD 中的代码文件到目标目录，返回 METADATA 依赖列表"""
    namelist = zf.namelist()
    record_file = next(
        (
            name
            for name in namelist
            if name.endswith("RECORD") and ".dist-info/" in name
        ),
        None,
    )
    if not record_file:
        raise FileNotFoundError("找不到 RECORD 文件")
    records: list[str] = []
    for line in zf.read(record_file).decode("utf-8").splitlines():
        if row := next(csv.reader([line]), None):
            records.append(row[0])

    dependencies: list[str] = []
    metadata_file = next(
        (
            f
            for f in namelist
            if f.endswith("METADATA") and ".dist-info/" in f
        ),
        None,
    )
    if metadata_file:
        for line in zf.read(metadata_file).decode(
            "utf-8", errors="ignore"
        ).splitlines():
            stripped = line.strip()
            if stripped.startswith("Requires-Dist:"):
                dep = stripped[len("Requires-Dist:"):].strip()
                if dep:
                    dependencies.append(dep)

    for file in records:
        if ".dist-info/" in file or ".data/" in file or file.endswith("/"):
            continue
        dest_path = dest_dir / file
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(zf.read(file))
    return dependencies


def _move_contents_up_one_level(target_dir: Path) -> None:
    """将目录内容上移一级（处理 wheel 内多包一层目录的情况）"""
    parent_dir = target_dir.parent
    for item in target_dir.iterdir():
        dest_path = parent_dir / item.name
        if dest_path.exists():
            if dest_path.is_dir() and item.is_dir():
                for sub_item in item.iterdir():
                    shutil.move(str(sub_item), str(dest_path))
                item.rmdir()
            else:
                if dest_path.is_file():
                    dest_path.unlink()
                shutil.move(str(item), str(dest_path))
        else:
            shutil.move(str(item), str(parent_dir))
    if not any(target_dir.iterdir()):
        target_dir.rmdir()


def _write_whl(whl_bytes: bytes, target_path: Path) -> None:
    """解压 wheel 到目标目录并写入 requirements.txt"""
    target_path.mkdir(parents=True, exist_ok=True)
    dependencies: list[str] = []
    with zipfile.ZipFile(io.BytesIO(whl_bytes)) as zf:
        dependencies = _extract_whl(zf, target_path)
    if not (target_path / "__init__.py").exists():
        logger.warning(
            f"{target_path} 不是一个有效的插件目录，正在修复...", LOG_COMMAND
        )
        _move_contents_up_one_level(target_path)
    if dependencies:
        (target_path / "requirements.txt").write_text(
            "\n".join(dependencies) + "\n", encoding="utf-8"
        )


# ==================== 安装 / 更新 / 卸载 ====================
def _find_detail(registry: list[dict], module_name: str) -> dict:
    detail = next(
        (d for d in registry if d.get("module_name") == module_name), None
    )
    if not detail:
        raise NotFoundException(f"插件 {module_name} 不存在")
    return detail


async def install_nb_plugin(module_name: str, *, is_update: bool = False) -> str:
    """安装 / 更新 NoneBot 插件

    参数:
        module_name: 插件模块名
        is_update: 是否为更新操作

    返回:
        str: 结果消息
    """
    detail = _find_detail(await _fetch_registry(), module_name)
    name = detail.get("name", module_name)
    version = detail.get("version", "")
    installed = await _installed_modules()

    if not is_update and module_name in installed:
        raise APIException(f"插件 {name} 已安装，无需重复安装")
    if is_update and module_name not in installed:
        raise APIException(f"插件 {name} 未安装，无法更新")
    if (
        is_update
        and module_name in installed
        and installed[module_name] == version
    ):
        raise APIException(f"插件 {name} 已是最新版本")

    logger.info(
        f"开始下载 NoneBot 插件 {name}({module_name})", LOG_COMMAND
    )
    down_url = await _get_whl_download_url(detail.get("project_link", ""))
    if not down_url:
        raise NotFoundException(f"插件 {name} 未找到安装包...")
    whl_data = await AsyncHttpx.get(down_url, timeout=60)
    target_path = NB_PLUGIN_DIR / module_name

    def _cleanup_and_write() -> None:
        if target_path.exists():
            shutil.rmtree(target_path)
        _write_whl(whl_data.content, target_path)

    await asyncio.to_thread(_cleanup_and_write)
    await set_version(module_name, version)

    requirements = target_path / "requirements.txt"
    if requirements.exists():
        logger.info(f"安装 NoneBot 插件 {name} 的依赖", LOG_COMMAND)
        await VirtualEnvPackageManager.install_requirement(requirements)

    action = "更新" if is_update else "安装"
    return f"插件 {name} {action}成功! 重启 Bot 后生效"


async def remove_nb_plugin(module_name: str) -> str:
    """卸载 NoneBot 插件"""
    detail = _find_detail(await _fetch_registry(), module_name)
    name = detail.get("name", module_name)
    path = NB_PLUGIN_DIR / module_name
    if not path.exists():
        raise NotFoundException(f"插件 {name} 未安装或不存在")
    logger.info(f"移除 NoneBot 插件 {name}: {path}", LOG_COMMAND)
    await asyncio.to_thread(shutil.rmtree, path)
    await remove_version(module_name)
    return f"插件 {name} 移除成功! 重启 Bot 后生效"


class NbStoreService:
    """NoneBot 插件商店（供路由层调用）"""

    get_nb_plugin_list = staticmethod(get_nb_plugin_list)
    install_nb_plugin = staticmethod(install_nb_plugin)
    remove_nb_plugin = staticmethod(remove_nb_plugin)

    @classmethod
    async def update_nb_plugin(cls, module_name: str) -> str:
        return await install_nb_plugin(module_name, is_update=True)
