"""数据库路由"""
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from ..dependencies import AuthenticatedUser
from ..models.database import (
    RowInsertRequest,
    RowMutationResult,
    RowUpdateRequest,
    SqlExecuteRequest,
    SqlExecuteResult,
    SqlFileItem,
    SqlFileListResult,
    SqlFileSaveRequest,
    SqlLogListResult,
    TableDataResult,
)
from ..responses import APIResponse, error_response, success_response
from ..services.database_service import DatabaseService

router = APIRouter(prefix="/database", tags=["数据库"])


@router.get(
    "/tables",
    response_model=APIResponse[list[str]],
    response_class=JSONResponse,
    summary="获取表列表",
)
async def get_table_list(user: AuthenticatedUser) -> APIResponse[list[str]]:
    """获取数据库表列表"""
    result = await DatabaseService.get_table_list()
    return success_response(data=result)


@router.get(
    "/tables/{table_name}/columns",
    response_model=APIResponse[list[dict]],
    response_class=JSONResponse,
    summary="获取表字段",
)
async def get_table_columns(
    user: AuthenticatedUser, table_name: str
) -> APIResponse[list[dict]]:
    """获取指定表的字段列表"""
    result = await DatabaseService.get_table_columns(table_name)
    return success_response(data=result)


@router.get(
    "/tables/{table_name}/data",
    response_model=APIResponse[TableDataResult],
    response_class=JSONResponse,
    summary="获取表数据",
)
async def get_table_data(
    user: AuthenticatedUser,
    table_name: str,
    page: int = 1,
    page_size: int = 50,
) -> APIResponse[TableDataResult]:
    """获取指定表的数据"""
    result = await DatabaseService.get_table_data(table_name, page, page_size)
    return success_response(data=result)


@router.post(
    "/execute",
    response_model=APIResponse[SqlExecuteResult],
    response_class=JSONResponse,
    summary="执行 SQL",
)
async def execute_sql(
    user: AuthenticatedUser, request: SqlExecuteRequest
) -> APIResponse[SqlExecuteResult]:
    """执行 SQL 查询"""
    try:
        result = await DatabaseService.execute_sql(request)
        return success_response(data=result)
    except Exception as e:
        # SQL 执行错误，返回 400
        return error_response(
            message=f"SQL 执行错误：{e!s}",
            code=400,
            data=SqlExecuteResult(
                success=False,
                message=f"SQL 执行错误：{e!s}",
                data=None,
                rows_affected=None,
            ),
        )


@router.get(
    "/sql-logs",
    response_model=APIResponse[SqlLogListResult],
    response_class=JSONResponse,
    summary="获取 SQL 执行日志",
)
async def get_sql_logs(
    user: AuthenticatedUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> APIResponse[SqlLogListResult]:
    """获取最近的 SQL 执行日志（倒序）"""
    result = DatabaseService.get_sql_logs(page, page_size)
    return success_response(data=result)


@router.get(
    "/sql-files",
    response_model=APIResponse[SqlFileListResult],
    response_class=JSONResponse,
    summary="获取 SQL 编辑器文件列表",
)
async def list_sql_files(user: AuthenticatedUser) -> APIResponse[SqlFileListResult]:
    """侧栏 SQL 目录 — 后端持久化文件列表"""
    return success_response(data=DatabaseService.list_sql_files())


@router.post(
    "/sql-files",
    response_model=APIResponse[SqlFileItem],
    response_class=JSONResponse,
    summary="新建/保存 SQL 文件",
)
async def save_sql_file(
    user: AuthenticatedUser, request: SqlFileSaveRequest
) -> APIResponse[SqlFileItem]:
    try:
        return success_response(data=DatabaseService.save_sql_file(request))
    except Exception as e:
        return error_response(message=f"保存 SQL 文件失败：{e!s}", code=400)


@router.delete(
    "/sql-files/{name}",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="删除 SQL 文件",
)
async def delete_sql_file(user: AuthenticatedUser, name: str) -> APIResponse[bool]:
    try:
        ok = DatabaseService.delete_sql_file(name)
        if not ok:
            return error_response(message="文件不存在", code=404)
        return success_response(data=True)
    except Exception as e:
        return error_response(message=f"删除 SQL 文件失败：{e!s}", code=400)


@router.patch(
    "/tables/{table_name}/rows/{row_id}",
    response_model=APIResponse[RowMutationResult],
    response_class=JSONResponse,
    summary="更新单行",
)
async def update_row(
    user: AuthenticatedUser,
    table_name: str,
    row_id: str,
    request: RowUpdateRequest,
) -> APIResponse[RowMutationResult]:
    """按主键更新单行"""
    try:
        result = await DatabaseService.update_row(table_name, row_id, request)
        return success_response(data=result)
    except Exception as e:
        return error_response(message=f"更新失败：{e!s}", code=400)


@router.delete(
    "/tables/{table_name}/rows/{row_id}",
    response_model=APIResponse[RowMutationResult],
    response_class=JSONResponse,
    summary="删除单行",
)
async def delete_row(
    user: AuthenticatedUser,
    table_name: str,
    row_id: str,
) -> APIResponse[RowMutationResult]:
    """按主键删除单行"""
    try:
        result = await DatabaseService.delete_row(table_name, row_id)
        return success_response(data=result)
    except Exception as e:
        return error_response(message=f"删除失败：{e!s}", code=400)


@router.post(
    "/tables/{table_name}/rows",
    response_model=APIResponse[RowMutationResult],
    response_class=JSONResponse,
    summary="插入单行",
)
async def insert_row(
    user: AuthenticatedUser,
    table_name: str,
    request: RowInsertRequest,
) -> APIResponse[RowMutationResult]:
    """插入单行"""
    try:
        result = await DatabaseService.insert_row(table_name, request)
        return success_response(data=result)
    except Exception as e:
        return error_response(message=f"插入失败：{e!s}", code=400)
