"""文件路由"""
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

from ..dependencies import AuthenticatedUser
from ..exceptions import FileException, ValidationException
from ..models.file import (
    ArchiveCompressRequest,
    ArchiveEntryReadRequest,
    ArchiveExtractRequest,
    ArchiveExtractResult,
    ArchivePreviewRequest,
    ArchivePreviewResult,
    CopyMoveRequest,
    CreateFileRequest,
    DeleteFileRequest,
    DeleteFolderRequest,
    FileContent,
    FileListResult,
    FileSearchRequest,
    FileSearchResult,
    RenameRequest,
    SaveFileRequest,
)
from ..responses import APIResponse, error_response, success_response
from ..services.file_service import FileService
from ..utils.path_validator import validate_path_secure

router = APIRouter(prefix="/file", tags=["文件管理"])


@router.get(
    "/list",
    response_model=APIResponse[FileListResult],
    response_class=JSONResponse,
    summary="获取文件列表",
)
async def get_file_list(
    user: AuthenticatedUser, path: str | None = None
) -> APIResponse[FileListResult]:
    """获取指定路径下的文件列表

    Args:
        path: 路径，默认为根目录

    Returns:
        APIResponse[FileListResult]: 文件列表结果
    """
    result = await FileService.get_file_list(path)
    return success_response(data=result)


@router.post(
    "/search",
    response_model=APIResponse[FileSearchResult],
    response_class=JSONResponse,
    summary="全文搜索文件内容",
)
async def search_files(
    user: AuthenticatedUser, request: FileSearchRequest
) -> APIResponse[FileSearchResult]:
    """在指定目录下全文搜索文本文件内容

    Args:
        request: 搜索请求（根目录 / 关键词 / 正则开关 / 大小写开关）

    Returns:
        APIResponse[FileSearchResult]: 按文件分组的命中结果
    """
    result = await FileService.search_files(
        request.path,
        request.keyword,
        request.is_regex,
        request.case_sensitive,
        request.whole_word,
    )
    return success_response(data=result)


@router.get(
    "/read",
    response_class=JSONResponse,
    summary="读取文件内容",
)
async def read_file(
    user: AuthenticatedUser,
    file_path: str,
    as_image: bool = False,
    as_bytes: bool = False,
):
    """读取指定文件的内容

    Args:
        file_path: 文件路径
        as_image: 是否以图片方式读取（返回 base64）
        as_bytes: 是否按原始字节读取（返回裸 base64，供 hex/utf-8 视图）

    Returns:
        文件内容或错误响应
    """
    try:
        result = await FileService.read_file(
            file_path, as_image=as_image, as_bytes=as_bytes
        )
        return success_response(data=result)
    except FileException as e:
        # 直接返回 JSON 响应
        return JSONResponse(
            status_code=e.code,
            content=error_response(message=e.message, code=e.code).model_dump(),
        )


@router.post(
    "/save",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="保存文件内容",
)
async def save_file(
    user: AuthenticatedUser, request: SaveFileRequest
) -> APIResponse[bool]:
    """保存文件内容

    Args:
        request: 保存请求

    Returns:
        APIResponse[bool]: 是否保存成功
    """
    result = await FileService.save_file(
        request.file_path, request.content, request.encoding
    )
    return success_response(data=result, message="保存成功")


@router.post(
    "/delete",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="删除文件",
)
async def delete_file(
    user: AuthenticatedUser, request: DeleteFileRequest
) -> APIResponse[bool]:
    """删除指定文件

    Args:
        request: 删除请求

    Returns:
        APIResponse[bool]: 是否删除成功
    """
    result = await FileService.delete_file(request.file_path)
    return success_response(data=result, message="删除成功")


@router.post(
    "/delete-folder",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="删除文件夹",
)
async def delete_folder(
    user: AuthenticatedUser, request: DeleteFolderRequest
) -> APIResponse[bool]:
    """删除指定文件夹

    Args:
        request: 删除请求

    Returns:
        APIResponse[bool]: 是否删除成功
    """
    result = await FileService.delete_folder(request.folder_path)
    return success_response(data=result, message="删除成功")


@router.post(
    "/rename",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="重命名文件/文件夹",
)
async def rename(
    user: AuthenticatedUser, request: RenameRequest
) -> APIResponse[bool]:
    """重命名文件或文件夹

    Args:
        request: 重命名请求

    Returns:
        APIResponse[bool]: 是否重命名成功
    """
    result = await FileService.rename(request.source_path, request.new_name)
    return success_response(data=result, message="重命名成功")


@router.post(
    "/copy",
    response_model=APIResponse[str],
    response_class=JSONResponse,
    summary="复制文件/文件夹",
)
async def copy_path(
    user: AuthenticatedUser, request: CopyMoveRequest
) -> APIResponse[str]:
    """复制文件/文件夹到目标目录，返回新路径"""
    result = await FileService.copy(
        request.source_path, request.dest_dir, request.new_name
    )
    return success_response(data=result, message="复制成功")


