"""实验性协议扩展与劫持模块"""
from .claude import ClaudeAdapter
from .hijack import HijackedAdapterProxy, ProtocolHijackManager
from .manager import get_hijack_manager, install_protocol_hijack

__all__ = [
    "ClaudeAdapter",
    "HijackedAdapterProxy",
    "ProtocolHijackManager",
    "get_hijack_manager",
    "install_protocol_hijack",
]
