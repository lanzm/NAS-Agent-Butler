# -*- coding: utf-8 -*-
"""
tests/test_channels.py - 多 IM 通道抽象、生命周期与调度管理测试
"""

import unittest
from app.channels.base import BaseChannel
from app.channels.manager import ChannelManager


class MockChannel(BaseChannel):
    def __init__(self, name="mock", enabled=True):
        self._name = name
        self._enabled = enabled
        self.started = False
        self.stopped = False
        self.sent_messages = []
        self.sent_cards = []
        self.sent_files = []

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

    def send_file(self, target_id, file_path: str, **kwargs) -> bool:
        self.sent_files.append((target_id, file_path))
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


class TestFeishuCardAction(unittest.TestCase):
    """测试飞书卡片按钮动作响应与防超时异步解耦"""

    def test_on_card_action_check_docker_async_fast_response(self):
        from unittest.mock import MagicMock
        from app.channels.feishu.channel import FeishuChannel

        mock_handler = MagicMock()
        mock_handler.handle_card_action.return_value = {
            "toast": {"type": "info", "content": "已更新"},
            "card": {"type": "template", "title": "result"}
        }

        channel = FeishuChannel(mock_handler)
        channel.patch_card = MagicMock(return_value=True)

        # Mock 带有 open_message_id 的卡片触发事件
        mock_data = MagicMock()
        mock_data.event.action.value = {"action": "check_docker"}
        mock_data.event.context.open_message_id = "om_12345678"

        resp = channel._on_card_action(mock_data)
        self.assertIsNotNone(resp)
        self.assertTrue(hasattr(resp, "toast") or hasattr(resp, "card") or hasattr(resp, "d"))

        # 校验 Toast 符合 I18N 规范且字数 <= 6 字约束
        from app.card_builder import get_i18n
        expected_toast = get_i18n("toast_docker_analyzing", "🐳 正在排查中")
        toast_dict = getattr(resp, "toast", None) or (getattr(resp, "d", {}) or {}).get("toast")
        if isinstance(toast_dict, dict):
            toast_content = toast_dict.get("content", "")
            self.assertEqual(toast_content, expected_toast)
            clean_text = toast_content.replace("🐳", "").strip()
            self.assertLessEqual(len(clean_text), 6)


if __name__ == "__main__":
    unittest.main()
