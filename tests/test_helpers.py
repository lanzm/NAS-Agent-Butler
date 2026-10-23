# -*- coding: utf-8 -*-
"""
tests/test_helpers.py - 天气、日历、语音识别及联网搜索等辅助工具模块测试
"""

import datetime
import unittest
from unittest.mock import patch, MagicMock
from app.weather_calendar_helper import get_wttr_weather, get_calendar_info
from app.calendar_helper import _get_lunar_year_days, get_lunar_date
from app.nas_mcp_server import execute_search_web_info
from app.sanitizer import sanitize_text


class TestWeatherCalendarHelper(unittest.TestCase):
    """测试天气与生活日历助手"""

    def test_weather_city_sanitization(self):
        res = get_wttr_weather("../../etc/passwd;curl%20evil.com")
        self.assertNotIn("..", res["city"])
        self.assertNotIn("/", res["city"])
        self.assertNotIn(";", res["city"])

    def test_calendar_info_integration(self):
        cal = get_calendar_info()
        self.assertIn("solar_date", cal)
        self.assertIn("lunar_date", cal)
        self.assertNotEqual(cal["lunar_date"], "农历未知")
        self.assertIn("formatted_calendar", cal)
        self.assertIn("countdown_summary", cal)


class TestCalendarHelper(unittest.TestCase):
    """测试核心阴历/阳历算法"""

    def test_lunar_year_days(self):
        for year in [1900, 2024, 2025, 2026, 2050]:
            days = _get_lunar_year_days(year)
            self.assertGreaterEqual(days, 353, f"{year}年农历天数过少: {days}")
            self.assertLessEqual(days, 385, f"{year}年农历天数过多: {days}")

    def test_lunar_date_accuracy(self):
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

    def test_format_datetime_chinese(self):
        from app.calendar_helper import format_datetime_chinese
        dt = datetime.datetime(2026, 10, 23, 15, 30)
        formatted = format_datetime_chinese(dt)
        self.assertEqual(formatted, "2026年10月23日 15:30 星期五")


class TestAudioMimeDetection(unittest.TestCase):
    """测试音频魔数自动识别纯函数"""

    def test_detect_audio_mime(self):
        from app.audio_transcriber import detect_audio_mime
        self.assertEqual(detect_audio_mime(b"RIFF\x00\x00\x00\x00WAVEfmt "), "audio/wav")
        self.assertEqual(detect_audio_mime(b"ID3\x03\x00\x00"), "audio/mp3")
        self.assertEqual(detect_audio_mime(b"fLaC\x00\x00"), "audio/flac")
        self.assertEqual(detect_audio_mime(b"\x00\x00\x00\x20ftypM4A "), "audio/mp4")
        self.assertEqual(detect_audio_mime(b"OggS\x00\x02"), "audio/ogg")
        self.assertEqual(detect_audio_mime(b""), "audio/ogg")


class TestWebSearchHelper(unittest.TestCase):
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


class TestSanitizer(unittest.TestCase):
    """测试敏感凭据脱敏与过滤"""

    def test_sanitize_empty_or_none(self):
        self.assertEqual(sanitize_text(""), "")
        self.assertIsNone(sanitize_text(None))

    def test_sanitize_env_secrets(self):
        with patch.dict("os.environ", {
            "ARIA2_RPC_SECRET": "my_super_secret_rpc_token_12345",
            "FEISHU_APP_SECRET": "lark_app_secret_xyz_8888"
        }):
            raw = "Connecting to Aria2 with secret my_super_secret_rpc_token_12345 and Feishu lark_app_secret_xyz_8888"
            sanitized = sanitize_text(raw)
            self.assertNotIn("my_super_secret_rpc_token_12345", sanitized)
            self.assertNotIn("lark_app_secret_xyz_8888", sanitized)
            self.assertIn("[PROTECTED_ARIA2_RPC_SECRET]", sanitized)
            self.assertIn("[PROTECTED_FEISHU_APP_SECRET]", sanitized)

    def test_sanitize_patterns(self):
        raw = "password=SuperPassword123; db=postgres://root:Admin12345@localhost:5432/mydb; Header: sk-abcdefghijklmnopqrstuvwxyz123"
        sanitized = sanitize_text(raw)
        self.assertNotIn("SuperPassword123", sanitized)
        self.assertNotIn("Admin12345", sanitized)
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz123", sanitized)
        self.assertIn("[PROTECTED]", sanitized)
        self.assertIn("[PROTECTED_DB_PWD]", sanitized)
        self.assertIn("[PROTECTED_API_KEY]", sanitized)


if __name__ == "__main__":
    unittest.main()
