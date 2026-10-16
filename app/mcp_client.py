# -*- coding: utf-8 -*-
"""
mcp_client.py - 通用轻量级 MCP Client (stdio 进程管道)
负责：
1. 本地子进程启动、监控与自愈回收；
2. 标准 JSON-RPC 2.0 握手与请求中继；
3. 将 MCP Tools Schema 自动转换为 OpenAI Function Calling 规范；
4. 动态读取 MCP Prompts (如 sre_engineer) 与 Resources。
"""

import sys
import os
import json
import time
import logging
import subprocess
import threading
from typing import Dict, Any, List, Optional

logger = logging.getLogger("feishu-bot.mcp_client")


class MCPClient:
    def __init__(self, server_cmd: Optional[List[str]] = None):
        """
        :param server_cmd: 启动 MCP Server 的命令列表，默认使用当前 Python 运行 nas_mcp_server.py
        """
        if server_cmd is None:
            # 兼容容器环境路径与本地不同层级路径
            possible_paths = [
                "/app/app/nas_mcp_server.py",
                "/app/nas_mcp_server.py",
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "nas_mcp_server.py"),
                os.path.join(os.getcwd(), "app", "nas_mcp_server.py"),
                os.path.join(os.getcwd(), "nas_mcp_server.py"),
            ]
            script_path = None
            for p in possible_paths:
                if os.path.exists(p):
                    script_path = p
                    break
            
            if not script_path:
                script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nas_mcp_server.py")

            server_cmd = [sys.executable, script_path]

        self.server_cmd = server_cmd
        self.process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._request_counter = 0

    def start(self):
        """启动或重启 MCP Server 子进程并完成握手"""
        with self._lock:
            if self.process and self.process.poll() is None:
                return

            logger.info(f"正在启动 MCP Server 进程: {' '.join(self.server_cmd)}")
            self.process = subprocess.Popen(
                self.server_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=sys.stderr,  # Server 日志直接输出至主程序 stderr
                text=True,
                encoding="utf-8",
                bufsize=1
            )
            # 立即发送 initialize 握手报文
            init_payload = {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "clientInfo": {"name": "feishu-bot-agent", "version": "1.0.0"},
                    "capabilities": {}
                }
            }
            resp = self._send_raw(init_payload)
            if not resp or "error" in resp:
                logger.error(f"MCP Server 握手失败: {resp}")
            else:
                logger.info("MCP Server 握手初始化成功！")

    def stop(self):
        """优雅关闭子进程"""
        with self._lock:
            if self.process and self.process.poll() is None:
                try:
                    self.process.terminate()
                    self.process.wait(timeout=3)
                except Exception:
                    self.process.kill()
            self.process = None

    def _next_id(self) -> int:
        self._request_counter += 1
        return self._request_counter

    def _send_raw(self, payload: Dict[str, Any], timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """发送 JSON-RPC 消息并通过管道读取一行回复"""
        if not self.process or self.process.poll() is not None:
            logger.warning("检测到 MCP Server 子进程未运行，尝试重新拉起...")
            self.start()

        if not self.process or not self.process.stdin or not self.process.stdout:
            raise RuntimeError("MCP Server 子进程管道未就绪")

        req_line = json.dumps(payload, ensure_ascii=False) + "\n"
        try:
            self.process.stdin.write(req_line)
            self.process.stdin.flush()

            # 读取单行响应
            resp_line = self.process.stdout.readline()
            if not resp_line:
                logger.error("读取到空响应，MCP Server 可能已退出")
                return None
            return json.loads(resp_line.strip())
        except Exception as e:
            logger.error(f"与 MCP Server 通信出现异常: {e}")
            self.stop()
            return None

    def get_prompt(self, name: str = "sre_engineer", current_time: str = "") -> str:
        """从 MCP Server 动态获取角色设定与提示词"""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "prompts/get",
            "params": {
                "name": name,
                "arguments": {"current_time": current_time} if current_time else {}
            }
        }
        resp = self._send_raw(payload)
        if resp and "result" in resp:
            messages = resp["result"].get("messages", [])
            if messages:
                content = messages[0].get("content", {})
                if isinstance(content, dict):
                    return content.get("text", "")
                return str(content)
        return ""

    def list_tools(self) -> List[Dict[str, Any]]:
        """从 MCP Server 获取原生 Tools 列表"""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
            "params": {}
        }
        resp = self._send_raw(payload)
        if resp and "result" in resp:
            return resp["result"].get("tools", [])
        return []

    def get_openai_tools(self) -> List[Dict[str, Any]]:
        """将 MCP Tools Schema 自动转换映射为 OpenAI 兼容的 Function Calling 格式"""
        mcp_tools = self.list_tools()
        openai_tools = []
        for t in mcp_tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": t.get("name"),
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters", {"type": "object", "properties": {}})
                }
            })
        return openai_tools

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """通过 MCP 管道触发工具调用"""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments or {}
            }
        }
        resp = self._send_raw(payload, timeout=60.0)
        if not resp:
            return {"error": "MCP Server 无响应或通信超时"}
        if "error" in resp:
            return {"error": resp["error"].get("message", "MCP 工具调用执行异常")}

        result = resp.get("result", {})
        content_items = result.get("content", [])
        if content_items:
            first_item = content_items[0]
            if first_item.get("type") == "text":
                text_val = first_item.get("text", "{}")
                try:
                    return json.loads(text_val)
                except Exception:
                    return {"result": text_val}
        return result

    def read_resource(self, uri: str) -> str:
        """读取只读资源数据流"""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "resources/read",
            "params": {"uri": uri}
        }
        resp = self._send_raw(payload)
        if resp and "result" in resp:
            contents = resp["result"].get("contents", [])
            if contents:
                return contents[0].get("text", "")
        return ""
