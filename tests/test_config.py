# -*- coding: utf-8 -*-
"""
tests/test_config.py - 系统配置解析、边界约束与强类型校验测试
"""

import os
import unittest
from unittest.mock import patch
from app.config import ButlerConfig, get_int, get_str, settings


class TestConfig(unittest.TestCase):
    """测试系统配置层"""

    def test_get_int_bounds_and_fallback(self):
        """测试整数环境变量的上下限截断与格式非法兜底"""
        with patch.dict(os.environ, {"TEST_INT_VAL": "150"}):
            val = get_int("TEST_INT_VAL", default=50, min_val=10, max_val=99)
            self.assertEqual(val, 99)

        with patch.dict(os.environ, {"TEST_INT_VAL": "5"}):
            val = get_int("TEST_INT_VAL", default=50, min_val=10, max_val=99)
            self.assertEqual(val, 10)

        with patch.dict(os.environ, {"TEST_INT_VAL": "invalid_number"}):
            val = get_int("TEST_INT_VAL", default=50, min_val=10, max_val=99)
            self.assertEqual(val, 50)

    def test_get_str_trim(self):
        """测试字符串环境变量读取与空白字符修剪"""
        with patch.dict(os.environ, {"TEST_STR_VAL": "  hello world  "}):
            val = get_str("TEST_STR_VAL", default="")
            self.assertEqual(val, "hello world")

    def test_get_bool(self):
        """测试布尔型环境变量读取与解析"""
        from app.config import get_bool
        with patch.dict(os.environ, {"TEST_BOOL": "true"}):
            self.assertTrue(get_bool("TEST_BOOL", False))
        with patch.dict(os.environ, {"TEST_BOOL": "1"}):
            self.assertTrue(get_bool("TEST_BOOL", False))
        with patch.dict(os.environ, {"TEST_BOOL": "false"}):
            self.assertFalse(get_bool("TEST_BOOL", True))
        with patch.dict(os.environ, {"TEST_BOOL": ""}):
            self.assertTrue(get_bool("TEST_BOOL", True))

    def test_butler_config_load_and_override(self):
        """测试 ButlerConfig 加载与环境覆盖"""
        with patch.dict(os.environ, {
            "CPU_THRESHOLD": "92",
            "DISK_THRESHOLD": "98",
            "DEFAULT_CITY": "上海",
            "ALARM_COOLDOWN": "1800",
            "FAIL2BAN_CONTAINER_NAME": "guard",
            "ENABLE_PC_POWER": "true",
            "TARGET_PC_MAC": "AA:BB:CC:DD:EE:FF"
        }):
            cfg = ButlerConfig.load()
            self.assertEqual(cfg.cpu_threshold, 92)
            self.assertEqual(cfg.disk_threshold, 98)
            self.assertEqual(cfg.default_city, "上海")
            self.assertEqual(cfg.alarm_cooldown, 1800)
            self.assertEqual(cfg.fail2ban_container_name, "guard")
            self.assertTrue(cfg.enable_pc_power)
            self.assertEqual(cfg.target_pc_mac, "AA:BB:CC:DD:EE:FF")

    def test_settings_proxy_dynamic_reflection(self):
        """测试 SettingsProxy 动态环境感知与单测属性覆盖"""
        # 1. 动态感知环境变量 patch
        with patch.dict(os.environ, {"DEFAULT_CITY": "深圳", "DEFAULT_LANGUAGE": "en"}):
            self.assertEqual(settings.default_city, "深圳")
            self.assertEqual(settings.default_language, "en")

        # 2. 动态支持直接属性覆盖与 reload() 重置
        try:
            settings.default_city = "杭州"
            self.assertEqual(settings.default_city, "杭州")
        finally:
            settings.reload()

        # 3. 访问不存在字段抛出 AttributeError
        with self.assertRaises(AttributeError):
            _ = settings.non_existent_key_xyz


if __name__ == "__main__":
    unittest.main()
