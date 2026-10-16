# -*- coding: utf-8 -*-
"""
plugins/aria2_plugin.py - Aria2 离线下载扩展插件
当且仅当配置了 ARIA2_RPC_URL 时动态激活。
"""

import os
import requests
from typing import Dict, Any

RPC_URL = os.getenv("ARIA2_RPC_URL", "").strip()
RPC_SECRET = os.getenv("ARIA2_RPC_SECRET", "").strip()

def is_enabled() -> bool:
    return bool(RPC_URL)

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
    full_params = [f"token:{RPC_SECRET}"] + params if RPC_SECRET else params
    payload = {
        "jsonrpc": "2.0",
        "id": "nas_butler",
        "method": method,
        "params": full_params
    }
    try:
        resp = requests.post(RPC_URL, json=payload, timeout=5)
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
        if not url:
            return {"status": "error", "message": "必须提供下载链接 (url)"}
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
