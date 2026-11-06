# -*- coding: utf-8 -*-
"""MCP 工具常驻可见性、防规划漂移护栏与写操作限制回归测试。"""

import json
import unittest
from unittest.mock import patch

from app import nas_mcp_server


class TestMCPToolVisibility(unittest.TestCase):
    def test_tools_always_visible_to_prevent_drift(self):
        """方案 A：所有核心工具常驻暴露给 LLM，防止因隐藏工具诱发大模型规划漂移与外网乱搜"""
        names = {tool["name"] for tool in nas_mcp_server.get_enabled_tools()}
        self.assertIn("manage_pc_power", names)
        self.assertIn("manage_aria2_download", names)
        self.assertIn("diagnose_system_health", names)
        self.assertIn("get_system_health", names)
        self.assertIn("search_web_info", names)

    def test_unconfigured_optional_tool_returns_graceful_error(self):
        """当插件未配置时，直接返回结构化错误事实引导用户配置，而非抛出 RPC 协议级异常"""
        with patch.object(nas_mcp_server.pc_power_plugin, "is_enabled", return_value=False):
            response = nas_mcp_server.handle_request({
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "manage_pc_power", "arguments": {"action": "wake"}},
                "id": 1,
            })
        self.assertIn("result", response)
        content_text = response["result"]["content"][0]["text"]
        data = json.loads(content_text)
        self.assertEqual(data["status"], "error")
        self.assertIn("ENABLE_PC_POWER", data["message"])

    def test_docker_restart_rejected(self):
        response = nas_mcp_server.execute_manage_docker_container({
            "action": "restart", "container_name": "test-container"
        })
        self.assertEqual(response["status"], "error")


if __name__ == "__main__":
    unittest.main()
