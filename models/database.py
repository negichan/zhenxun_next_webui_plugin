"""数据库相关模型"""
from pydantic import BaseModel, Field


class TableRowData(BaseModel):
    """表行数据"""

    id: int | str = Field(..., description="主键")
    data: dict = Field(..., description="行数据")


class TableDataResult(BaseModel):
    """表数据结果"""

    items: list[TableRowData] = Field(..., description="数据列表")
    total: int = Field(..., description="总数")
    page: int = Field(..., description="当前页码")
    page_size: int = Field(..., description="每页数量")
    has_next: bool = Field(..., description="是否有下一页")
    has_prev: bool = Field(..., description="是否有上一页")


class SqlExecuteRequest(BaseModel):
    """SQL 执行请求"""

    sql: str = Field(..., description="SQL 语句")


class SqlExecuteResult(BaseModel):
    """SQL 执行结果"""

    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="消息")
    data: list[dict] | None = Field(None, description="返回数据")
    rows_affected: int | None = Field(None, description="影响的行数")


class SqlLogItem(BaseModel):
    """SQL 执行日志条目"""

    id: int = Field(..., description="自增 ID")
    sql: str = Field(..., description="SQL 语句")
    is_success: bool = Field(..., description="是否执行成功")
    message: str = Field("", description="结果消息")
    created_at: str = Field(..., description="执行时间 ISO 格式")


class SqlLogListResult(BaseModel):
    """SQL 日志列表"""

    items: list[SqlLogItem] = Field(..., description="日志列表")
    total: int = Field(..., description="总条数")


class RowUpdateRequest(BaseModel):
    """更新单行"""

    data: dict = Field(..., description="要更新的字段（只写变更列）")


class RowInsertRequest(BaseModel):
    """插入单行"""

    data: dict = Field(..., description="新行字段")


class RowMutationResult(BaseModel):
    """行操作结果"""

    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="结果消息")
    rows_affected: int = Field(0, description="影响行数")


class SqlFileSaveRequest(BaseModel):
    """保存 SQL 文件"""

    name: str = Field(..., min_length=1, description="文件名（如 query-1.sql）")
    content: str = Field("", description="SQL 内容")


class SqlFileItem(BaseModel):
    """后端保存的 SQL 文件"""

    name: str = Field(..., description="文件名")
    content: str = Field("", description="SQL 内容")
    updated_at: float = Field(..., description="更新时间戳")


class SqlFileListResult(BaseModel):
    """SQL 文件列表"""

    items: list[SqlFileItem] = Field(default_factory=list, description="文件列表")
    total: int = Field(0, description="数量")
