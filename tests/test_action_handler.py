# -*- coding: utf-8 -*-
"""
tests/test_action_handler.py - 交互动作分发器与卡片回调测试
"""

import os
import unittest
from unittest.mock import MagicMock, patch
from app.action_handler import ActionHandler


class TestActionHandler(unittest.TestCase):

    def setUp(self):
        self.mock_collector = MagicMock()
        self.mock_collector.collect.return_value = {
            "hostname": "test-nas",
            "host_ip": "100.1.2.3",
            "uptime": "10天",
            "timestamp": "2026-10-23 17:00:00",
            "cpu_usage": 10.0,
            "mem_usage": 30.0,
            "mem_used": "3.0 GB",
            "mem_total": "16.0 GB",
            "loadavg": "0.1 / 0.2 / 0.3",
            "disks": [],
            "containers": [],
            "alarms": [],
            "is_alarm": False
        }
        with patch("app.action_handler.AIAgent"):
            self.handler = ActionHandler(self.mock_collector)
            self.handler.agent.chat = MagicMock(return_value={
                "text": "Docker 容器全部健康运行。",
                "trace_tag": "#tr_123 (0.5s)"
            })

    def test_handle_text_command_zh(self):
        with patch.dict(os.environ, {"DEFAULT_LANGUAGE": "zh"}):
            mode, card = self.handler.handle_text_command("测试提问")
            self.assertEqual(mode, "CARD")
            self.assertIn("智能管家", card["header"]["title"]["content"])
            self.assertEqual(card["header"]["template"], "indigo")

    def test_handle_text_command_en(self):
        with patch.dict(os.environ, {"DEFAULT_LANGUAGE": "en"}):
            mode, card = self.handler.handle_text_command("Test question")
            self.assertEqual(mode, "CARD")
            self.assertIn("Smart Butler", card["header"]["title"]["content"])

    def test_handle_card_action_refresh_status(self):
        res = self.handler.handle_card_action({"action": "refresh_status"})
        self.assertEqual(res["toast"]["type"], "success")
        self.assertIn("card", res)
        self.mock_collector.collect.assert_called_once()

    def test_handle_card_action_check_docker(self):
        res = self.handler.handle_card_action({"action": "check_docker"})
        self.assertEqual(res["toast"]["type"], "info")
        self.assertIn("card", res)
        self.handler.agent.chat.assert_called_once()

    def test_handle_card_action_cancel_action(self):
        res = self.handler.handle_card_action({"action": "cancel_action"})
        self.assertEqual(res["toast"]["type"], "info")
        self.assertIn("操作已取消", res["toast"]["content"])
        self.assertEqual(res["card"]["header"]["template"], "grey")
        self.assertIn("操作已取消", res["card"]["header"]["title"]["content"])

    def test_handle_card_action_cancel_action_en(self):
        with patch.dict(os.environ, {"DEFAULT_LANGUAGE": "en"}):
            res = self.handler.handle_card_action({"action": "cancel_action"})
            self.assertEqual(res["toast"]["type"], "info")
            self.assertIn("cancelled", res["toast"]["content"])
            self.assertEqual(res["card"]["header"]["template"], "grey")
            self.assertIn("Cancelled", res["card"]["header"]["title"]["content"])

    def test_handle_card_action_unknown(self):
        res = self.handler.handle_card_action({"action": "something_non_existent"})
        self.assertEqual(res["toast"]["type"], "warning")
        self.assertIn("未知动作", res["toast"]["content"])


if __name__ == "__main__":
    unittest.main()
