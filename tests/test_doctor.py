# -*- coding: utf-8 -*-
"""
tests/test_doctor.py - SystemDoctor 系统自检核心逻辑与各检查项测试
"""

import unittest
from unittest.mock import patch, MagicMock
from app.doctor import SystemDoctor


class TestSystemDoctor(unittest.TestCase):
    def setUp(self):
        self.doctor = SystemDoctor()

    @patch("app.doctor.get_docker_client")
    def test_docker_check_healthy(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_c1 = MagicMock()
        mock_c1.status = "running"
        mock_c2 = MagicMock()
        mock_c2.status = "exited"
        mock_client.containers.list.return_value = [mock_c1, mock_c2]
        mock_get_client.return_value = mock_client

        res = self.doctor.check_docker()
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["total_containers"], 2)
        self.assertEqual(res["running_containers"], 1)

    @patch("app.doctor.get_docker_client", return_value=None)
    def test_docker_check_unavailable(self, _):
        res = self.doctor.check_docker()
        self.assertEqual(res["status"], "error")
        self.assertIn("无法连接", res["message"])

    @patch("app.doctor.pc_power_plugin.is_enabled", return_value=True)
    def test_pc_power_check_healthy(self, _):
        with patch("app.doctor.settings") as mock_settings:
            mock_settings.target_pc_mac = "A0:36:BC:A9:EC:2C"
            res = self.doctor.check_pc_power()
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["mac"], "A0:36:BC:A9:EC:2C")

    @patch("app.doctor.pc_power_plugin.is_enabled", return_value=False)
    def test_pc_power_check_disabled(self, _):
        with patch("app.doctor.settings") as mock_settings:
            mock_settings.enable_pc_power = False
            mock_settings.target_pc_mac = ""
            res = self.doctor.check_pc_power()
            self.assertEqual(res["status"], "disabled")

    @patch("app.doctor.aria2_plugin.is_enabled", return_value=True)
    @patch("app.doctor.aria2_plugin.rpc_call")
    def test_aria2_check_healthy(self, mock_rpc, _):
        mock_rpc.side_effect = [
            {"version": "1.36.0"},  # getVersion
            {"numActive": "1", "numWaiting": "0"}  # getGlobalStat
        ]
        res = self.doctor.check_aria2()
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["version"], "1.36.0")
        self.assertEqual(res["active_tasks"], 1)

    @patch("app.doctor.requests.get")
    def test_ai_gateway_check_healthy(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        with patch("app.doctor.settings") as mock_settings:
            mock_settings.openai_api_base = "https://gemini.example.com/v1beta/openai"
            mock_settings.ai_api_key = "test_key"
            res = self.doctor.check_ai_gateway()
            self.assertEqual(res["status"], "ok")
            self.assertIn("latency_ms", res)

    def test_run_all_diagnosis(self):
        with patch.object(self.doctor, "check_docker", return_value={"status": "ok"}):
            with patch.object(self.doctor, "check_aria2", return_value={"status": "disabled", "message": "未配置"}):
                with patch.object(self.doctor, "check_pc_power", return_value={"status": "ok"}):
                    with patch.object(self.doctor, "check_ai_gateway", return_value={"status": "ok", "latency_ms": 120}):
                        report = self.doctor.diagnose()
                        self.assertIn(report["overall_status"], ["healthy", "warning"])
                        self.assertIn("checks", report)
                        self.assertIn("summary", report)


if __name__ == "__main__":
    unittest.main()
