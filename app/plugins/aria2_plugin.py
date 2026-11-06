# -*- coding: utf-8 -*-
"""
plugins/aria2_plugin.py - Aria2 离线下载扩展插件
当且仅当配置了 ARIA2_RPC_URL 时动态激活。
支持下载状态查询、添加任务（支持 HTTP/HTTPS 与磁力链接 magnet:?）、暂停、恢复及删除任务。
"""

import os
import requests
from typing import Dict, Any, List
from app.config import settings
from app.url_security import validate_public_url
from app.plugins.base import BasePlugin
from app.utils import format_bytes


def get_rpc_url() -> str:
    return settings.aria2_rpc_url


def get_rpc_secret() -> str:
    return settings.aria2_rpc_secret


def is_enabled() -> bool:
    return bool(get_rpc_url())


def validate_download_url(url: str) -> tuple[bool, str]:
    """
    验证下载链接安全性：
    - 允许 magnet 磁力链接 (magnet:?xt=urn:...)
    - 验证公网 HTTP/HTTPS，拦截内网/本地保留地址 (SSRF 防御)
    - 拒绝不支持的文件协议 (file://, ftp:// 等)
    """
    if not url or not isinstance(url, str):
        return False, "必须提供下载链接 (url)"

    url = url.strip()
    if url.lower().startswith("magnet:?"):
        if "xt=urn:" not in url.lower():
            return False, "磁力链接格式非法：缺少 xt 参数"
        return True, ""

    allowed, message = validate_public_url(url, schemes=("http", "https"))
    if not allowed:
        return False, f"安全拦截：{message}"
    return True, ""


TOOL_SPEC = {
    "name": "manage_aria2_download",
    "description": "管理 NAS 上的 Aria2 离线下载任务。支持查看当前下载状态与速度、添加离线下载（支持公网 HTTP/HTTPS 链接与磁力链接 magnet:?）、暂停、恢复或删除任务。注意：当用户询问 Aria2 下载状态、下载进度、还有没有在下载、添加磁力/下载链接、或者管理下载任务时，必须优先调用本工具，严禁使用 docker 日志查询！",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "add", "pause", "unpause", "remove"],
                "description": "操作类型：status(查询任务与速度), add(添加下载任务), pause(暂停任务), unpause(恢复任务), remove(删除任务)"
            },
            "url": {
                "type": "string",
                "description": "下载链接（action 为 add 时必填），支持公网 HTTP/HTTPS 链接或磁力链接 (magnet:?)"
            },
            "gid": {
                "type": "string",
                "description": "任务 GID（action 为 pause/unpause/remove 时必填）"
            }
        },
        "required": ["action"]
    }
}


def rpc_call(method: str, params: list = None) -> Any:
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
        resp = requests.post(rpc_url, json=payload, timeout=8)
        data = resp.json()
        if "error" in data:
            return {"error": data["error"].get("message", str(data["error"]))}
        return data.get("result")
    except Exception as e:
        return {"error": f"Aria2 RPC 连接失败: {str(e)}"}


def _format_tasks(task_list: Any) -> List[Dict[str, Any]]:
    if not isinstance(task_list, list):
        return []
    res = []
    for t in task_list:
        total = int(t.get("totalLength", 0))
        completed = int(t.get("completedLength", 0))
        pct = f"{(completed / total * 100):.1f}%" if total > 0 else "0.0%"

        name = ""
        bt = t.get("bittorrent", {})
        if bt and isinstance(bt, dict) and bt.get("info", {}).get("name"):
            name = bt["info"]["name"]
        elif t.get("files") and len(t["files"]) > 0:
            path = t["files"][0].get("path", "")
            if path:
                name = os.path.basename(path)
            elif t["files"][0].get("uris"):
                name = t["files"][0]["uris"][0].get("uri", "")

        if not name:
            name = f"任务_{t.get('gid', '')}"

        speed = format_bytes(int(t.get("downloadSpeed", 0))) + "/s"
        res.append({
            "gid": t.get("gid"),
            "name": name,
            "status": t.get("status"),
            "progress": pct,
            "size": format_bytes(total),
            "download_speed": speed,
            "error": t.get("errorMessage", "")
        })
    return res


def execute(args: Dict[str, Any]) -> Dict[str, Any]:
    if not is_enabled():
        return {"status": "error", "message": "Aria2 插件未配置启用，请在 .env 中设置 ARIA2_RPC_URL"}

    action = args.get("action")

    if action == "status":
        keys = ["gid", "status", "totalLength", "completedLength", "downloadSpeed", "files", "bittorrent"]
        active = rpc_call("aria2.tellActive", [keys])
        waiting = rpc_call("aria2.tellWaiting", [0, 10, keys])
        stopped = rpc_call("aria2.tellStopped", [0, 10, keys + ["errorMessage"]])
        stat = rpc_call("aria2.getGlobalStat")

        speed_str = format_bytes(int(stat.get("downloadSpeed", 0))) + "/s" if isinstance(stat, dict) else "0 B/s"
        upload_str = format_bytes(int(stat.get("uploadSpeed", 0))) + "/s" if isinstance(stat, dict) else "0 B/s"

        return {
            "status": "success",
            "global_download_speed": speed_str,
            "global_upload_speed": upload_str,
            "active_count": len(active) if isinstance(active, list) else 0,
            "active_tasks": _format_tasks(active),
            "waiting_tasks": _format_tasks(waiting),
            "stopped_tasks": _format_tasks(stopped)
        }

    elif action == "add":
        url = (args.get("url") or "").strip()
        is_valid, err_msg = validate_download_url(url)
        if not is_valid:
            return {"status": "error", "message": err_msg}

        res = rpc_call("aria2.addUri", [[url]])
        if isinstance(res, dict) and "error" in res:
            return {"status": "error", "message": f"添加下载任务失败: {res['error']}"}
        return {
            "status": "success",
            "message": f"成功添加下载任务，GID: {res}",
            "gid": res
        }

    elif action == "pause":
        gid = (args.get("gid") or "").strip()
        if not gid:
            return {"status": "error", "message": "暂停任务必须提供 gid"}
        res = rpc_call("aria2.pause", [gid])
        if isinstance(res, dict) and "error" in res:
            return {"status": "error", "message": f"暂停任务失败: {res['error']}"}
        return {"status": "success", "message": f"已暂停任务 GID: {gid}", "gid": gid}

    elif action == "unpause":
        gid = (args.get("gid") or "").strip()
        if not gid:
            return {"status": "error", "message": "恢复任务必须提供 gid"}
        res = rpc_call("aria2.unpause", [gid])
        if isinstance(res, dict) and "error" in res:
            return {"status": "error", "message": f"恢复任务失败: {res['error']}"}
        return {"status": "success", "message": f"已恢复任务 GID: {gid}", "gid": gid}

    elif action == "remove":
        gid = (args.get("gid") or "").strip()
        if not gid:
            return {"status": "error", "message": "删除任务必须提供 gid"}
        res = rpc_call("aria2.remove", [gid])
        if isinstance(res, dict) and "error" in res:
            # 可能是已经停止的任务，尝试 removeDownloadResult
            res_stop = rpc_call("aria2.removeDownloadResult", [gid])
            if isinstance(res_stop, dict) and "error" in res_stop:
                return {"status": "error", "message": f"删除任务失败: {res['error']}"}
        return {"status": "success", "message": f"已成功删除任务 GID: {gid}", "gid": gid}

    return {"status": "error", "message": f"未知动作: {action}，支持动作为 status, add, pause, unpause, remove"}


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
