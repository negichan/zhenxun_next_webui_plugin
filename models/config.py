"""配置相关模型"""
from pydantic import BaseModel, Field


class EnvFileContent(BaseModel):
    """环境变量文件内容"""

    name: str = Field(..., description="文件名称")
    content: str = Field(..., description="文件原始内容")


class YamlConfigContent(BaseModel):
    """YAML 配置文件内容"""

    file_path: str = Field(..., description="文件路径")
    content: str = Field(..., description="YAML 文件原始内容")


class ConfigSaveRequest(BaseModel):
    """配置保存请求"""

    name: str = Field(..., description="文件名称")
    content: str = Field(..., description="文件原始内容")


class YamlConfigSaveRequest(BaseModel):
    """YAML 配置保存请求"""

    file_path: str = Field(..., description="文件路径")
    content: str = Field(..., description="YAML 文件原始内容")


class PluginConfigSaveRequest(BaseModel):
    """插件配置保存请求"""

    module: str = Field(..., description="插件模块名")
    configs: dict[str, str] = Field(..., description="配置键值对字典")


class ConfigValueSetRequest(BaseModel):
    """设置配置值请求"""

    module: str = Field(..., description="模块名")
    key: str = Field(..., description="配置键")
    value: str = Field(..., description="配置值")
