# -*- coding: utf-8 -*-
"""
plugins/aria2_plugin.py - Aria2 离线下载扩展插件
当且仅当配置了 ARIA2_RPC_URL 时动态激活。
"""

import os
import requests
from typing import Dict, Any
from app.config import settings
from app.url_security import validate_public_url
from app.plugins.base import BasePlugin

def get_rpc_url() -> str:
    return os.getenv("ARIA2_RPC_URL", settings.aria2_rpc_url).strip()

def get_rpc_secret() -> str:
    return os.getenv("ARIA2_RPC_SECRET", settings.aria2_rpc_secret).strip()

def is_enabled() -> bool:
    return bool(get_rpc_url())

def validate_download_url(url: str) -> tuple[bool, str]:
    """拒绝本地/保留地址；任意磁力链接仍由 aria2 自行解析 peer。"""
    if not url:
        return False, "必须提供下载链接 (url)"

    if url.lower().startswith("magnet:?"):
        return False, "安全拦截：磁力链接可连接任意 peer，当前部署无法可靠限制其目标地址"

    allowed, message = validate_public_url(url, schemes=("http", "https"))
    if not allowed:
        return False, f"安全拦截：{message}"
    return True, ""

TOOL_SPEC = {
    "name": "manage_aria2_download",
    "description": "管理 NAS 上的 Aria2 离线下载引擎（支持查询即时下载列表/速度、添加 HTTP/磁力链接等）。",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "add", "pause", "unpause"],
                "description": "操作类型：status(查询任务与速度), add(添加下载链接), pause(暂停任务), unpause(恢复任务)"
            },
            "url": {
                "type": "string",
                "description": "下载资源的 HTTP/HTTPS/FTP 链接或 magnet: 磁力链接（action 为 add 时必填）"
            },
            "gid": {
                "type": "string",
                "description": "任务 GID（action 为 pause/unpause 时必填）"
            }
        },
        "required": ["action"]
    }
}

def format_bytes(size):
    try:
        size = float(size)
    except Exception:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"

def rpc_call(method, params=None):
    if params is None:
        params = []
    rpc_url = get_rpc_url()
    rpc_secret = get_rpc_secret()
    if not rpc_url:
        return {"error": "Aria2 RPC 地址未配置"}

    full_params = [f"token:{rpc_secret}"] + params if rpc_secret else params
    payload = {
        "jsonrpc": "2.0",
        "id": "nas_butler",
        "method": method,
        "params": full_params
    }
    try:
        resp = requests.post(rpc_url, json=payload, timeout=5)
        data = resp.json()
        if "error" in data:
            return {"error": data["error"].get("message", str(data["error"]))}
        return data.get("result")
    except Exception as e:
        return {"error": f"Aria2 RPC 连接失败: {str(e)}"}

def execute(args: Dict[str, Any]) -> Dict[str, Any]:
    if not is_enabled():
        return {"status": "error", "message": "Aria2 插件未配置启用，请在 .env 中设置 ARIA2_RPC_URL"}
    
    action = args.get("action")
    if action != "status":
        return {
            "status": "error",
            "message": "安全策略仅允许查询 Aria2 状态；新增、暂停和恢复任务当前禁用。",
        }

    if action == "status":
        active = rpc_call("aria2.tellActive", [["gid", "status", "totalLength", "completedLength", "downloadSpeed", "files"]])
        stat = rpc_call("aria2.getGlobalStat")
        speed_str = format_bytes(stat.get("downloadSpeed", 0)) + "/s" if isinstance(stat, dict) else "0 B/s"
        return {
            "status": "success",
            "global_download_speed": speed_str,
            "active_tasks": active if isinstance(active, list) else []
        }
    elif action == "add":
        is_valid, err_msg = validate_download_url(url)
        if not is_valid:
            return {"status": "error", "message": err_msg}
        return {
            "status": "error",
            "message": "安全策略暂时禁用新增下载：Aria2 会自行解析 DNS 并跟随重定向，无法保证最终目标仍是公网地址。",
        }
    return {"status": "error", "message": f"未知动作: {action}"}


class Aria2Plugin(BasePlugin):
    """Aria2 离线下载插件类实现"""

    @property
    def name(self) -> str:
        return "manage_aria2_download"

    @property
    def tool_spec(self) -> Dict[str, Any]:
        return TOOL_SPEC

    def is_enabled(self) -> bool:
        return is_enabled()

    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return execute(args)

