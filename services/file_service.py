"""文件服务"""
import asyncio
import base64
from datetime import datetime
import io
import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
import time
import zipfile

import aiofiles

from ..exceptions import FileException, ValidationException
from ..models.file import (
    ArchiveEntry,
    ArchivePreviewResult,
    FileContent,
    FileItem,
    FileListResult,
    FileSearchGroup,
    FileSearchMatch,
    FileSearchResult,
)
from ..utils.formatters import format_datetime, format_file_size
from ..utils.path_validator import generate_path_segments, validate_path_secure


class FileService:
    """文件服务"""

    IMAGE_TYPE = ["jpg", "jpeg", "png", "gif", "bmp", "webp", "svg", "ico", "tiff", "tif"]

    # 支持预览/解压的压缩包后缀（zip 一族 + tar 一族）
    ZIP_SUFFIXES = {".zip", ".jar", ".apk", ".whl", ".epub"}
    TAR_SUFFIXES = {".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz"}
    # 解压安全上限：总解压体积 2GB、条目数 50000
    MAX_EXTRACT_TOTAL_SIZE = 2 * 1024 * 1024 * 1024
    MAX_EXTRACT_ENTRIES = 50000
    # 预览条目展示上限
    PREVIEW_ENTRY_LIMIT = 1000
    # 嵌套压缩包钻入最大层级
    ARCHIVE_CHAIN_MAX_DEPTH = 6
    # 按字节读取上限（hex 视图），20MB
    MAX_BYTES_READ_SIZE = 20 * 1024 * 1024
    # 全文搜索：忽略目录与各项上限
    SEARCH_IGNORED_DIRS = {
        ".git", "__pycache__", ".venv", "venv", "node_modules",
        ".idea", ".vscode", "site-packages", ".pytest_cache", ".mypy_cache",
    }
    SEARCH_MAX_FILE_SIZE = 1024 * 1024  # 超过 1MB 的文件不参与搜索
    SEARCH_MAX_MATCHES_PER_FILE = 20
    SEARCH_MAX_TOTAL_MATCHES = 500
    SEARCH_MAX_FILES = 5000
    SEARCH_MAX_SECONDS = 10.0
    # 命中行的展示窗口：命中点前 80 字符、后 200 字符
    SEARCH_CONTEXT_BEFORE = 80
    SEARCH_CONTEXT_AFTER = 200

    @staticmethod
    def get_mime_type(ext: str) -> str:
        """获取图片的 MIME 类型

        参数:
            ext: 文件扩展名

        返回:
            str: MIME 类型
        """
        mime_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
            ".tiff": "image/tiff",
            ".tif": "image/tiff",
        }
        return mime_types.get(ext.lower(), "application/octet-stream")

    @staticmethod
    def get_root_dir() -> Path:
        """获取根目录

        返回:
            Path: 根目录
        """
        return Path().resolve()

    @staticmethod
    async def get_file_list(path: str | None = None) -> FileListResult:
        """获取文件列表

        参数:
            path: 路径

        返回:
            FileListResult: 文件列表结果
        """
        root_dir = FileService.get_root_dir()
        validated_path, error = validate_path_secure(path, root_dir)
        if error or not validated_path:
            raise ValidationException(error or "无效的路径")

        if not validated_path.exists():
            raise FileException("路径不存在")

        files = []
        for file in os.listdir(validated_path):
            file_path = validated_path / file
            is_file = file_path.is_file()
            is_image = is_file and any(file.endswith(f".{t}") for t in FileService.IMAGE_TYPE)

            # 获取文件/文件夹的 stat 信息
            try:
                stat = file_path.stat()
                file_size = stat.st_size if is_file else None
                file_mtime = stat.st_mtime
            except Exception:
                # 如果无法获取 stat 信息，使用默认值
                file_size = None
                file_mtime = None

            files.append(
                FileItem(
                    name=file,
                    is_file=is_file,
                    is_image=is_image,
                    size=file_size,
                    size_formatted=format_file_size(file_size),
                    # file_mtime 可能为 None（stat 失败），不能直接比较
                    mtime=datetime.fromtimestamp(file_mtime)
                    if file_mtime is not None and file_mtime > 0
                    else None,
                    mtime_formatted=format_datetime(file_mtime)
                    if file_mtime is not None and file_mtime > 0
                    else None,
                    path=str(file_path),
                    parent=str(validated_path) if validated_path != root_dir else None,
                )
            )

        # 排序：文件夹在前，然后按名称排序
        files.sort(key=lambda f: (not f.is_file, f.name.lower()))

        return FileListResult(
            files=files,
            current_path=str(validated_path),
            path_segments=generate_path_segments(str(validated_path.relative_to(root_dir))),
            has_parent=validated_path != root_dir,
        )

    @staticmethod
    def is_text_file(file_path: Path, sample_size: int = 8192) -> bool:
        """检测文件是否为文本文件

        参数:
            file_path: 文件路径
            sample_size: 采样大小

        返回:
            bool: 是否为文本文件
        """
        try:
            with open(file_path, "rb") as f:
                chunk = f.read(sample_size)
                # 检查是否包含常见的二进制文件标记
                # PNG: 89 50 4E 47, JPEG: FF D8 FF
                if chunk.startswith(b"\x89PNG") or chunk.startswith(b"\xff\xd8\xff"):
                    return False
                # 检查是否包含空字节（二进制文件的常见特征）
                if b"\x00" in chunk:
                    return False
                # 尝试解码为 UTF-8
                try:
                    chunk.decode("utf-8")
                    return True
                except UnicodeDecodeError:
                    # 尝试其他常见编码
                    for encoding in ["gbk", "latin-1", "cp437"]:
                        try:
                            chunk.decode(encoding)
                            return True
                        except UnicodeDecodeError:
                            continue
                    return False
        except Exception:
            return False

    @staticmethod
    def _decode_search_text(data: bytes) -> str | None:
        """按 read_file 同款编码链解码，失败返回 None（视为不可搜索）"""
        for encoding in ("utf-8", "gbk"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return None

    @staticmethod
    def _search_files_sync(
        root: Path,
        keyword: str,
        is_regex: bool,
        case_sensitive: bool,
        whole_word: bool,
    ) -> FileSearchResult:
        """同步全文搜索（在线程池中执行，避免阻塞事件循环）"""
        flags = 0 if case_sensitive else re.IGNORECASE
        if whole_word:
            # 整词：非正则时把字面量包进 \b；正则则给整段 pattern 加词边界
            if is_regex:
                try:
                    pattern = re.compile(rf"\b(?:{keyword})\b", flags)
                except re.error as e:
                    raise ValidationException(f"无效的正则表达式：{e}")
            else:
                pattern = re.compile(rf"\b{re.escape(keyword)}\b", flags)
        elif is_regex:
            try:
                pattern = re.compile(keyword, flags)
            except re.error as e:
                raise ValidationException(f"无效的正则表达式：{e}")
        else:
            pattern = None
        needle = keyword if case_sensitive else keyword.lower()

        started = time.monotonic()
        scanned = 0
        total_matches = 0
        truncated = False
        groups: list[FileSearchGroup] = []

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(
                d for d in dirnames if d not in FileService.SEARCH_IGNORED_DIRS
            )
            for name in sorted(filenames):
                if truncated:
                    break
                if scanned >= FileService.SEARCH_MAX_FILES:
                    truncated = True
                    break
                if time.monotonic() - started > FileService.SEARCH_MAX_SECONDS:
                    truncated = True
                    break
                file_path = Path(dirpath) / name
                try:
                    if not file_path.is_file():
                        continue
                    if file_path.stat().st_size > FileService.SEARCH_MAX_FILE_SIZE:
                        continue
                except OSError:
                    continue
                scanned += 1
                if not FileService.is_text_file(file_path):
                    continue
                try:
                    data = file_path.read_bytes()
                except OSError:
                    continue
                text = FileService._decode_search_text(data)
                if text is None:
                    continue

                matches: list[FileSearchMatch] = []
                for lineno, line in enumerate(text.splitlines(), 1):
                    if total_matches >= FileService.SEARCH_MAX_TOTAL_MATCHES:
                        truncated = True
                        break
                    if len(matches) >= FileService.SEARCH_MAX_MATCHES_PER_FILE:
                        break  # 单文件命中太多，该文件停止收集但继续搜其他文件
                    hit: tuple[int, int] | None = None  # (0 起起始列, 命中长度)
                    if pattern is not None:
                        m = pattern.search(line)
                        if m:
                            hit = (m.start(), m.end() - m.start())
                    else:
                        idx = (
                            line.find(needle)
                            if case_sensitive
                            else line.lower().find(needle)
                        )
                        if idx != -1:
                            hit = (idx, len(keyword))
                    if hit is None:
                        continue
                    col, length = hit
                    # 超长行截窗展示：命中点前 80、后 200 字符
                    start = max(0, col - FileService.SEARCH_CONTEXT_BEFORE)
                    end = min(len(line), col + length + FileService.SEARCH_CONTEXT_AFTER)
                    matches.append(
                        FileSearchMatch(
                            line_number=lineno,
                            column=col + 1,
                            length=length,
                            line_text=line[start:end],
                            context_offset=start,
                        )
                    )
                if matches:
                    groups.append(
                        FileSearchGroup(path=str(file_path), name=name, matches=matches)
                    )
                    total_matches += len(matches)
            if truncated:
                break

        return FileSearchResult(
            results=groups,
            total_matches=total_matches,
            scanned_files=scanned,
            truncated=truncated,
        )

    @staticmethod
    async def search_files(
        path: str | None,
        keyword: str,
        is_regex: bool = False,
        case_sensitive: bool = False,
        whole_word: bool = False,
    ) -> FileSearchResult:
        """全文搜索目录下文本文件的内容

        参数:
            path: 搜索根目录，默认工作区根目录
            keyword: 关键词或正则表达式
            is_regex: 是否按正则匹配
            case_sensitive: 是否区分大小写
            whole_word: 是否匹配整个单词

        返回:
            FileSearchResult: 按文件分组的命中结果
        """
        root_dir = FileService.get_root_dir()
        validated_path, error = validate_path_secure(path, root_dir)
        if error or not validated_path:
            raise ValidationException(error or "无效的路径")
        if not keyword.strip():
            raise ValidationException("搜索关键词不能为空")
        if not validated_path.is_dir():
            raise FileException("搜索目录不存在")
        return await asyncio.to_thread(
            FileService._search_files_sync,
            validated_path,
            keyword,
            is_regex,
            case_sensitive,
            whole_word,
        )

    @staticmethod
    def is_image_file(file_path: Path) -> bool:
        """检测文件是否为图片文件

        参数:
            file_path: 文件路径

        返回:
            bool: 是否为图片文件
        """
        ext = file_path.suffix.lower()
        return ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".tiff", ".tif"]

    @staticmethod
    async def read_file(file_path: str, as_image: bool = False, as_bytes: bool = False) -> FileContent:
        """读取文件内容

        参数:
            file_path: 文件路径
            as_image: 是否以图片方式读取（返回 data URL base64）
            as_bytes: 是否按原始字节读取（返回裸 base64，供 hex/utf-8 视图用）

        返回:
            FileContent: 文件内容

        异常:
            FileException: 文件操作失败
        """
        import base64

        root_dir = FileService.get_root_dir()
        validated_path, error = validate_path_secure(file_path, root_dir)
        if error or not validated_path:
            raise ValidationException(error or "无效的路径")

        if not validated_path.exists():
            raise FileException("文件不存在")

        if validated_path.is_dir():
            raise FileException("不能读取目录")

        # 原始字节读取（hex 视图需要未解码字节，跳过文本检测）
        if as_bytes:
            try:
                size = validated_path.stat().st_size
                if size > FileService.MAX_BYTES_READ_SIZE:
                    raise FileException(
                        f"文件过大（{format_file_size(size)}），不支持按字节读取"
                    )
                data = validated_path.read_bytes()
                return FileContent(
                    path=str(validated_path),
                    content=base64.b64encode(data).decode("ascii"),
                    encoding="base64",
                )
            except FileException:
                raise
            except Exception as e:
                raise FileException(f"读取文件字节失败：{e!s}")

        # 如果请求以图片方式读取
        if as_image or FileService.is_image_file(validated_path):
            try:
                with open(validated_path, "rb") as f:
                    image_data = f.read()
                # 转换为 base64
                base64_data = base64.b64encode(image_data).decode("utf-8")
                # 获取 MIME 类型
                mime_type = FileService.get_mime_type(validated_path.suffix)
                return FileContent(
                    path=str(validated_path),
                    content=f"data:{mime_type};base64,{base64_data}",
                    encoding="base64",
                )
            except Exception as e:
                raise FileException(f"读取图片文件失败：{e!s}")

        # 检测是否为文本文件
        if not FileService.is_text_file(validated_path):
            raise FileException("不支持读取二进制文件")

        # 尝试多种编码读取文本文件（读字节后解码，保留原始换行符不做翻译）
        data = validated_path.read_bytes()
        encodings = ["utf-8", "gbk", "utf-8-sig", "latin-1"]
        for encoding in encodings:
            try:
                content = data.decode(encoding)
                return FileContent(
                    path=str(validated_path),
                    content=content,
                    encoding=encoding,
                )
            except (UnicodeDecodeError, LookupError):
                continue

        raise FileException("文件编码不支持")

    # 允许的保存编码（防止任意 codec 注入，也收窄测试面）
    SAVE_ENCODINGS = {"utf-8", "gbk", "gb18030"}

    @staticmethod
    async def save_file(
        file_path: str, content: str, encoding: str = "utf-8"
    ) -> bool:
        """保存文件内容

        参数:
            file_path: 文件路径
            content: 文件内容
            encoding: 写入编码，默认 utf-8

        返回:
            bool: 是否保存成功

        异常:
            FileException: 文件操作失败
        """
        root_dir = FileService.get_root_dir()
        validated_path, error = validate_path_secure(file_path, root_dir)
        if error or not validated_path:
            raise ValidationException(error or "无效的路径")

        if encoding.lower() not in FileService.SAVE_ENCODINGS:
            raise ValidationException(f"不支持的编码：{encoding}")
        encoding = encoding.lower()

        try:
            # newline="" 禁用换行翻译：Windows 文本模式默认把 \n 写成 \r\n，
            # 会让 LF 文件保存后变 CRLF、CRLF 内容变 \r\r\n
            async with aiofiles.open(
                str(validated_path), "w", encoding=encoding, newline=""
            ) as f:
                await f.write(content)
            return True
        except Exception as e:
            raise FileException(f"保存文件失败：{e!s}")

    @staticmethod
    async def delete_file(file_path: str) -> bool:
        """删除文件

        参数:
            file_path: 文件路径

        返回:
            bool: 是否删除成功

        异常:
            FileException: 文件操作失败
        """
        root_dir = FileService.get_root_dir()
        validated_path, error = validate_path_secure(file_path, root_dir)
        if error or not validated_path:
            raise ValidationException(error or "无效的路径")

        if not validated_path.exists():
            raise FileException("文件不存在")

        if validated_path.is_dir():
            raise FileException("不能删除目录")

        try:
            validated_path.unlink()
            return True
        except Exception as e:
            raise FileException(f"删除文件失败：{e!s}")

    @staticmethod
    async def delete_folder(folder_path: str) -> bool:
        """删除文件夹

        参数:
            folder_path: 文件夹路径

        返回:
            bool: 是否删除成功

        异常:
            FileException: 文件操作失败
        """
        root_dir = FileService.get_root_dir()
        validated_path, error = validate_path_secure(folder_path, root_dir)
        if error or not validated_path:
            raise ValidationException(error or "无效的路径")

        if not validated_path.exists():
            raise FileException("文件夹不存在")

        if validated_path.is_file():
            raise FileException("路径指向的是文件，不是文件夹")

        try:
            shutil.rmtree(validated_path)
            return True
        except Exception as e:
            raise FileException(f"删除文件夹失败：{e!s}")

    @staticmethod
    async def rename(source_path: str, new_name: str) -> bool:
        """重命名文件/文件夹

        参数:
            source_path: 源路径
            new_name: 新名称

        返回:
            bool: 是否重命名成功

        异常:
            FileException: 文件操作失败
        """
        root_dir = FileService.get_root_dir()
        validated_path, error = validate_path_secure(source_path, root_dir)
        if error or not validated_path:
            raise ValidationException(error or "无效的路径")

        if not validated_path.exists():
            raise FileException("文件/文件夹不存在")

        new_path = validated_path.parent / new_name

        # 验证新路径是否安全
        new_validated, error = validate_path_secure(str(new_path), root_dir)
        if error or not new_validated:
            raise ValidationException("新路径不合法")

        try:
            validated_path.rename(new_path)
            return True
        except Exception as e:
            raise FileException(f"重命名失败：{e!s}")

    @staticmethod
    def _unique_copy_dest(dest_dir: Path, src: Path) -> Path:
        """同名冲突时生成 name_copy / name_copy2 …"""
        if src.is_file():
            dest = dest_dir / f"{src.stem}_copy{src.suffix}"
            n = 2
            while dest.exists():
                dest = dest_dir / f"{src.stem}_copy{n}{src.suffix}"
                n += 1
            return dest
        dest = dest_dir / f"{src.name}_copy"
        n = 2
        while dest.exists():
            dest = dest_dir / f"{src.name}_copy{n}"
            n += 1
        return dest

    @staticmethod
    def _resolve_dest_dir(dest_dir: str, root_dir: Path) -> Path:
        validated, error = validate_path_secure(dest_dir, root_dir)
        if error or not validated:
            raise ValidationException(error or "无效的目标路径")
        if not validated.exists() or not validated.is_dir():
            raise FileException("目标路径不存在或不是目录")
        return validated

    @staticmethod
    async def copy(source_path: str, dest_dir: str, new_name: str | None = None) -> str:
        """复制文件/文件夹到目标目录，返回新路径"""
        root_dir = FileService.get_root_dir()
        src, error = validate_path_secure(source_path, root_dir)
        if error or not src:
            raise ValidationException(error or "无效的源路径")
        if not src.exists():
            raise FileException("源文件/文件夹不存在")

        dest_parent = FileService._resolve_dest_dir(dest_dir, root_dir)

        if new_name:
            dest = dest_parent / new_name
        else:
            dest = dest_parent / src.name
            if dest.exists():
                dest = FileService._unique_copy_dest(dest_parent, src)

        new_validated, error = validate_path_secure(str(dest), root_dir)
        if error or not new_validated:
            raise ValidationException("目标路径不合法")
        if new_validated.exists():
            raise FileException("目标已存在同名文件/文件夹")

        try:
            if src.is_file():
                shutil.copy2(src, new_validated)
            else:
                shutil.copytree(src, new_validated)
            return str(new_validated)
        except Exception as e:
            raise FileException(f"复制失败：{e!s}")

    @staticmethod
    async def move(source_path: str, dest_dir: str, new_name: str | None = None) -> str:
        """移动文件/文件夹到目标目录，返回新路径"""
        root_dir = FileService.get_root_dir()
        src, error = validate_path_secure(source_path, root_dir)
        if error or not src:
            raise ValidationException(error or "无效的源路径")
        if not src.exists():
            raise FileException("源文件/文件夹不存在")

        dest_parent = FileService._resolve_dest_dir(dest_dir, root_dir)
        dest = dest_parent / (new_name or src.name)

        # 同目录同名：无需移动
        if src.parent.resolve() == dest_parent.resolve() and src.name == dest.name:
            return str(src)

        if dest.exists():
            raise FileException("目标已存在同名文件/文件夹")

        # 禁止移入自身或子目录
        if src.is_dir():
            try:
                dest_parent.resolve().relative_to(src.resolve())
            except ValueError:
                pass
            else:
                raise FileException("不能移动到自身或子目录")

        new_validated, error = validate_path_secure(str(dest), root_dir)
        if error or not new_validated:
            raise ValidationException("目标路径不合法")

        try:
            shutil.move(str(src), str(new_validated))
            return str(new_validated)
        except Exception as e:
            raise FileException(f"移动失败：{e!s}")

    @staticmethod
    async def create_file(parent_path: str, name: str) -> bool:
        """创建文件

        参数:
            parent_path: 父路径
            name: 文件名

        返回:
            bool: 是否创建成功

        异常:
            FileException: 文件操作失败
        """
        root_dir = FileService.get_root_dir()
        validated_path, error = validate_path_secure(parent_path, root_dir)
        if error or not validated_path:
            raise ValidationException(error or "无效的路径")

        if not validated_path.exists() or not validated_path.is_dir():
            raise FileException("父路径不存在或不是目录")

        file_path = validated_path / name

        # 验证新路径是否安全
        new_validated, error = validate_path_secure(str(file_path), root_dir)
        if error or not new_validated:
            raise ValidationException("文件路径不合法")

        if file_path.exists():
            raise FileException("文件已存在")

        try:
            file_path.touch()
            return True
        except Exception as e:
            raise FileException(f"创建文件失败：{e!s}")

    @staticmethod
    async def create_folder(parent_path: str, name: str) -> bool:
        """创建文件夹

        参数:
            parent_path: 父路径
            name: 文件夹名

        返回:
            bool: 是否创建成功

        异常:
            FileException: 文件操作失败
        """
        root_dir = FileService.get_root_dir()
        validated_path, error = validate_path_secure(parent_path, root_dir)
        if error or not validated_path:
            raise ValidationException(error or "无效的路径")

        if not validated_path.exists() or not validated_path.is_dir():
            raise FileException("父路径不存在或不是目录")

        folder_path = validated_path / name

        # 验证新路径是否安全
        new_validated, error = validate_path_secure(str(folder_path), root_dir)
        if error or not new_validated:
            raise ValidationException("文件夹路径不合法")

        if folder_path.exists():
            raise FileException("文件夹已存在")

        try:
            folder_path.mkdir()
            return True
        except Exception as e:
            raise FileException(f"创建文件夹失败：{e!s}")

    # ==================== 压缩包 / 打包下载 ====================

    @staticmethod
    def get_archive_kind(file_path: Path) -> str | None:
        """判断压缩包类型：zip / tar / None（不支持）"""
        name = file_path.name.lower()
        suffixes = [s for s in FileService.TAR_SUFFIXES if name.endswith(s)]
        if suffixes:
            return "tar"
        if file_path.suffix.lower() in FileService.ZIP_SUFFIXES:
            return "zip"
        return None

    @staticmethod
    def _archive_kind_by_name(name: str) -> str | None:
        """按文件名判断压缩包类型（嵌套条目没有 Path，用名字推断）"""
        lower = name.lower()
        if any(lower.endswith(s) for s in FileService.TAR_SUFFIXES):
            return "tar"
        if any(lower.endswith(s) for s in FileService.ZIP_SUFFIXES):
            return "zip"
        return None

    @staticmethod
    def _validate_member_name(name: str) -> bool:
        """压缩包内路径安全校验：拒绝绝对路径与目录穿越"""
        if not name:
            return False
        normalized = name.replace("\\", "/")
        if normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
            return False
        return ".." not in normalized.split("/")

    @staticmethod
    def _list_entries_from_fileobj(fo: io.BytesIO, kind: str) -> list[ArchiveEntry]:
        """从字节流列出压缩包条目（zip / tar 一族）"""
        entries: list[ArchiveEntry] = []
        if kind == "zip":
            with zipfile.ZipFile(fo) as zf:
                for info in zf.infolist():
                    name = info.filename
                    is_dir = name.endswith("/")
                    entries.append(
                        ArchiveEntry(
                            name=name.rstrip("/"),
                            is_dir=is_dir,
                            size=None if is_dir else info.file_size,
                            size_formatted=None if is_dir else format_file_size(info.file_size),
                        )
                    )
        else:
            with tarfile.open(fileobj=fo, mode="r:*") as tf:
                for member in tf.getmembers():
                    entries.append(
                        ArchiveEntry(
                            name=member.name,
                            is_dir=member.isdir(),
                            size=None if member.isdir() else member.size,
                            size_formatted=None if member.isdir() else format_file_size(member.size),
                        )
                    )
        return entries

    @staticmethod
    def _load_member_bytes(validated_path: Path, chain: list[str]) -> bytes:
        """沿条目链逐层进入嵌套压缩包，读取链末端条目的原始字节。

        chain 里每一项都是所在归档内的成员名，最后一项即目标文件。
        """
        if len(chain) > FileService.ARCHIVE_CHAIN_MAX_DEPTH:
            raise ValidationException("嵌套层级过深")
        data = validated_path.read_bytes()
        cur_name = validated_path.name
        for member in chain:
            if not FileService._validate_member_name(member):
                raise ValidationException("压缩包内路径不合法")
            kind = FileService._archive_kind_by_name(cur_name)
            if not kind:
                raise FileException("嵌套目标不是支持的压缩包")
            buf = io.BytesIO(data)
            try:
                if kind == "zip":
                    with zipfile.ZipFile(buf) as zf:
                        info = next(
                            (
                                x
                                for x in zf.infolist()
                                if x.filename.rstrip("/") == member and not x.is_dir()
                            ),
                            None,
                        )
                        if not info:
                            raise FileException(f"压缩包内未找到：{member}")
                        if info.file_size > FileService.MAX_BYTES_READ_SIZE:
                            raise FileException("嵌套内容过大，无法读取")
                        data = zf.read(info)
                else:
                    with tarfile.open(fileobj=buf, mode="r:*") as tf:
                        target = next(
                            (
                                m
                                for m in tf.getmembers()
                                if m.name.rstrip("/") == member and m.isfile()
                            ),
                            None,
                        )
                        if not target:
                            raise FileException(f"压缩包内未找到：{member}")
                        if target.size > FileService.MAX_BYTES_READ_SIZE:
                            raise FileException("嵌套内容过大，无法读取")
                        fobj = tf.extractfile(target)
                        if not fobj:
                            raise FileException(f"压缩包内未找到：{member}")
                        data = fobj.read()
            except (zipfile.BadZipFile, tarfile.TarError, EOFError, KeyError) as e:
                raise FileException(f"压缩包已损坏或无法读取：{e!s}")
            cur_name = member
        return data

    @staticmethod
    async def preview_archive(
        file_path: str, entries: list[str] | None = None
    ) -> ArchivePreviewResult:
        """预览压缩包内容；entries 为钻入嵌套压缩包的条目链（可为空）"""
        root_dir = FileService.get_root_dir()
        validated_path, error = validate_path_secure(file_path, root_dir)
        if error or not validated_path:
            raise ValidationException(error or "无效的路径")

        if not validated_path.is_file():
            raise FileException("压缩包不存在")

        chain = entries or []
        if chain:
            data = FileService._load_member_bytes(validated_path, chain)
            kind = FileService._archive_kind_by_name(chain[-1])
            if not kind:
                raise FileException("不支持的压缩包格式")
            entries_list = FileService._list_entries_from_fileobj(io.BytesIO(data), kind)
        else:
            kind = FileService.get_archive_kind(validated_path)
            if not kind:
                raise FileException("不支持的压缩包格式")
            with open(validated_path, "rb") as fo:
                entries_list = FileService._list_entries_from_fileobj(fo, kind)

        total = len(entries_list)
        entries_list.sort(key=lambda e: (e.is_dir, e.name.lower()))
        return ArchivePreviewResult(
            path=str(validated_path),
            archive_type=kind,
            entries=entries_list[: FileService.PREVIEW_ENTRY_LIMIT],
            total_count=total,
            truncated=total > FileService.PREVIEW_ENTRY_LIMIT,
        )

    @staticmethod
    async def read_archive_entry(file_path: str, entries: list[str]) -> FileContent:
        """读取压缩包（含嵌套）内单个文件的原始字节，base64 返回"""
        root_dir = FileService.get_root_dir()
        validated_path, error = validate_path_secure(file_path, root_dir)
        if error or not validated_path:
            raise ValidationException(error or "无效的路径")
        if not validated_path.is_file():
            raise FileException("压缩包不存在")
        if not entries:
            raise ValidationException("entries 不能为空")

        data = FileService._load_member_bytes(validated_path, entries)
        return FileContent(
            path=f"{file_path}::{entries[-1]}",
            content=base64.b64encode(data).decode("ascii"),
            encoding="base64",
        )

    @staticmethod
    async def extract_archive(file_path: str, dest_name: str | None = None) -> tuple[str, int]:
        """解压压缩包到同名文件夹，返回 (目标目录, 解压条目数)"""
        root_dir = FileService.get_root_dir()
        validated_path, error = validate_path_secure(file_path, root_dir)
        if error or not validated_path:
            raise ValidationException(error or "无效的路径")

        if not validated_path.is_file():
            raise FileException("压缩包不存在")

        kind = FileService.get_archive_kind(validated_path)
        if not kind:
            raise FileException("不支持的压缩包格式")

        base_name = dest_name or f"{validated_path.stem or validated_path.name}_extracted"
        dest = validated_path.parent / base_name

        # 目标目录已存在时追加序号，避免覆盖
        candidate = dest
        counter = 1
        while candidate.exists():
            candidate = validated_path.parent / f"{dest.name}_{counter}"
            counter += 1
        dest = candidate

        # 防穿越：目标目录必须还在根目录内
        dest_validated, error = validate_path_secure(str(dest), root_dir)
        if error or not dest_validated:
            raise ValidationException("解压目标路径不合法")
        dest = dest_validated
        dest.mkdir(parents=True)

        count = 0

        def check_limits(total_size: int, entry_count: int):
            if total_size > FileService.MAX_EXTRACT_TOTAL_SIZE:
                raise FileException("压缩包解压后体积超出限制")
            if entry_count > FileService.MAX_EXTRACT_ENTRIES:
                raise FileException("压缩包条目数超出限制")

        try:
            if kind == "zip":
                total_size = 0
                with zipfile.ZipFile(validated_path) as zf:
                    for info in zf.infolist():
                        name = info.filename.rstrip("/")
                        if not FileService._validate_member_name(info.filename):
                            continue
                        check_limits(total_size, count)
                        total_size += info.file_size
                        target = dest / name
                        if info.is_dir() or not name:
                            target.mkdir(parents=True, exist_ok=True)
                            continue
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as src, open(target, "wb") as out:
                            shutil.copyfileobj(src, out)
                        count += 1
            else:
                total_size = 0
                with tarfile.open(validated_path, "r:*") as tf:
                    for member in tf.getmembers():
                        if not FileService._validate_member_name(member.name):
                            continue
                        check_limits(total_size, count)
                        total_size += max(member.size, 0)
                        target = dest / member.name.replace("\\", "/")
                        if member.isdir():
                            target.mkdir(parents=True, exist_ok=True)
                            continue
                        if member.issym() or member.islnk():
                            # 拒绝软/硬链接，防止逃逸
                            continue
                        if not member.isfile():
                            continue
                        target.parent.mkdir(parents=True, exist_ok=True)
                        src = tf.extractfile(member)
                        if src is None:
                            continue
                        with src, open(target, "wb") as out:
                            shutil.copyfileobj(src, out)
                        count += 1
        except FileException:
            shutil.rmtree(dest, ignore_errors=True)
            raise
        except (zipfile.BadZipFile, tarfile.TarError, EOFError, OSError) as e:
            shutil.rmtree(dest, ignore_errors=True)
            raise FileException(f"解压失败：{e!s}")

        return str(dest), count

    @staticmethod
    def _add_path_to_zip(zf: zipfile.ZipFile, path: Path, root_for_arcname: Path) -> int:
        """递归把文件/文件夹写入 zip，返回写入的文件数"""
        count = 0
        if path.is_file():
            zf.write(path, path.relative_to(root_for_arcname))
            return 1
        for child in sorted(path.rglob("*")):
            if child.is_file():
                zf.write(child, child.relative_to(root_for_arcname))
                count += 1
        return count

    @staticmethod
    async def compress_files(paths: list[str], name: str | None = None) -> tuple[str, int]:
        """把多个文件/文件夹压缩为 zip，返回 (压缩包路径, 文件数)"""
        if not paths:
            raise ValidationException("未选择要压缩的内容")

        root_dir = FileService.get_root_dir()
        validated: list[Path] = []
        for p in paths[:100]:
            vp, error = validate_path_secure(p, root_dir)
            if error or not vp:
                raise ValidationException(error or f"无效的路径：{p}")
            if not vp.exists():
                raise FileException(f"路径不存在：{vp.name}")
            validated.append(vp)

        if name and ("/" in name or "\\" in name or ".." in name):
            raise ValidationException("压缩包名称不合法")
        if not name:
            name = f"archive_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        if not name.lower().endswith(".zip"):
            name += ".zip"

        parent = validated[0].parent
        target, error = validate_path_secure(str(parent / name), root_dir)
        if error or not target:
            raise ValidationException("压缩包路径不合法")
        if target.exists():
            raise FileException("同名压缩包已存在")

        # arcname 以所选路径的共同父目录为根，保持顶层名称
        root_for_arcname = parent
        count = 0
        try:
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
                for vp in validated:
                    count += FileService._add_path_to_zip(zf, vp, root_for_arcname)
        except Exception as e:
            target.unlink(missing_ok=True)
            raise FileException(f"压缩失败：{e!s}")

        return str(target), count

    @staticmethod
    async def build_download_archive(paths: list[str], dest_file: Path) -> int:
        """把多选内容打包到指定 zip 文件（下载用），返回文件数"""
        root_dir = FileService.get_root_dir()
        validated: list[Path] = []
        for p in paths[:100]:
            vp, error = validate_path_secure(p, root_dir)
            if error or not vp:
                raise ValidationException(error or f"无效的路径：{p}")
            if not vp.exists():
                raise FileException(f"路径不存在：{vp.name}")
            validated.append(vp)

        parent = validated[0].parent if validated else root_dir
        count = 0
        with zipfile.ZipFile(dest_file, "w", zipfile.ZIP_DEFLATED) as zf:
            for vp in validated:
                count += FileService._add_path_to_zip(zf, vp, parent)
        return count
