# -*- coding: utf-8 -*-
"""
tests/test_ai_agent.py - AI Agent 对话管理、历史截断与 TraceTracker 追踪器测试
"""

import unittest
from unittest.mock import patch
from app.ai_agent import AIAgent
from app.trace_tracker import TraceTracker


class TestTraceTracker(unittest.TestCase):
    """测试调用链耗时度量与标签生成"""

    def test_trace_duration_and_tags(self):
        tracker = TraceTracker(trace_id="test_tr1")
        tracker.mark_first_thought(0.85)
        tracker.record_tool_call("fetch_weather", 0.42, "ok")
        tracker.mark_second_thought(0.51)
        tracker.record_tokens({"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150})

        finish_duration = tracker.finish()
        self.assertGreaterEqual(finish_duration, 0)
        self.assertEqual(tracker.first_thought_duration, 0.85)
        self.assertEqual(tracker.tool_execution_duration, 0.42)
        self.assertEqual(tracker.second_thought_duration, 0.51)
        self.assertEqual(tracker.total_tokens, 150)

        tag = tracker.get_summary_tag()
        self.assertIn("#test_tr1", tag)
        self.assertIn("fetch_weather", tag)
        self.assertIn("150T", tag)

    def test_tool_call_max_count(self):
        tracker = TraceTracker(trace_id="test_tr2")
        for i in range(60):
            tracker.record_tool_call(f"tool_{i}", 0.05, "ok")
        # 保护边界：最多保留 50 条工具调用详情
        self.assertEqual(len(tracker.tool_calls), 50)


class TestAIAgentHistory(unittest.TestCase):
    """测试 AI Agent 对话历史修剪与滑动窗口管理"""

    def setUp(self):
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
        for i in range(4):
            self.agent.history.append({"role": "user", "content": "X" * 3000})

        self.agent._trim_history(max_messages=10, max_chars=7000)
        total_chars = sum(len(m["content"]) for m in self.agent.history)
        self.assertLessEqual(total_chars, 7000)
        self.assertEqual(len(self.agent.history), 2)


class TestAIAgentChat(unittest.TestCase):
    """测试 AI Agent 对话流程与锁重入（防死锁）"""

    @patch("app.ai_agent.MCPClient")
    def test_chat_lazy_mcp_client_no_deadlock(self, mock_mcp_cls):
        mock_instance = mock_mcp_cls.return_value
        mock_instance.get_prompt.return_value = "system prompt"
        mock_instance.get_openai_tools.return_value = []

        agent = AIAgent()
        agent.api_key = "test_key"
        agent.api_base = "https://api.test.com"

        # Mock _call_model to return immediate answer
        with patch.object(agent, "_call_model", return_value=({"content": "你好！我是智能管家。"}, {"total_tokens": 50}, None)):
            res = agent.chat("你好")
            self.assertIn("你好", res["text"])
            self.assertIn("trace_tag", res)


if __name__ == "__main__":
    unittest.main()