@router.post(
    "/move",
    response_model=APIResponse[str],
    response_class=JSONResponse,
    summary="移动文件/文件夹",
)
async def move_path(
    user: AuthenticatedUser, request: CopyMoveRequest
) -> APIResponse[str]:
    """移动文件/文件夹到目标目录，返回新路径"""
    result = await FileService.move(
        request.source_path, request.dest_dir, request.new_name
    )
    return success_response(data=result, message="移动成功")


@router.post(
    "/create-file",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="创建文件",
)
async def create_file(
    user: AuthenticatedUser, request: CreateFileRequest
) -> APIResponse[bool]:
    """创建新文件

    Args:
        request: 创建请求

    Returns:
        APIResponse[bool]: 是否创建成功
    """
    result = await FileService.create_file(request.parent_path, request.name)
    return success_response(data=result, message="创建成功")


@router.post(
    "/create-folder",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="创建文件夹",
)
async def create_folder(
    user: AuthenticatedUser, request: CreateFileRequest
) -> APIResponse[bool]:
    """创建新文件夹

    Args:
        request: 创建请求

    Returns:
        APIResponse[bool]: 是否创建成功
    """
    result = await FileService.create_folder(request.parent_path, request.name)
    return success_response(data=result, message="创建成功")


@router.get(
    "/download",
    summary="下载文件（单文件直下，多选/文件夹打包 zip）",
)
async def download_files(user: AuthenticatedUser, paths: str):
    """下载文件

    Args:
        paths: JSON 数组字符串，如 `["/a/b.txt"]`；
               单个文件直接返回原文件，多个文件或文件夹打包为 zip

    Returns:
        FileResponse: 文件流
    """
    try:
        path_list = json.loads(paths)
        if not isinstance(path_list, list) or not path_list:
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        raise ValidationException("paths 参数格式错误")

    root_dir = FileService.get_root_dir()

    validated: list = []
    for p in path_list[:100]:
        if not isinstance(p, str):
            raise ValidationException("paths 参数格式错误")
        vp, error = validate_path_secure(p, root_dir)
        if error or not vp:
            raise ValidationException(error or f"无效的路径：{p}")
        if not vp.exists():
            raise FileException(f"路径不存在：{vp.name}")
        validated.append(vp)

    # 单个文件直接下载原文件
    if len(validated) == 1 and validated[0].is_file():
        return FileResponse(validated[0], filename=validated[0].name)

    # 多选或文件夹：打包 zip 到临时文件，响应完成后清理
    if len(validated) == 1:
        zip_name = f"{validated[0].name}.zip"
    else:
        zip_name = f"files_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp.close()
    try:
        FileService.build_download_archive([str(v) for v in validated], Path(tmp.name))
    except Exception:
        os.unlink(tmp.name)
        raise

    return FileResponse(
        tmp.name,
        filename=zip_name,
        background=BackgroundTask(os.unlink, tmp.name),
    )


@router.post(
    "/archive-preview",
    response_model=APIResponse[ArchivePreviewResult],
    response_class=JSONResponse,
    summary="预览压缩包内容",
)
async def archive_preview(
    user: AuthenticatedUser, request: ArchivePreviewRequest
) -> APIResponse[ArchivePreviewResult]:
    """列出压缩包内条目（zip / tar 一族），支持钻入嵌套压缩包"""
    result = await FileService.preview_archive(request.path, request.entries)
    return success_response(data=result)


@router.post(
    "/archive-read-entry",
    response_model=APIResponse[FileContent],
    response_class=JSONResponse,
    summary="读取压缩包内单个文件（base64）",
)
async def archive_read_entry(
    user: AuthenticatedUser, request: ArchiveEntryReadRequest
) -> APIResponse[FileContent]:
    """按条目链读取压缩包（含嵌套）内单个文件的原始字节"""
    result = await FileService.read_archive_entry(request.path, request.entries)
    return success_response(data=result)


@router.post(
    "/archive-extract",
    response_model=APIResponse[ArchiveExtractResult],
    response_class=JSONResponse,
    summary="解压压缩包",
)
async def archive_extract(
    user: AuthenticatedUser, request: ArchiveExtractRequest
) -> APIResponse[ArchiveExtractResult]:
    """解压到压缩包同级的 <名称>_extracted 文件夹"""
    dest, count = await FileService.extract_archive(request.path, request.dest_name)
    return success_response(
        data=ArchiveExtractResult(dest_path=dest, file_count=count),
        message="解压成功",
    )


@router.post(
    "/compress",
    response_model=APIResponse[ArchiveExtractResult],
    response_class=JSONResponse,
    summary="压缩文件/文件夹为 zip",
)
async def compress_files(
    user: AuthenticatedUser, request: ArchiveCompressRequest
) -> APIResponse[ArchiveExtractResult]:
    """把选中的文件/文件夹压缩为 zip"""
    target, count = await FileService.compress_files(request.paths, request.name)
    return success_response(
        data=ArchiveExtractResult(dest_path=target, file_count=count),
        message="压缩成功",
    )
