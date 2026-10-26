# -*- coding: utf-8 -*-
"""
tests/test_mcp.py - MCP 客户端 (MCPClient) 与服务端 (nas_mcp_server) 协议与调度测试
"""

import threading
import unittest
from app.mcp_client import MCPClient
from app.nas_mcp_server import handle_request, TOOL_DISPATCH_TABLE


class TestMCPClient(unittest.TestCase):
    """测试 MCP 客户端功能"""

    def test_tools_caching_and_thread_safety(self):
        """测试 MCPClient 工具定义缓存与并发自增 ID 的线程安全性"""
        client = MCPClient()
        client.start()
        try:
            tools_first = client.get_openai_tools()
            self.assertIsInstance(tools_first, list)
            self.assertGreater(len(tools_first), 0)

            # 再次获取命中缓存
            tools_second = client.get_openai_tools()
            self.assertIs(tools_first, tools_second)

            # 强制刷新生成新列表
            tools_refreshed = client.get_openai_tools(force_refresh=True)
            self.assertEqual(len(tools_first), len(tools_refreshed))

            # 并发请求自增 ID 线程安全测试
            generated_ids = set()
            lock = threading.Lock()

            def worker():
                for _ in range(50):
                    req_id = client._next_id()
                    with lock:
                        generated_ids.add(req_id)

            threads = [threading.Thread(target=worker) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.assertEqual(len(generated_ids), 500)
        finally:
            client.stop()


class TestMCPServer(unittest.TestCase):
    """测试 MCP 服务端协议处理与工具分发"""

    def test_tools_list(self):
        req = {"jsonrpc": "2.0", "method": "tools/list", "id": 1}
        res = handle_request(req)
        self.assertEqual(res["jsonrpc"], "2.0")
        self.assertIn("tools", res["result"])
        names = {tool["name"] for tool in res["result"]["tools"]}
        self.assertIn("get_system_health", names)

    def test_unknown_tool_call(self):
        req = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": "non_existent_tool", "arguments": {}},
            "id": 2
        }
        res = handle_request(req)
        self.assertIn("error", res)
        self.assertEqual(res["error"]["code"], -32601)
        self.assertIn("未知工具", res["error"]["message"])

    def test_valid_tool_dispatch(self):
        self.assertIn("get_system_health", TOOL_DISPATCH_TABLE)
        self.assertIn("generate_daily_report", TOOL_DISPATCH_TABLE)
        self.assertIn("search_web_info", TOOL_DISPATCH_TABLE)

        req = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": "get_system_health", "arguments": {}},
            "id": 3
        }
        res = handle_request(req)
        self.assertIn("result", res)
        self.assertIn("content", res["result"])
        self.assertEqual(res["result"]["content"][0]["type"], "text")

    def test_unknown_method(self):
        req = {"jsonrpc": "2.0", "method": "unsupported/method", "id": 4}
        res = handle_request(req)
        self.assertIn("error", res)
        self.assertEqual(res["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
