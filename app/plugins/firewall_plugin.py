# -*- coding: utf-8 -*-
"""
plugins/firewall_plugin.py - Fail2ban 安全防火墙插件
当且仅当配置了 FAIL2BAN_CONTAINER_NAME 时动态激活。
"""

import os
import re
try:
    import docker
except ImportError:
    docker = None
from typing import Dict, Any

CONTAINER_NAME = os.getenv("FAIL2BAN_CONTAINER_NAME", "").strip()
DEFAULT_JAIL = os.getenv("FAIL2BAN_JAIL", "caddy-services").strip()

def is_enabled() -> bool:
    return bool(CONTAINER_NAME)

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
                "description": f"Fail2ban 规则链名称，默认 {DEFAULT_JAIL}",
                "default": DEFAULT_JAIL
            }
        },
        "required": ["action"]
    }
}

def execute(args: Dict[str, Any]) -> Dict[str, Any]:
    if not is_enabled():
        return {"status": "error", "message": "Fail2ban 插件未配置启用，请在 .env 中设置 FAIL2BAN_CONTAINER_NAME"}

    if not docker:
        return {"status": "error", "message": "Docker 模块未就绪"}

    action = args.get("action")
    target_ip = (args.get("ip") or "").strip()
    jail = (args.get("jail") or DEFAULT_JAIL).strip()

    try:
        client = docker.from_env()
        guard = client.containers.get(CONTAINER_NAME)

        if action == "status":
            cmd = f"fail2ban-client status {jail}"
            exec_res = guard.exec_run(cmd)
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
            if not target_ip:
                return {"status": "error", "message": "解封必须提供目标 IP"}
            cmd = f"fail2ban-client set {jail} unbanip {target_ip}"
            exec_res = guard.exec_run(cmd)
            out = exec_res.output.decode("utf-8", errors="replace").strip()
            return {
                "status": "success",
                "target_ip": target_ip,
                "jail": jail,
                "result": out,
                "message": f"IP `{target_ip}` 已在 `{jail}` 规则链中执行解封。"
            }
        return {"status": "error", "message": f"未知动作: {action}"}
    except Exception as e:
        return {"status": "error", "message": f"防火墙指令执行失败: {str(e)}"}
