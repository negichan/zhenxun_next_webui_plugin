"""文件相关模型"""
from datetime import datetime

from pydantic import BaseModel, Field


class FileItem(BaseModel):
    """文件项"""

    name: str = Field(..., description="文件名")
    is_file: bool = Field(..., description="是否为文件")
    is_image: bool = Field(default=False, description="是否为图片")
    size: int | None = Field(None, description="文件大小（字节）")
    size_formatted: str | None = Field(None, description="格式化后的文件大小")
    mtime: datetime | None = Field(None, description="最后修改时间")
    mtime_formatted: str | None = Field(None, description="格式化后的最后修改时间")
    path: str = Field(..., description="完整路径")
    parent: str | None = Field(None, description="父路径")


class FileListResult(BaseModel):
    """文件列表结果"""

    files: list[FileItem] = Field(..., description="文件列表")
    current_path: str = Field(..., description="当前路径")
    path_segments: list[str] = Field(
        default_factory=list, description="路径段（面包屑导航）"
    )
    has_parent: bool = Field(default=False, description="是否有父目录")


class FileContent(BaseModel):
    """文件内容"""

    path: str = Field(..., description="文件路径")
    content: str = Field(..., description="文件内容")
    encoding: str = Field(default="utf-8", description="文件编码")


class FileOperation(BaseModel):
    """文件操作请求"""

    source_path: str = Field(..., description="源路径")
    dest_path: str | None = Field(None, description="目标路径")
    operation: str = Field(..., description="操作类型：delete, rename, move, copy")
    new_name: str | None = Field(None, description="新文件名（重命名用）")


class CreateFileRequest(BaseModel):
    """创建文件/文件夹请求"""

    parent_path: str = Field(..., description="父路径")
    name: str = Field(..., description="文件/文件夹名")


class SaveFileRequest(BaseModel):
    """保存文件请求"""

    file_path: str = Field(..., description="文件路径")
    content: str = Field(..., description="文件内容")
    encoding: str = Field(default="utf-8", description="写入编码：utf-8 / gbk")


class DeleteFileRequest(BaseModel):
    """删除文件请求"""

    file_path: str = Field(..., description="文件路径")


class DeleteFolderRequest(BaseModel):
    """删除文件夹请求"""

    folder_path: str = Field(..., description="文件夹路径")


class RenameRequest(BaseModel):
    """重命名请求"""

    source_path: str = Field(..., description="源路径")
    new_name: str = Field(..., description="新名称")


class CopyMoveRequest(BaseModel):
    """复制/移动请求：把 source_path 放到 dest_dir 目录下"""

    source_path: str = Field(..., description="源文件/文件夹路径")
    dest_dir: str = Field(..., description="目标目录路径")
    new_name: str | None = Field(None, description="可选目标名称，默认保留原名")


class ArchiveEntry(BaseModel):
    """压缩包内条目"""

    name: str = Field(..., description="条目路径（包内相对路径）")
    is_dir: bool = Field(default=False, description="是否为目录")
    size: int | None = Field(None, description="原始大小（字节）")
    size_formatted: str | None = Field(None, description="格式化后的文件大小")


class ArchivePreviewResult(BaseModel):
    """压缩包预览结果"""

    path: str = Field(..., description="压缩包路径")
    archive_type: str = Field(..., description="压缩包类型：zip / tar")
    entries: list[ArchiveEntry] = Field(default_factory=list, description="条目列表")
    total_count: int = Field(default=0, description="条目总数")
    truncated: bool = Field(default=False, description="条目数超出展示上限时为 true")


class ArchivePreviewRequest(BaseModel):
    """压缩包预览请求"""

    path: str = Field(..., description="压缩包路径")
    entries: list[str] = Field(
        default_factory=list,
        description="钻入嵌套压缩包的条目链（为空表示预览 path 本身）",
    )


class ArchiveEntryReadRequest(BaseModel):
    """压缩包内单文件读取请求"""

    path: str = Field(..., description="压缩包路径")
    entries: list[str] = Field(
        ..., description="条目链，最后一项为目标文件成员名"
    )


class ArchiveExtractRequest(BaseModel):
    """压缩包解压请求"""

    path: str = Field(..., description="压缩包路径")
    dest_name: str | None = Field(None, description="目标文件夹名，默认为 <压缩包名>_extracted")


class ArchiveExtractResult(BaseModel):
    """压缩包解压结果"""

    dest_path: str = Field(..., description="解压目标文件夹")
    file_count: int = Field(default=0, description="解压出的文件/文件夹数量")


class ArchiveCompressRequest(BaseModel):
    """压缩请求"""

    paths: list[str] = Field(..., description="要压缩的文件/文件夹路径列表")
    name: str | None = Field(None, description="压缩包文件名，默认 archive_<时间戳>.zip")


class FileSearchRequest(BaseModel):
    """文件内容搜索请求"""

    path: str | None = Field(None, description="搜索根目录，默认工作区根目录")
    keyword: str = Field(..., min_length=1, description="搜索关键词（或正则表达式）")
    is_regex: bool = Field(False, description="是否按正则表达式匹配")
    case_sensitive: bool = Field(False, description="是否区分大小写")
    whole_word: bool = Field(False, description="是否匹配整个单词")


class FileSearchMatch(BaseModel):
    """单条搜索命中"""

    line_number: int = Field(..., description="原始行号（1 起）")
    column: int = Field(..., description="命中起始列（1 起，相对原始行，用于跳转定位）")
    length: int = Field(..., description="命中文本长度")
    line_text: str = Field(..., description="命中所在行的展示切片（命中点前后截窗）")
    context_offset: int = Field(0, description="切片在原始行中的 0 起偏移，用于计算高亮位置")


class FileSearchGroup(BaseModel):
    """按文件分组的搜索命中"""

    path: str = Field(..., description="文件完整路径")
    name: str = Field(..., description="文件名")
    matches: list[FileSearchMatch] = Field(default_factory=list, description="命中列表")


class FileSearchResult(BaseModel):
    """文件内容搜索结果"""

    results: list[FileSearchGroup] = Field(default_factory=list, description="按文件分组的结果")
    total_matches: int = Field(0, description="命中总数（受上限约束）")
    scanned_files: int = Field(0, description="实际扫描的文件数")
    truncated: bool = Field(False, description="是否因上限提前截断")
