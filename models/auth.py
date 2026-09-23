"""认证相关模型"""
from pydantic import BaseModel, Field


class User(BaseModel):
    """用户模型"""
    username: str


class LoginRequest(BaseModel):
    """登录请求"""
    username: str = Field(..., max_length=64, description="用户名")
    password: str = Field(..., max_length=128, description="密码")


class LoginResponse(BaseModel):
    """登录响应"""
    access_token: str = Field(..., description="访问令牌")
    token_type: str = Field(default="bearer", description="令牌类型")
    expires_in: int = Field(default=1800, description="过期时间（秒）")


class TokenRefreshResponse(BaseModel):
    """Token 刷新响应"""
    access_token: str = Field(..., description="新的访问令牌")
    token_type: str = Field(default="bearer", description="令牌类型")
    expires_in: int = Field(default=1800, description="过期时间（秒）")
