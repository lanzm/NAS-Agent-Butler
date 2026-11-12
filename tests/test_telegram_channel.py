# -*- coding: utf-8 -*-
"""
tests/test_telegram_channel.py - 测试 Telegram 通道生命周期、消息转码、按钮交互与安全鉴权
"""

import time
import unittest
from unittest.mock import MagicMock, patch

from app.channels.telegram.channel import (
    TelegramChannel,
    card_to_telegram_payload,
    convert_markdown_to_telegram_html
)
from app.config import settings


class TestTelegramChannel(unittest.TestCase):
    """测试 Telegram 通道核心逻辑"""

    def setUp(self):
        self.mock_handler = MagicMock()
        self.mock_handler.handle_text_command.return_value = (
            "CARD",
            {
                "header": {"title": {"content": "诊断报告"}},
                "elements": [{"tag": "markdown", "content": "NAS 运行正常"}]
            }
        )
        self.mock_handler.handle_card_action.return_value = {
            "toast": {"type": "success", "content": "已刷新"},
            "card": {
                "header": {"title": {"content": "系统状态"}},
                "elements": [{"tag": "markdown", "content": "CPU: 10%"}]
            }
        }

    def test_convert_markdown_to_telegram_html(self):
        """测试 Markdown 与飞书专有标签完整转码为 Telegram 原生 HTML 格式"""
        raw_text = (
            "• 状态: **健康** 且 *运行中*\n"
            "• 容器: `immich_server` 与 `caddy_services`\n"
            "• 阈值判定: 1 < 2 & 5 > 3\n"
            "• 飞书标签: <text_tag color='neutral'>15%</text_tag> <font color='red'>告警</font>\n"
            "• 链接: [官网](https://github.com/lanzm/NAS-Agent-Butler)\n"
            "```python\nif x < 10 and y > 2:\n    print('OK')\n```"
        )
        res = convert_markdown_to_telegram_html(raw_text)

        self.assertIn("<b>健康</b>", res)
        self.assertIn("<b>运行中</b>", res)
        self.assertIn("<code>immich_server</code>", res)
        self.assertIn("<code>caddy_services</code>", res)
        self.assertIn("1 &lt; 2 &amp; 5 &gt; 3", res)
        self.assertIn("<code>15%</code> 告警", res)
        self.assertIn('<a href="https://github.com/lanzm/NAS-Agent-Butler">官网</a>', res)
        self.assertIn('<pre><code class="language-python">if x &lt; 10 and y &gt; 2:\n    print(\'OK\')\n</code></pre>', res)

        # 验证算式中的星号不会被误转为加粗
        math_res = convert_markdown_to_telegram_html("算式: 2 * 3 * 4")
        self.assertIn("2 * 3 * 4", math_res)
        self.assertNotIn("<b>", math_res)

        # 验证 URL 中含有引号时的安全转义
        quote_link_res = convert_markdown_to_telegram_html('[链接](https://example.com/test"safe)')
        self.assertIn('<a href="https://example.com/test%22safe">链接</a>', quote_link_res)

    def test_card_to_telegram_payload_conversion(self):
        """测试卡片格式转换为 Telegram HTML 与内联键盘 (Inline Keyboard)"""
        card_data = {
            "header": {"title": {"content": "系统概况"}},
            "elements": [
                {
                    "tag": "markdown",
                    "content": "• CPU 占用: <text_tag color='neutral'>15%</text_tag>\n• 状态: <font color='red'>异常</font>"
                },
                {"tag": "hr"},
                {
                    "tag": "action",
                    "actions": [
                        {"text": {"content": "📊 查看概况"}, "value": {"action": "refresh_status"}},
                        {"text": {"content": "🐳 检查容器"}, "value": {"action": "check_docker"}}
                    ]
                }
            ]
        }
        text, reply_markup = card_to_telegram_payload(card_data)

        self.assertIn("<b>系统概况</b>", text)
        self.assertIn("• CPU 占用: <code>15%</code>", text)
        self.assertIn("• 状态: 异常", text)
        self.assertIn("────────────────────", text)
        self.assertIsNotNone(reply_markup)
        self.assertIn("inline_keyboard", reply_markup)
        buttons = reply_markup["inline_keyboard"][0]
        self.assertEqual(len(buttons), 2)
        self.assertEqual(buttons[0]["text"], "📊 查看概况")
        self.assertEqual(buttons[0]["callback_data"], "refresh_status")
        self.assertEqual(buttons[1]["text"], "🐳 检查容器")
        self.assertEqual(buttons[1]["callback_data"], "check_docker")

    def test_card_to_telegram_payload_long_truncation(self):
        """测试超长消息防止突破 4096 字符限制"""
        card_data = {
            "elements": [{"tag": "markdown", "content": "A" * 5000}]
        }
        text, _ = card_to_telegram_payload(card_data)
        self.assertLessEqual(len(text), 4000)
        self.assertIn("(内容已截断)", text)

    def test_is_enabled(self):
        """测试根据 TELEGRAM_BOT_TOKEN 自动判定启用状态"""
        channel = TelegramChannel(self.mock_handler)
        channel.bot_token = ""
        self.assertFalse(channel.is_enabled())

        channel.bot_token = "your_bot_token_here"
        self.assertFalse(channel.is_enabled())

        channel.bot_token = "123456:ABC-DEF1234ghIkl"
        self.assertTrue(channel.is_enabled())

    @patch("requests.Session.post")
    def test_send_message_success(self, mock_post):
        """测试发送消息成功（验证 parse_mode 为 HTML）"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        channel = TelegramChannel(self.mock_handler)
        channel.bot_token = "123456:ABC"
        channel.chat_id = "987654321"

        ok = channel.send_message(None, "测试消息正文", title="早报")
        self.assertTrue(ok)
        mock_post.assert_called_once()
        sent_data = mock_post.call_args[1]["json"]
        self.assertEqual(sent_data["chat_id"], "987654321")
        self.assertIn("<b>早报</b>", sent_data["text"])
        self.assertIn("测试消息正文", sent_data["text"])
        self.assertEqual(sent_data["parse_mode"], "HTML")

    @patch("requests.Session.post")
    def test_send_message_html_fallback(self, mock_post):
        """测试 HTML 语法冲突导致 400 时自动安全降级为纯文本重试"""
        resp_400 = MagicMock()
        resp_400.status_code = 400
        resp_400.text = "Bad Request: can't parse entities"

        resp_200 = MagicMock()
        resp_200.status_code = 200

        mock_post.side_effect = [resp_400, resp_200]

        channel = TelegramChannel(self.mock_handler)
        channel.bot_token = "123456:ABC"
        channel.chat_id = "987654321"

        ok = channel.send_message(None, "带有冲突字符的内容")
        self.assertTrue(ok)
        self.assertEqual(mock_post.call_count, 2)
        # 第二次重试应剔除 parse_mode
        second_call_json = mock_post.call_args_list[1][1]["json"]
        self.assertNotIn("parse_mode", second_call_json)

    @patch("requests.Session.post")
    def test_handle_incoming_message_auth_and_dispatch(self, mock_post):
        """测试消息鉴权与自动绑定"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        channel = TelegramChannel(self.mock_handler)
        channel.bot_token = "123456:ABC"
        channel.chat_id = ""  # 初始为空

        # 1. 首次用户发送消息，自动记忆并绑定
        incoming_msg = {
            "chat": {"id": 111222333},
            "text": "查一下当前 NAS 水位"
        }
        channel._handle_incoming_message(incoming_msg)
        self.assertEqual(channel.chat_id, "111222333")
        self.mock_handler.handle_text_command.assert_called_with("查一下当前 NAS 水位")

        # 2. 陌生非管理员用户发送消息，触发拦截拒绝
        stranger_msg = {
            "chat": {"id": 999999999},
            "text": "重启服务器"
        }
        channel._handle_incoming_message(stranger_msg)
        sent_text = mock_post.call_args[1]["json"]["text"]
        self.assertIn("权限拒绝", sent_text)

    @patch("requests.Session.post")
    def test_handle_incoming_callback_query(self, mock_post):
        """测试内联按钮点击回调与即时 Toast 弹窗"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        channel = TelegramChannel(self.mock_handler)
        channel.bot_token = "123456:ABC"
        channel.chat_id = "111222333"

        query = {
            "id": "query_id_123",
            "message": {
                "chat": {"id": 111222333},
                "message_id": 42
            },
            "data": "refresh_status"
        }
        channel._handle_incoming_callback(query)

        # 检查是否调用了 handle_card_action
        self.mock_handler.handle_card_action.assert_called_with({"action": "refresh_status"})
        # 检查是否调用了 answerCallbackQuery
        call_urls = [c[0][0] for c in mock_post.call_args_list]
        self.assertTrue(any("answerCallbackQuery" in u for u in call_urls))
        self.assertTrue(any("editMessageText" in u for u in call_urls))

    @patch("requests.Session.post")
    def test_handle_incoming_callback_check_docker_async(self, mock_post):
        """测试 check_docker 异步防超时解耦与即时 Toast 气泡"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        channel = TelegramChannel(self.mock_handler)
        channel.bot_token = "123456:ABC"
        channel.chat_id = "111222333"

        query = {
            "id": "query_id_docker",
            "message": {
                "chat": {"id": 111222333},
                "message_id": 99
            },
            "data": "check_docker"
        }
        channel._handle_incoming_callback(query)

        # 即时 answerCallbackQuery 应该立刻被调用
        call_urls = [c[0][0] for c in mock_post.call_args_list]
        self.assertTrue(any("answerCallbackQuery" in u for u in call_urls))
        toast_call = [c[1]["json"] for c in mock_post.call_args_list if "answerCallbackQuery" in c[0][0]][0]
        self.assertIn("正在排查中", toast_call["text"])

        # 等待后台线程执行完毕
        time.sleep(0.1)
        self.mock_handler.handle_card_action.assert_called_with({"action": "check_docker"})


if __name__ == "__main__":
    unittest.main()
