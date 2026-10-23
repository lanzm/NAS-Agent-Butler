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


if __name__ == "__main__":
    unittest.main()
