"""路径验证工具"""
from pathlib import Path
import re

DANGEROUS_CHARS = ["..", "~", "*", "?", ">", "<", "|", '"', "\0"]
MAX_PATH_LENGTH = 4096


def validate_path_secure(
    path_str: str | None, root_dir: Path | None = None
) -> tuple[Path | None, str | None]:
    """安全的路径验证函数"""
    if root_dir is None:
        root_dir = Path().resolve()

    try:
        if not path_str:
            return root_dir, None

        # 移除路径遍历尝试
        path_str = re.sub(r"[\\/]\.\.[\\/]", "", path_str)

        # 规范化路径
        path = Path(path_str).resolve()

        # 检查符号链接攻击
        if path.is_symlink():
            real_path = path.resolve()
            try:
                real_path.relative_to(root_dir)
            except ValueError:
                return None, "符号链接指向不允许的位置"

        # 验证路径是否在根目录内
        try:
            path.relative_to(root_dir)
        except ValueError:
            return None, "访问路径超出允许范围"

        # 验证危险字符和长度
        if any(c in str(path) for c in DANGEROUS_CHARS):
            return None, "路径包含非法字符"

        if len(str(path)) > MAX_PATH_LENGTH:
            return None, "路径长度超出限制"

        return path, None
    except Exception as e:
        return None, f"路径验证失败：{e!s}"


def generate_path_segments(path: str) -> list[str]:
    """生成面包屑导航路径段"""
    if not path:
        return []
    # Windows 下 str(Path) 是反斜杠分隔，统一归一后再分段
    return [p for p in path.replace("\\", "/").split("/") if p]
