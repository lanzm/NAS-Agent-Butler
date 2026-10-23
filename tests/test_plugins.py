# -*- coding: utf-8 -*-
"""
tests/test_plugins.py - 扩展插件 (防火墙、Aria2、PC电源管理) 安全与功能测试
"""

import os
import unittest
from app.plugins import firewall_plugin, aria2_plugin, pc_power_plugin


class TestFirewallPlugin(unittest.TestCase):
    """测试防火墙插件安全校验与命令执行防注入"""

    def test_firewall_command_injection_defense(self):
        os.environ["FAIL2BAN_CONTAINER_NAME"] = "mock-guard"

        # 1. 非法 jail 名称注入拦截
        res = firewall_plugin.execute({"action": "status", "jail": "caddy; cat /etc/passwd"})
        self.assertEqual(res["status"], "error")
        self.assertIn("非法 jail 名称", res["message"])

        # 2. 目标 IP 指令注入拦截
        res = firewall_plugin.execute({"action": "unban", "jail": "caddy", "ip": "1.2.3.4; rm -rf /"})
        self.assertEqual(res["status"], "error")
        self.assertIn("目标 IP 格式非法", res["message"])


class TestAria2Plugin(unittest.TestCase):
    """测试 Aria2 插件 SSRF 拦截与协议白名单"""

    def test_aria2_ssrf_and_protocol_defense(self):
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


class TestPCPowerPlugin(unittest.TestCase):
    """测试 PC 电源管理魔包广播与参数合法性"""

    def test_invalid_mac(self):
        self.assertFalse(pc_power_plugin.send_magic_packet("invalid_mac"))
        self.assertFalse(pc_power_plugin.send_magic_packet("12:34"))

    def test_valid_mac(self):
        self.assertTrue(pc_power_plugin.send_magic_packet("00:11:22:33:44:55"))
        self.assertTrue(pc_power_plugin.send_magic_packet("AA-BB-CC-DD-EE-FF"))


if __name__ == "__main__":
    unittest.main()
