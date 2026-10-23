# -*- coding: utf-8 -*-
"""
plugins/firewall_plugin.py - Fail2ban 安全防火墙插件
当且仅当配置了 FAIL2BAN_CONTAINER_NAME 时动态激活。
"""

import os
import re
import ipaddress
try:
    from app.docker_client import get_docker_client
except ImportError:
    try:
        from docker_client import get_docker_client
    except ImportError:
        def get_docker_client():
            return None
from typing import Dict, Any

try:
    from app.config import settings
except ImportError:
    from config import settings

def get_container_name() -> str:
    return os.getenv("FAIL2BAN_CONTAINER_NAME", settings.fail2ban_container_name).strip()

def get_default_jail() -> str:
    return os.getenv("FAIL2BAN_JAIL", settings.fail2ban_jail).strip()

def is_enabled() -> bool:
    return bool(get_container_name())

TOOL_SPEC = {
    "name": "manage_firewall_security",
    "description": "检查与维护 Fail2ban 入侵防御防火墙（查询当前封禁 IP 列表与误封 IP 一键解封）。",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "unban"],
                "description": "操作类型：status(查看封禁列表与统计), unban(解封指定 IP)"
            },
            "ip": {
                "type": "string",
                "description": "待解封的目标 IPv4 或 IPv6 地址（action 为 unban 时必填）"
            },
            "jail": {
                "type": "string",
                "description": "Fail2ban 规则链名称，默认读取系统配置 (如 caddy-services)",
                "default": "caddy-services"
            }
        },
        "required": ["action"]
    }
}

JAIL_PATTERN = re.compile(r'^[a-zA-Z0-9_\-]+$')

def execute(args: Dict[str, Any]) -> Dict[str, Any]:
    container_name = get_container_name()
    if not container_name:
        return {"status": "error", "message": "Fail2ban 插件未配置启用，请在 .env 中设置 FAIL2BAN_CONTAINER_NAME"}

    action = args.get("action")
    raw_ip = (args.get("ip") or "").strip()
    jail = (args.get("jail") or get_default_jail()).strip()

    # 防注入校验：jail 名称白名单
    if not JAIL_PATTERN.match(jail):
        return {"status": "error", "message": f"非法 jail 名称: `{jail}`，仅允许字母、数字、下划线及横杠"}

    validated_ip = None
    if action == "unban":
        if not raw_ip:
            return {"status": "error", "message": "解封必须提供目标 IP"}
        try:
            validated_ip = str(ipaddress.ip_address(raw_ip))
        except ValueError:
            return {"status": "error", "message": f"目标 IP 格式非法: `{raw_ip}`"}

    client = get_docker_client()
    if not client:
        return {"status": "error", "message": "Docker 模块未就绪或未运行"}

    try:
        guard = client.containers.get(container_name)

        if action == "status":
            # 以 list 传参，严禁 shell 字符串插值执行
            exec_res = guard.exec_run(["fail2ban-client", "status", jail])
            out = exec_res.output.decode("utf-8", errors="replace")
            
            banned_match = re.search(r'Banned IP list:\s*(.*)', out)
            banned_ips = banned_match.group(1).strip().split() if banned_match else []
            
            return {
                "status": "success",
                "jail": jail,
                "banned_count": len(banned_ips),
                "banned_ips": banned_ips
            }
        elif action == "unban":
            exec_res = guard.exec_run(["fail2ban-client", "set", jail, "unbanip", validated_ip])
            out = exec_res.output.decode("utf-8", errors="replace").strip()
            return {
                "status": "success",
                "target_ip": validated_ip,
                "jail": jail,
                "result": out,
                "message": f"IP `{validated_ip}` 已在 `{jail}` 规则链中执行解封。"
            }
        return {"status": "error", "message": f"未知动作: {action}"}
    except Exception as e:
        return {"status": "error", "message": f"防火墙指令执行失败: {str(e)}"}


try:
    from app.plugins.base import BasePlugin
except ImportError:
    from plugins.base import BasePlugin


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

