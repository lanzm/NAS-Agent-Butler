# -*- coding: utf-8 -*-
"""
test_utils.py - 基础工具函数集合单元测试
验证：
1. format_bytes / human_bytes 字节大小格式化
2. format_duration_chinese 中文运行时间跨度格式化与 compact 模式
3. find_first_existing_path 候选路径探测
4. get_chinese_weekday 中文星期获取
"""

import os
import unittest
import datetime
import tempfile
from app.utils import format_bytes, human_bytes, format_duration_chinese, find_first_existing_path
from app.calendar_helper import get_chinese_weekday, WEEKDAYS_CN


class TestUtils(unittest.TestCase):

    def test_format_bytes_and_human_bytes_alias(self):
        """测试字节格式化及 human_bytes 别名一致性"""
        self.assertEqual(format_bytes(0), "0B")
        self.assertEqual(format_bytes(None), "0B")
        self.assertEqual(format_bytes("invalid"), "0B")
        self.assertEqual(format_bytes(512), "512B")
        self.assertEqual(format_bytes(1024), "1.0KB")
        self.assertEqual(format_bytes(1024 * 1024), "1.0MB")
        self.assertEqual(format_bytes(int(1024 * 1024 * 1024 * 2.5)), "2.5GB")
        self.assertEqual(format_bytes(1024 ** 4), "1.0TB")
        self.assertEqual(format_bytes(1024 ** 5), "1.0PB")

        # 验证别名 human_bytes 表现完全一致
        self.assertEqual(human_bytes(0), "0B")
        self.assertEqual(human_bytes(1024), "1.0KB")
        self.assertEqual(human_bytes(1024 * 1024), "1.0MB")

    def test_format_duration_chinese_standard(self):
        """测试标准中文持续时间格式化"""
        self.assertEqual(format_duration_chinese(0), "0分钟")
        self.assertEqual(format_duration_chinese(59), "0分钟")
        self.assertEqual(format_duration_chinese(60), "1分钟")
        self.assertEqual(format_duration_chinese(3600), "1小时")
        self.assertEqual(format_duration_chinese(3665), "1小时1分钟")

        # 天 + 小时 + 分钟
        sec = 86400 * 3 + 3600 * 4 + 60 * 15
        self.assertEqual(format_duration_chinese(sec), "3天4小时15分钟")

        # 异常与边界值
        self.assertEqual(format_duration_chinese("invalid"), "未知")
        self.assertEqual(format_duration_chinese(-10), "0分钟")

    def test_format_duration_chinese_compact(self):
        """测试 compact=True 紧凑模式（保留高阶两级）"""
        # 天 + 小时
        sec_days = 86400 * 5 + 3600 * 2 + 60 * 30
        self.assertEqual(format_duration_chinese(sec_days, compact=True), "5天2小时")

        # 小时 + 分钟
        sec_hours = 3600 * 3 + 60 * 15
        self.assertEqual(format_duration_chinese(sec_hours, compact=True), "3小时15分钟")

        # 仅分钟
        sec_minutes = 60 * 42
        self.assertEqual(format_duration_chinese(sec_minutes, compact=True), "42分钟")

    def test_find_first_existing_path(self):
        """测试路径探测降级机制"""
        self.assertIsNone(find_first_existing_path([]))
        self.assertIsNone(find_first_existing_path(["/non/existent/path/1.txt", "/non/existent/path/2.txt"]))

        with tempfile.NamedTemporaryFile() as tmp:
            paths = ["/invalid/path/a", tmp.name, "/invalid/path/b"]
            found = find_first_existing_path(paths)
            self.assertEqual(found, tmp.name)

    def test_get_chinese_weekday(self):
        """测试日期转中文星期"""
        # 2026-10-23 是星期五
        fri = datetime.date(2026, 10, 23)
        self.assertEqual(get_chinese_weekday(fri), "星期五")

        # 2026-10-24 是星期六
        sat = datetime.date(2026, 10, 24)
        self.assertEqual(get_chinese_weekday(sat), "星期六")

        # 2026-10-25 是星期日
        sun = datetime.date(2026, 10, 25)
        self.assertEqual(get_chinese_weekday(sun), "星期日")

        # 2026-10-26 是星期一
        mon = datetime.date(2026, 10, 26)
        self.assertEqual(get_chinese_weekday(mon), "星期一")

        # 支持 datetime
        dt = datetime.datetime(2026, 10, 23, 15, 30)
        self.assertEqual(get_chinese_weekday(dt), "星期五")


if __name__ == "__main__":
    unittest.main()
