# -*- coding: utf-8 -*-
"""MCP 工具启用过滤和写操作限制回归测试。"""

import unittest
from unittest.mock import patch

from app import nas_mcp_server


class TestMCPToolVisibility(unittest.TestCase):
    def test_optional_tools_hidden_unless_configured(self):
        with patch.object(nas_mcp_server.aria2_plugin, "is_enabled", return_value=False), \
             patch.object(nas_mcp_server.firewall_plugin, "is_enabled", return_value=False), \
             patch.object(nas_mcp_server.pc_power_plugin, "is_enabled", return_value=False):
            names = {tool["name"] for tool in nas_mcp_server.get_enabled_tools()}
        self.assertNotIn("manage_aria2_download", names)
        self.assertNotIn("manage_firewall_security", names)
        self.assertNotIn("manage_pc_power", names)
        self.assertIn("get_system_health", names)

    def test_unconfigured_optional_tool_call_rejected(self):
        with patch.object(nas_mcp_server.aria2_plugin, "is_enabled", return_value=False):
            response = nas_mcp_server.handle_request({
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "manage_aria2_download", "arguments": {"action": "status"}},
                "id": 1,
            })
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32601)

    def test_docker_restart_rejected(self):
        response = nas_mcp_server.execute_manage_docker_container({
            "action": "restart", "container_name": "test-container"
        })
        self.assertEqual(response["status"], "error")


if __name__ == "__main__":
    unittest.main()
