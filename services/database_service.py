"""数据库服务"""
from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time

from tortoise import Tortoise

from zhenxun.configs.config import BotConfig
from zhenxun.services.log import logger

from ..exceptions import SystemException, ValidationException
from ..models.database import (
    RowInsertRequest,
    RowMutationResult,
    RowUpdateRequest,
    SqlExecuteRequest,
    SqlExecuteResult,
    SqlFileItem,
    SqlFileListResult,
    SqlFileSaveRequest,
    SqlLogItem,
    SqlLogListResult,
    TableDataResult,
    TableRowData,
)

# SQL 类型映射
type2sql = {
    "sqlite": "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
    "mysql": "SHOW TABLES",
    "postgres": (
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' ORDER BY table_name"
    ),
}

# 内存 SQL 日志（最近 200 条），足够管理员排障
_SQL_LOG_MAX = 200
_sql_logs: deque[SqlLogItem] = deque(maxlen=_SQL_LOG_MAX)
_sql_log_seq = 0

# SQL 编辑器文件：持久化到 Bot 数据目录（非浏览器 localStorage）
_SQL_FILE_RE = re.compile(r"^[A-Za-z0-9_\-]+\.(sql|SQL)$")

# 标识符白名单：字母/下划线开头，只含字母数字下划线
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote_ident(name: str) -> str:
    """安全引用标识符（表名/列名）"""
    if not name or not _IDENT_RE.match(name):
        raise ValidationException(f"非法标识符：{name!r}")
    sql_type = BotConfig.get_sql_type()
    if sql_type == "mysql":
        return f"`{name}`"
    return f'"{name}"'


def _get_primary_key(columns: list[dict]) -> str | None:
    for col in columns:
        if col.get("primary_key"):
            return col.get("name")
    return None


def _sql_files_path() -> Path:
    return Path() / "data" / "webui" / "sql_files.json"


def _load_sql_files() -> list[SqlFileItem]:
    path = _sql_files_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        items = []
        for row in raw if isinstance(raw, list) else []:
            if not isinstance(row, dict) or not row.get("name"):
                continue
            items.append(
                SqlFileItem(
                    name=str(row["name"]),
                    content=str(row.get("content", "")),
                    updated_at=float(row.get("updated_at", 0)),
                )
            )
        return items
    except Exception as e:
        logger.warning(f"读取 SQL 文件列表失败: {e}", "WebUi")
        return []


