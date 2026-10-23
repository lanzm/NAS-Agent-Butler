# -*- coding: utf-8 -*-
"""
plugins/pc_power_plugin.py - 局域网 PC 电源管理扩展插件 (WOL 唤醒与远程关机)
当且仅当 ENABLE_PC_POWER=true 时动态激活。
"""

import os
import socket
import subprocess
from typing import Dict, Any

try:
    from app.config import settings
except ImportError:
    from config import settings

def is_enabled() -> bool:
    enabled = os.getenv("ENABLE_PC_POWER", "").strip().lower() == "true" if "ENABLE_PC_POWER" in os.environ else settings.enable_pc_power
    mac = os.getenv("TARGET_PC_MAC", settings.target_pc_mac).strip()
    return enabled and bool(mac)

TOOL_SPEC = {
    "name": "manage_pc_power",
    "description": "通过局域网唤醒（WOL）开机，或经由 SSH 对目标电脑执行远程休眠/关机。",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["wake", "sleep", "shutdown"],
                "description": "操作类型：wake(局域网唤醒开机), sleep(远程休眠/待机), shutdown(远程关机)"
            }
        },
        "required": ["action"]
    }
}

def send_magic_packet(mac_addr: str) -> bool:
    """纯 Python 零依赖跨平台发送 WOL 唤醒魔包"""
    clean_mac = mac_addr.replace(":", "").replace("-", "")
    if len(clean_mac) != 12:
        return False
    data = bytes.fromhex("FF" * 6 + clean_mac * 16)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(data, ("255.255.255.255", 9))
    return True

def execute(args: Dict[str, Any]) -> Dict[str, Any]:
    if not is_enabled():
        return {"status": "error", "message": "PC 电源管理未开启，请在 .env 中设置 ENABLE_PC_POWER=true 并指定 TARGET_PC_MAC"}

    action = args.get("action")

    mac = os.getenv("TARGET_PC_MAC", settings.target_pc_mac).strip()
    ip = os.getenv("TARGET_PC_IP", settings.target_pc_ip).strip()
    user = os.getenv("TARGET_PC_USER", settings.target_pc_user).strip() or "Administrator"
    port_str = os.getenv("TARGET_PC_PORT", "")
    port = int(port_str) if port_str.isdigit() else settings.target_pc_port

    if action == "wake":
        ok = send_magic_packet(mac)
        if ok:
            return {"status": "success", "message": f"已成功向目标 MAC `{mac}` 广播发送 WOL 唤醒魔包。"}
        return {"status": "error", "message": f"无效的 MAC 地址: {mac}"}

    elif action in ["sleep", "shutdown"]:
        if not ip:
            return {"status": "error", "message": "远程关机需要配置 TARGET_PC_IP"}
        
        # 针对 Windows PC 的轻量远程命令
        cmd_str = "rundll32.exe powrprof.dll,SetSuspendState 0,1,0" if action == "sleep" else "shutdown /s /t 10"
        ssh_cmd = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=5",
            "-o", "StrictHostKeyChecking=no",
            "-p", str(port),
            f"{user}@{ip}",
            cmd_str
        ]
        try:
            res = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                return {"status": "success", "message": f"已成功发送远程{'休眠' if action == 'sleep' else '关机'}信号。"}
            return {"status": "error", "message": f"SSH 远程执行失败 (rc={res.returncode}): {res.stderr.strip()}"}
        except Exception as e:
            return {"status": "error", "message": f"远程电源调度异常: {str(e)}"}

    return {"status": "error", "message": f"未知电源动作: {action}"}
