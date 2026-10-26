# -*- coding: utf-8 -*-
"""
plugins/firewall_plugin.py - Fail2ban 安全防火墙插件
为避免通过 Docker exec 扩大 Docker API 权限，该插件在只读 socket 代理方案下默认禁用。
"""

from typing import Dict, Any
from app.plugins.base import BasePlugin

def is_enabled() -> bool:
    """Fail2ban is disabled until a least-privilege API replaces Docker exec."""
    return False

TOOL_SPEC = {
    "name": "manage_firewall_security",
    "description": "Fail2ban 管理当前因需要 Docker exec 权限而禁用。",
    "parameters": {"type": "object", "properties": {}, "required": []}
}


def execute(args: Dict[str, Any]) -> Dict[str, Any]:
    return {"status": "error", "message": "Fail2ban Docker exec 已因最小权限策略禁用。"}


class FirewallPlugin(BasePlugin):
    """Fail2ban 防火墙入侵防御插件类实现"""

    @property
    def name(self) -> str:
        return "manage_firewall_security"

    @property
    def tool_spec(self) -> Dict[str, Any]:
        return TOOL_SPEC

    def is_enabled(self) -> bool:
        return is_enabled()

    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return execute(args)

