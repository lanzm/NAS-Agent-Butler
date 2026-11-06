# -*- coding: utf-8 -*-
"""安全边界回归测试：Aria2 下载目标与可选插件权限。"""

import os
import unittest
from unittest.mock import patch

from app.plugins import aria2_plugin, firewall_plugin, pc_power_plugin


class TestAria2Security(unittest.TestCase):
    def test_rejects_local_private_reserved_and_unsupported_targets(self):
        for url in (
            "http://127.0.0.1:8999/notify",
            "http://localhost/admin",
            "http://10.0.0.5/",
            "https://169.254.169.254/latest/meta-data/",
            "https://[::ffff:127.0.0.1]/",
            "ftp://example.com/file",
            "file:///etc/passwd",
            "magnet:?dn=test_without_xt",
        ):
            with self.subTest(url=url):
                allowed, _ = aria2_plugin.validate_download_url(url)
                self.assertFalse(allowed)

    def test_allows_valid_magnet_links(self):
        magnet_url = "magnet:?xt=urn:btih:7604944FD0648D444D20E54AA0A597E3B2C1417B"
        allowed, msg = aria2_plugin.validate_download_url(magnet_url)
        self.assertTrue(allowed)
        self.assertEqual(msg, "")

    def test_rejects_public_hostname_with_private_dns_answer(self):
        private_addr = (2, 1, 6, "", ("192.168.1.10", 443))
        with patch("app.url_security.socket.getaddrinfo", return_value=[private_addr]):
            allowed, message = aria2_plugin.validate_download_url("https://public.example/file")
        self.assertFalse(allowed)
        self.assertIn("安全拦截", message)

    def test_aria2_action_execution(self):
        with patch.dict(os.environ, {"ARIA2_RPC_URL": "http://127.0.0.1:6800/jsonrpc"}):
            with patch("app.plugins.aria2_plugin.rpc_call") as mock_rpc:
                # Test add
                mock_rpc.return_value = "2089b05e0a3f40dc"
                result = aria2_plugin.execute({
                    "action": "add",
                    "url": "magnet:?xt=urn:btih:7604944FD0648D444D20E54AA0A597E3B2C1417B"
                })
                self.assertEqual(result["status"], "success")
                self.assertEqual(result["gid"], "2089b05e0a3f40dc")

                # Test pause
                mock_rpc.return_value = "2089b05e0a3f40dc"
                result = aria2_plugin.execute({"action": "pause", "gid": "2089b05e0a3f40dc"})
                self.assertEqual(result["status"], "success")

                # Test unpause
                mock_rpc.return_value = "2089b05e0a3f40dc"
                result = aria2_plugin.execute({"action": "unpause", "gid": "2089b05e0a3f40dc"})
                self.assertEqual(result["status"], "success")

                # Test remove
                mock_rpc.return_value = "2089b05e0a3f40dc"
                result = aria2_plugin.execute({"action": "remove", "gid": "2089b05e0a3f40dc"})
                self.assertEqual(result["status"], "success")


class TestOptionalPlugins(unittest.TestCase):
    def test_firewall_disabled_until_non_exec_api_available(self):
        self.assertFalse(firewall_plugin.is_enabled())
        self.assertEqual(firewall_plugin.execute({"action": "status"})["status"], "error")

    def test_plugin_classes_follow_contract(self):
        from app.plugins.base import BasePlugin
        from app.plugins.firewall_plugin import FirewallPlugin
        from app.plugins.aria2_plugin import Aria2Plugin
        from app.plugins.pc_power_plugin import PCPowerPlugin

        for plugin in (FirewallPlugin(), Aria2Plugin(), PCPowerPlugin()):
            self.assertIsInstance(plugin, BasePlugin)
            self.assertTrue(plugin.name)
            self.assertIn("name", plugin.tool_spec)
            self.assertIsInstance(plugin.is_enabled(), bool)


if __name__ == "__main__":
    unittest.main()
