# -*- coding: utf-8 -*-
"""
plugins/aria2_plugin.py - Aria2 离线下载扩展插件
当且仅当配置了 ARIA2_RPC_URL 时动态激活。
"""

import os
import urllib.parse
import ipaddress
import requests
from typing import Dict, Any

try:
    from app.config import settings
except ImportError:
    from config import settings

def get_rpc_url() -> str:
    return os.getenv("ARIA2_RPC_URL", settings.aria2_rpc_url).strip()

def get_rpc_secret() -> str:
    return os.getenv("ARIA2_RPC_SECRET", settings.aria2_rpc_secret).strip()

def is_enabled() -> bool:
    return bool(get_rpc_url())

BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}

def validate_download_url(url: str) -> tuple[bool, str]:
    """校验下载链接，防止协议注入与内网 SSRF 探测"""
    if not url:
        return False, "必须提供下载链接 (url)"
    
    if url.startswith("magnet:?"):
        return True, ""
        
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as e:
        return False, f"下载链接解析异常: {e}"
        
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https", "ftp"):
        return False, f"安全拦截：不支持的下载协议 `{scheme}`，仅支持 HTTP/HTTPS/FTP 与 magnet 链接"
        
    hostname = parsed.hostname
    if not hostname:
        return False, "下载链接未包含有效的目标主机地址"
        
    if hostname.lower() in BLOCKED_HOSTS:
        return False, f"安全拦截：禁止向本地回环主机 `{hostname}` 发起离线下载"
        
    try:
        ip_obj = ipaddress.ip_address(hostname)
        if ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_unspecified:
            return False, f"安全拦截：禁止向内部保留地址 `{hostname}` 发起离线下载"
    except ValueError:
        pass
        
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
    url = (args.get("url") or "").strip()
    gid = (args.get("gid") or "").strip()

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
        res = rpc_call("aria2.addUri", [[url]])
        if isinstance(res, dict) and "error" in res:
            return {"status": "error", "message": res["error"]}
        return {"status": "success", "gid": res, "message": "已成功将任务提交至 Aria2 队列。"}
    elif action == "pause":
        if not gid:
            return {"status": "error", "message": "必须提供任务 GID"}
        return {"status": "success", "result": rpc_call("aria2.pause", [gid])}
    elif action == "unpause":
        if not gid:
            return {"status": "error", "message": "必须提供任务 GID"}
        return {"status": "success", "result": rpc_call("aria2.unpause", [gid])}
    return {"status": "error", "message": f"未知动作: {action}"}
