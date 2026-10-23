# -*- coding: utf-8 -*-
"""
tests/test_p2_quality.py - P2 质量、工程化与健康检查回归测试
"""

import os
import unittest
from unittest.mock import patch
from app.config import ButlerConfig, get_int, get_str
from app.trace_tracker import TraceTracker
from app.channels.base import BaseChannel
from app.channels.manager import ChannelManager


class TestConfigValidation(unittest.TestCase):
    """测试强类型配置与边界校验"""

    def test_get_int_bounds_and_fallback(self):
        with patch.dict(os.environ, {"TEST_INT_VAL": "150"}):
            # 超出上限 99 -> 99
            val = get_int("TEST_INT_VAL", default=50, min_val=10, max_val=99)
            self.assertEqual(val, 99)

        with patch.dict(os.environ, {"TEST_INT_VAL": "5"}):
            # 低于下限 10 -> 10
            val = get_int("TEST_INT_VAL", default=50, min_val=10, max_val=99)
            self.assertEqual(val, 10)

        with patch.dict(os.environ, {"TEST_INT_VAL": "not_a_number"}):
            # 非法字符 -> fallback default
            val = get_int("TEST_INT_VAL", default=50, min_val=10, max_val=99)
            self.assertEqual(val, 50)

    def test_butler_config_load(self):
        with patch.dict(os.environ, {
            "CPU_THRESHOLD": "92",
            "DISK_THRESHOLD": "98",
            "DEFAULT_CITY": "上海",
            "ALARM_COOLDOWN": "1800"
        }):
            cfg = ButlerConfig.load()
            self.assertEqual(cfg.cpu_threshold, 92)
            self.assertEqual(cfg.disk_threshold, 98)
            self.assertEqual(cfg.default_city, "上海")
            self.assertEqual(cfg.alarm_cooldown, 1800)


class TestTraceTracker(unittest.TestCase):
    """测试执行链路跟踪器及性能与耗时统计"""

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
        # 保护边界：最多保留 50 条调用详情
        self.assertEqual(len(tracker.tool_calls), 50)


class MockChannel(BaseChannel):
    def __init__(self, name="mock", enabled=True):
        self._name = name
        self._enabled = enabled
        self.started = False
        self.stopped = False
        self.sent_messages = []
        self.sent_cards = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def display_name(self) -> str:
        return f"Mock Channel ({self._name})"

    def is_enabled(self) -> bool:
        return self._enabled

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def send_message(self, target_id, content: str, title=None, **kwargs) -> bool:
        self.sent_messages.append((target_id, content, title))
        return True

    def send_card(self, target_id, card_data, **kwargs) -> bool:
        self.sent_cards.append((target_id, card_data))
        return True


class TestChannelManager(unittest.TestCase):
    """测试渠道管理器与多通道广播"""

    def test_manager_registration_and_broadcast(self):
        manager = ChannelManager()
        ch1 = MockChannel("feishu", enabled=True)
        ch2 = MockChannel("disabled_ch", enabled=False)
        manager.register(ch1)
        manager.register(ch2)

        self.assertEqual(len(manager.get_active_channels()), 1)

        msg_results = manager.broadcast_message("晨报测试", title="早安")
        self.assertTrue(msg_results["feishu"])
        self.assertNotIn("disabled_ch", msg_results)
        self.assertEqual(len(ch1.sent_messages), 1)

        card_results = manager.broadcast_card({"type": "test_card"})
        self.assertTrue(card_results["feishu"])
        self.assertEqual(len(ch1.sent_cards), 1)

        manager.stop_all()
        self.assertTrue(ch1.stopped)
        self.assertFalse(ch2.stopped)


class TestInternalNotifyHandler(unittest.TestCase):
    """测试内部 Webhook 与健康检查端点"""

    def test_health_check_get(self):
        import io
        from unittest.mock import MagicMock
        from app.main import InternalNotifyHandler

        handler = InternalNotifyHandler.__new__(InternalNotifyHandler)
        handler.path = "/health"
        handler.wfile = io.BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        handler.do_GET()
        handler.send_response.assert_called_with(200)
        self.assertIn(b"healthy", handler.wfile.getvalue())


if __name__ == "__main__":
    unittest.main()
