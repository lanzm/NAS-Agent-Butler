# -*- coding: utf-8 -*-
"""
tests/test_p3_features.py - P3 扩展性、搜索增强、历史管理与工具调度测试
"""

import unittest
from unittest.mock import patch, MagicMock
from app.nas_mcp_server import handle_request, execute_search_web_info, TOOL_DISPATCH_TABLE
from app.ai_agent import AIAgent
from app.card_builder import build_confirm_card
from app.plugins.pc_power_plugin import send_magic_packet


class TestMCPServerDispatch(unittest.TestCase):
    """测试 MCP Server 字典注册表分发与错误控制"""

    def test_tools_list(self):
        req = {"jsonrpc": "2.0", "method": "tools/list", "id": 1}
        res = handle_request(req)
        self.assertEqual(res["jsonrpc"], "2.0")
        self.assertIn("tools", res["result"])
        self.assertGreater(len(res["result"]["tools"]), 0)

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
        # 验证 TOOL_DISPATCH_TABLE 中注册了核心工具
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


class TestWebSearchEnhancement(unittest.TestCase):
    """测试必应搜索与摘要正文提取增强"""

    def test_empty_query(self):
        res = execute_search_web_info({"query": ""})
        self.assertEqual(res["status"], "error")

    @patch("urllib.request.urlopen")
    def test_mock_search_with_snippets(self, mock_urlopen):
        mock_html = """
        <html><body>
        <li class="b_algo">
            <h2><a href="https://example.com/item1">测试标题一</a></h2>
            <div class="b_caption"><p>这是第一条搜索摘要内容说明。</p></div>
        </li>
        <li class="b_algo">
            <h2><a href="https://example.com/item2">测试标题二</a></h2>
            <div class="b_caption"><p>这是第二条搜索摘要内容说明。</p></div>
        </li>
        </body></html>
        """
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_html.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = execute_search_web_info({"query": "测试搜索"})
        self.assertEqual(res["status"], "success")
        self.assertIn("测试标题一", res["markdown_result"])
        self.assertIn("测试标题二", res["markdown_result"])


class TestAIAgentHistoryTrimming(unittest.TestCase):
    """测试多轮对话历史基于条数与字符预算的双重截断"""

    def setUp(self):
        # 实例化时不拉起真实 MCP
        with patch("app.ai_agent.MCPClient"):
            self.agent = AIAgent()

    def test_trim_by_max_messages(self):
        for i in range(15):
            self.agent.history.append({"role": "user" if i % 2 == 0 else "assistant", "content": f"msg_{i}"})
        self.agent._trim_history(max_messages=10, max_chars=100000)
        self.assertEqual(len(self.agent.history), 10)
        self.assertEqual(self.agent.history[-1]["content"], "msg_14")
        self.assertEqual(self.agent.history[0]["content"], "msg_5")

    def test_trim_by_max_chars(self):
        # 构造 4 条，每条 3000 字，总共 12000 字
        for i in range(4):
            self.agent.history.append({"role": "user", "content": "X" * 3000})

        # 限制预算为 7000 字，应自动剔除最老的记录
        self.agent._trim_history(max_messages=10, max_chars=7000)
        total_chars = sum(len(m["content"]) for m in self.agent.history)
        self.assertLessEqual(total_chars, 7000)
        self.assertEqual(len(self.agent.history), 2)


class TestDangerousOperationConfirm(unittest.TestCase):
    """测试敏感/破坏性操作二次核准卡片"""

    def test_build_confirm_card_structure(self):
        card = build_confirm_card(
            title="重启容器确认",
            message="确认重启容器 **nginx-proxy** 吗？",
            action_name="restart_container",
            target="nginx-proxy"
        )
        self.assertIn("header", card)
        self.assertEqual(card["header"]["template"], "orange")
        self.assertIn("elements", card)
        action_elements = [el for el in card["elements"] if el.get("tag") == "action"]
        self.assertEqual(len(action_elements), 1)

        actions = action_elements[0]["actions"]
        self.assertEqual(len(actions), 2)
        # 确认按钮
        self.assertEqual(actions[0]["type"], "danger")
        self.assertEqual(actions[0]["value"]["action"], "restart_container")
        self.assertEqual(actions[0]["value"]["target"], "nginx-proxy")
        # 取消按钮
        self.assertEqual(actions[1]["value"]["action"], "cancel_action")


class TestPCPowerPlugin(unittest.TestCase):
    """测试 PC 电源管理扩展参数与唤醒包逻辑"""

    def test_invalid_mac(self):
        self.assertFalse(send_magic_packet("invalid_mac"))
        self.assertFalse(send_magic_packet("12:34"))

    def test_valid_mac(self):
        # 模拟有效 MAC 地址生成 102 字节魔包
        self.assertTrue(send_magic_packet("00:11:22:33:44:55"))
        self.assertTrue(send_magic_packet("AA-BB-CC-DD-EE-FF"))


if __name__ == "__main__":
    unittest.main()
