"""自定义异常类"""
from typing import Any


class APIException(Exception):
    """API 异常基类"""

    def __init__(self, message: str = "操作失败", code: int = 400, data: Any = None):
        self.message = message
        self.code = code
        self.data = data
        super().__init__(self.message)


class ValidationException(APIException):
    """验证异常"""

    def __init__(self, message: str = "参数验证失败", data: Any = None):
        super().__init__(message=message, code=400, data=data)


class AuthenticationException(APIException):
    """认证异常"""

    def __init__(self, message: str = "认证失败", code: int = 401):
        super().__init__(message=message, code=code)


class PermissionException(APIException):
    """权限异常"""

    def __init__(self, message: str = "权限不足", code: int = 403):
        super().__init__(message=message, code=code)


class NotFoundException(APIException):
    """未找到异常"""

    def __init__(self, message: str = "资源不存在", code: int = 404):
        super().__init__(message=message, code=code)


class SystemException(APIException):
    """系统异常"""

    def __init__(self, message: str = "系统错误", code: int = 500):
        super().__init__(message=message, code=code)


class FileException(APIException):
    """文件操作异常"""

    def __init__(self, message: str = "文件操作失败", code: int = 400):
        super().__init__(message=message, code=code)


class ConfigException(APIException):
    """配置操作异常"""

    def __init__(self, message: str = "配置操作失败", code: int = 400):
        super().__init__(message=message, code=code)
