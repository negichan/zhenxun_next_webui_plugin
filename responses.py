"""统一响应模型"""
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """统一 API 响应格式"""

    success: bool
    message: str
    code: int
    data: T | None = None


class PageData(BaseModel, Generic[T]):
    """分页数据"""

    items: list[T]
    total: int
    page: int
    page_size: int
    has_next: bool
    has_prev: bool


def success_response(data: T | None = None, message: str = "操作成功", code: int = 200) -> APIResponse[T]:
    """成功响应"""
    return APIResponse(success=True, message=message, code=code, data=data)


def error_response(message: str = "操作失败", code: int = 400, data: Any = None) -> APIResponse:
    """错误响应"""
    return APIResponse(success=False, message=message, code=code, data=data)