def _save_sql_files(items: list[SqlFileItem]) -> None:
    path = _sql_files_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [i.model_dump() for i in items]
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _append_sql_log(
    sql: str, is_success: bool, message: str = ""
) -> None:
    global _sql_log_seq
    _sql_log_seq += 1
    _sql_logs.appendleft(
        SqlLogItem(
            id=_sql_log_seq,
            sql=sql,
            is_success=is_success,
            message=message,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    )


class DatabaseService:
    """数据库服务"""

    @staticmethod
    async def get_table_list() -> list[str]:
        """获取表列表

        返回:
            list[str]: 表名列表
        """
        try:
            db = Tortoise.get_connection("default")
            sql_type = BotConfig.get_sql_type()
            sql = type2sql.get(sql_type)
            if not sql:
                raise ValidationException(f"不支持的数据库类型：{sql_type}")

            query = await db.execute_query_dict(sql)
            return [next(iter(row.values())) for row in query]
        except Exception as e:
            raise SystemException(f"获取表列表失败：{e!s}")

    @staticmethod
    async def get_table_columns(table_name: str) -> list[dict]:
        """获取表字段

        参数:
            table_name: 表名

        返回:
            list[dict]: 字段列表，包含 name, type, nullable, default, primary_key
        """
        try:
            db = Tortoise.get_connection("default")
            sql_type = BotConfig.get_sql_type()

            columns = []
            if sql_type == "sqlite":
                sql = f"PRAGMA table_info({table_name})"
                query = await db.execute_query_dict(sql)
                for row in query:
                    columns.append(
                        {
                            "name": row.get("name", ""),
                            "type": row.get("type", ""),
                            "nullable": row.get("notnull", 0) == 0,
                            "default": row.get("dflt_value"),
                            "primary_key": row.get("pk", 0) == 1,
                        }
                    )
            elif sql_type == "mysql":
                sql = f"SHOW COLUMNS FROM {table_name}"
                query = await db.execute_query_dict(sql)
                for row in query:
                    columns.append(
                        {
                            "name": row.get("Field", ""),
                            "type": row.get("Type", ""),
                            "nullable": row.get("Null", "") == "YES",
                            "default": row.get("Default"),
                            "primary_key": row.get("Key", "") == "PRI",
                        }
                    )
            elif sql_type == "postgres":
                sql = """
                    SELECT
                        column_name,
                        data_type,
                        is_nullable,
                        column_default,
                        CASE
                            WHEN pk.col_name IS NOT NULL
                            THEN true ELSE false
                        END as is_primary
                    FROM information_schema.columns
                    LEFT JOIN (
                        SELECT kcu.column_name as col_name
                        FROM information_schema.table_constraints tco
                        JOIN information_schema.key_column_usage kcu
                            ON tco.constraint_name = kcu.constraint_name
                        WHERE tco.constraint_type = 'PRIMARY KEY'
                        AND tco.table_name = '{table_name}'
                    ) pk ON information_schema.columns.column_name = pk.col_name
                    WHERE information_schema.columns.table_name = '{table_name}'
                    ORDER BY ordinal_position
                """
                query = await db.execute_query_dict(sql)
                for row in query:
                    columns.append(
                        {
                            "name": row.get("column_name", ""),
                            "type": row.get("data_type", ""),
                            "nullable": row.get("is_nullable", "NO") == "YES",
                            "default": row.get("column_default"),
                            "primary_key": row.get("is_primary", False),
                        }
                    )
            else:
                raise ValidationException(f"不支持的数据库类型：{sql_type}")

            return columns
        except Exception as e:
            raise SystemException(f"获取表字段失败：{e!s}")

    @staticmethod
    async def get_table_data(
        table_name: str, page: int = 1, page_size: int = 50
    ) -> TableDataResult:
        """获取表数据

        参数:
            table_name: 表名
            page: 页码
            page_size: 每页数量

        返回:
            TableDataResult: 表数据结果
        """
        try:
            # 获取模型类
            model_cls = Tortoise.apps["models"].get(table_name)
            if not model_cls:
                # 尝试从其他 app 获取
                for app_name, app_models in Tortoise.apps.items():
                    if table_name in app_models:
                        model_cls = app_models[table_name]
                        break

            if not model_cls:
                # 如果没有对应的模型，使用通用查询
                db = Tortoise.get_connection("default")
                sql_type = BotConfig.get_sql_type()

                # 获取总数
                count_sql = f"SELECT COUNT(*) as count FROM {table_name}"
                count_result = await db.execute_query_dict(count_sql)
                total = count_result[0]["count"] if count_result else 0

                # 获取数据
                offset = (page - 1) * page_size
                if sql_type == "sqlite":
                    data_sql = (
                        f"SELECT * FROM {table_name} LIMIT {page_size} OFFSET {offset}"
                    )
                elif sql_type == "mysql":
                    data_sql = (
                        f"SELECT * FROM {table_name} LIMIT {offset}, {page_size}"
                    )
                elif sql_type == "postgres":
                    data_sql = (
                        f"SELECT * FROM {table_name} LIMIT {page_size} OFFSET {offset}"
                    )
                else:
                    raise ValidationException(f"不支持的数据库类型：{sql_type}")

                data = await db.execute_query_dict(data_sql)

                items = []
                for i, row in enumerate(data):
                    items.append(
                        TableRowData(
                            id=row.get("id", i),
                            data=row,
                        )
                    )

                return TableDataResult(
                    items=items,
                    total=total,
                    page=page,
                    page_size=page_size,
                    has_next=offset + len(data) < total,
                    has_prev=page > 1,
                )

            # 使用模型查询
            total = await model_cls.all().count()
            offset = (page - 1) * page_size
            data = await model_cls.all().limit(page_size).offset(offset)

            items = []
            for i, row in enumerate(data):
                row_data = row.to_dict() if hasattr(row, "to_dict") else row.__dict__
                items.append(
                    TableRowData(
                        id=getattr(row, "id", i),
                        data=row_data,
                    )
                )

            return TableDataResult(
                items=items,
                total=total,
                page=page,
                page_size=page_size,
                has_next=offset + len(items) < total,
                has_prev=page > 1,
            )
        except Exception as e:
            raise SystemException(f"获取表数据失败：{e!s}")

    @staticmethod
    async def execute_sql(request: SqlExecuteRequest) -> SqlExecuteResult:
        """执行 SQL

        参数:
            request: SQL 请求

        返回:
            SqlExecuteResult: 执行结果
        """
        db = Tortoise.get_connection("default")
        sql = request.sql.strip()

        # 判断是否为查询语句
        sql_lower = sql.lower()
        is_query = sql_lower.startswith(
            ("select", "show", "describe", "explain", "pragma")
        )

        try:
            if is_query:
                # 查询语句返回结果数据
                result = await db.execute_query_dict(sql)
                message = f"查询成功，返回 {len(result)} 行"
                _append_sql_log(sql, True, message)
                return SqlExecuteResult(
                    success=True,
                    message=message,
                    data=result,
                    rows_affected=len(result),
                )

            # 非查询语句（INSERT、UPDATE、DELETE、CREATE、DROP 等）返回影响行数
            rows_affected = await db.execute_query(sql)
            affected = rows_affected[0] if rows_affected else 0
            message = f"执行成功，影响 {affected} 行"
            _append_sql_log(sql, True, message)
            return SqlExecuteResult(
                success=True,
                message=message,
                data=None,
                rows_affected=affected,
            )
        except Exception as e:
            _append_sql_log(sql, False, str(e))
            raise

    @staticmethod
    def get_sql_logs(page: int = 1, page_size: int = 50) -> SqlLogListResult:
        """获取 SQL 执行日志（倒序）

        参数:
            page: 页码，从 1 开始
            page_size: 每页数量

        返回:
            SqlLogListResult: 分页日志
        """
        total = len(_sql_logs)
        start = (page - 1) * page_size
        items = list(_sql_logs)[start : start + page_size]
        return SqlLogListResult(items=items, total=total)

    # ==================== SQL 编辑器文件（后端持久化） ====================

    @staticmethod
    def list_sql_files() -> SqlFileListResult:
        items = _load_sql_files()
        return SqlFileListResult(items=items, total=len(items))

    @staticmethod
    def save_sql_file(request: SqlFileSaveRequest) -> SqlFileItem:
        name = request.name.strip()
        if not name.endswith(".sql"):
            name = f"{name}.sql"
        if not _SQL_FILE_RE.match(name):
            raise ValidationException(
                f"非法文件名：{request.name}（仅字母数字下划线连字符 + .sql）"
            )
        items = _load_sql_files()
        now = time.time()
        item = SqlFileItem(name=name, content=request.content, updated_at=now)
        idx = next((i for i, x in enumerate(items) if x.name == name), None)
        if idx is None:
            items.insert(0, item)
        else:
            items[idx] = item
        _save_sql_files(items)
        return item

    @staticmethod
    def delete_sql_file(name: str) -> bool:
        items = _load_sql_files()
        remain = [x for x in items if x.name != name]
        if len(remain) == len(items):
            return False
        _save_sql_files(remain)
        return True

    @staticmethod
    async def _require_pk(table_name: str) -> tuple[str, list[dict]]:
        """校验表存在且有主键，返回 (pk_name, columns)"""
        columns = await DatabaseService.get_table_columns(table_name)
        pk = _get_primary_key(columns)
        if not pk:
            raise ValidationException(f"表 {table_name} 没有主键，无法按行编辑")
        return pk, columns

    @staticmethod
    async def update_row(
        table_name: str, row_id: str | int, request: RowUpdateRequest
    ) -> RowMutationResult:
        """按主键更新单行（只更新 data 中出现的字段）"""
        if not request.data:
            raise ValidationException("没有需要更新的字段")

        pk_name, columns = await DatabaseService._require_pk(table_name)
        allowed = {c["name"] for c in columns}

        sets: list[str] = []
        values: list = []
        preview_parts: list[str] = []
        for key, value in request.data.items():
            if key not in allowed:
                raise ValidationException(f"未知字段：{key}")
            if key == pk_name:
                continue  # 不允许通过此接口改主键
            sets.append(f"{_quote_ident(key)} = ?")
            values.append(value)
            preview_parts.append(f"{key}={value!r}")

        if not sets:
            raise ValidationException("没有可更新的字段")

        table_q = _quote_ident(table_name)
        pk_q = _quote_ident(pk_name)
        sql = f"UPDATE {table_q} SET {', '.join(sets)} WHERE {pk_q} = ?"
        values.append(row_id)

        try:
            db = Tortoise.get_connection("default")
            result = await db.execute_query(sql, values)
            affected = result[0] if result else 0
            message = f"已更新 {affected} 行（{', '.join(preview_parts)}）"
            _append_sql_log(f"{sql} -- {row_id!r}", True, message)
            return RowMutationResult(
                success=True, message=message, rows_affected=affected
            )
        except ValidationException:
            raise
        except Exception as e:
            _append_sql_log(sql, False, str(e))
            raise SystemException(f"更新行失败：{e!s}")

    @staticmethod
    async def delete_row(
        table_name: str, row_id: str | int
    ) -> RowMutationResult:
        """按主键删除单行"""
        pk_name, _ = await DatabaseService._require_pk(table_name)
        table_q = _quote_ident(table_name)
        pk_q = _quote_ident(pk_name)
        sql = f"DELETE FROM {table_q} WHERE {pk_q} = ?"

        try:
            db = Tortoise.get_connection("default")
            result = await db.execute_query(sql, [row_id])
            affected = result[0] if result else 0
            message = f"已删除 {affected} 行"
            _append_sql_log(f"{sql} -- {row_id!r}", True, message)
            return RowMutationResult(
                success=True, message=message, rows_affected=affected
            )
        except Exception as e:
            _append_sql_log(sql, False, str(e))
            raise SystemException(f"删除行失败：{e!s}")

    @staticmethod
    async def insert_row(
        table_name: str, request: RowInsertRequest
    ) -> RowMutationResult:
        """插入单行（字段需来自表结构）"""
        if not request.data:
            raise ValidationException("新行不能为空")

        columns = await DatabaseService.get_table_columns(table_name)
        allowed = {c["name"] for c in columns}
        unknown = [k for k in request.data if k not in allowed]
        if unknown:
            raise ValidationException(f"未知字段：{', '.join(unknown)}")

        table_q = _quote_ident(table_name)
        col_names = list(request.data.keys())
        col_sql = ", ".join(_quote_ident(c) for c in col_names)
        placeholders = ", ".join(["?"] * len(col_names))
        values = [request.data[c] for c in col_names]
        sql = f"INSERT INTO {table_q} ({col_sql}) VALUES ({placeholders})"

        try:
            db = Tortoise.get_connection("default")
            result = await db.execute_query(sql, values)
            affected = result[0] if result else 0
            message = f"已插入 {affected} 行"
            _append_sql_log(sql, True, message)
            return RowMutationResult(
                success=True, message=message, rows_affected=affected
            )
        except Exception as e:
            _append_sql_log(sql, False, str(e))
            raise SystemException(f"插入行失败：{e!s}")
