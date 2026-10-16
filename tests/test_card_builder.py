# -*- coding: utf-8 -*-
"""
test_card_builder.py - 飞书卡片构建器单元测试
"""

import unittest
from app.card_builder import (
    format_feishu_markdown,
    clean_ai_content,
    build_status_card,
    build_ai_response_card,
    build_message_card,
    build_confirm_card,
    get_i18n
)


class TestCardBuilder(unittest.TestCase):

    def test_format_feishu_markdown_inline_code(self):
        """测试单反引号行内代码转为飞书 text_tag 标签"""
        text = "CPU使用率为 `85%`"
        res = format_feishu_markdown(text)
        self.assertIn("<text_tag color='neutral'>85%</text_tag>", res)

    def test_format_feishu_markdown_code_block(self):
        """测试多行代码块不被单反引号正则误伤"""
        text = "```bash\ndocker ps\n```"
        res = format_feishu_markdown(text)
        self.assertIn("```bash\ndocker ps\n```", res)

    def test_clean_ai_content_json_stripping(self):
        """测试剥离大模型返回的 JSON 外壳"""
        raw = '{"text": "今日天气晴朗，系统运行平稳"}'
        cleaned = clean_ai_content(raw)
        self.assertIn("今日天气晴朗，系统运行平稳", cleaned)
        self.assertNotIn('{"text":', cleaned)

    def test_build_status_card_normal(self):
        """测试正常状态下的系统卡片（蓝色表头，无告警）"""
        data = {
            "hostname": "test-nas",
            "host_ip": "192.168.1.100",
            "uptime": "5天2小时",
            "timestamp": "2026-10-16 12:00:00",
            "cpu_usage": 15.0,
            "cpu_temp": 45,
            "loadavg": "0.10 / 0.15 / 0.20",
            "mem_usage": 30.0,
            "mem_used": "4.8 GB",
            "mem_total": "16.0 GB",
            "disks": [{"mount": "系统盘 /", "total": "500 GB", "used": "100 GB", "free": "400 GB", "percent": 20}],
            "containers": [{"name": "jellyfin", "status": "running", "is_running": True, "health": "healthy"}],
            "is_alarm": False,
            "alarms": []
        }
        card = build_status_card(data)
        self.assertEqual(card["header"]["template"], "blue")
        self.assertIn("NAS 系统运行概况", card["header"]["title"]["content"])

    def test_build_status_card_alarm(self):
        """测试异常告警状态下的系统卡片（红色表头，高亮展示告警项）"""
        data = {
            "hostname": "test-nas",
            "host_ip": "192.168.1.100",
            "uptime": "5天2小时",
            "timestamp": "2026-10-16 12:00:00",
            "cpu_usage": 95.0,
            "cpu_temp": 85,
            "loadavg": "4.50 / 3.80 / 2.90",
            "mem_usage": 92.0,
            "mem_used": "14.8 GB",
            "mem_total": "16.0 GB",
            "disks": [],
            "containers": [],
            "is_alarm": True,
            "alarms": ["CPU 使用率持续偏高: 95% (阈值 85%)", "CPU 温度过高: 85°C (阈值 80°C)"]
        }
        card = build_status_card(data)
        self.assertEqual(card["header"]["template"], "red")
        self.assertIn("NAS 系统异常告警", card["header"]["title"]["content"])
        card_str = str(card)
        self.assertIn("CPU 使用率持续偏高", card_str)

    def test_build_ai_response_card(self):
        """测试 AI 响应卡片"""
        card = build_ai_response_card(
            content="根据分析，当前系统平稳。",
            title="🤖 运维晨报",
            trace_tag="Trace: req-12345 (250ms)"
        )
        self.assertEqual(card["header"]["title"]["content"], "🤖 运维晨报")
        self.assertTrue(card["config"]["wide_screen_mode"])
        card_str = str(card)
        self.assertIn("根据分析，当前系统平稳。", card_str)
        self.assertIn("req-12345", card_str)

    def test_build_message_card(self):
        """测试通用消息卡片"""
        card = build_message_card(title="提示", content="备份已完成", template="green")
        self.assertEqual(card["header"]["template"], "green")
        self.assertEqual(card["header"]["title"]["content"], "提示")


if __name__ == "__main__":
    unittest.main()
