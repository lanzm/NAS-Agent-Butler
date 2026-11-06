# -*- coding: utf-8 -*-
"""
tests/test_doctor.py - SystemDoctor 系统自检核心逻辑与各检查项测试
"""

import unittest
from unittest.mock import patch, MagicMock
import requests
from app.doctor import SystemDoctor, format_cli_report


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

    @patch("app.doctor.pc_power_plugin.is_enabled", return_value=True)
    def test_pc_power_check_invalid_mac(self, _):
        with patch("app.doctor.settings") as mock_settings:
            mock_settings.target_pc_mac = "12:34:invalid"
            res = self.doctor.check_pc_power()
            self.assertEqual(res["status"], "warning")
            self.assertIn("格式非法", res["message"])

    @patch("app.doctor.requests.get")
    def test_ai_gateway_timeout_and_error(self, mock_get):
        # 1. 超时异常
        mock_get.side_effect = requests.Timeout()
        with patch("app.doctor.settings") as mock_settings:
            mock_settings.openai_api_base = "https://gemini.example.com/v1beta/openai"
            mock_settings.ai_api_key = "test_key"
            res = self.doctor.check_ai_gateway()
            self.assertEqual(res["status"], "error")
            self.assertIn("超时", res["message"])

        # 2. 连接重置 / 握手异常
        mock_get.side_effect = Exception("Connection refused")
        with patch("app.doctor.settings") as mock_settings:
            mock_settings.openai_api_base = "https://gemini.example.com/v1beta/openai"
            mock_settings.ai_api_key = "test_key"
            res = self.doctor.check_ai_gateway()
            self.assertEqual(res["status"], "error")
            self.assertIn("网络握手失败", res["message"])

    def test_format_cli_report_healthy(self):
        diag = {
            "overall_status": "healthy",
            "summary": "所有服务运行正常",
            "checks": {
                "docker": {"status": "ok", "message": "Docker 守护进程连通"},
                "ai_gateway": {"status": "ok", "message": "模型端点往返延迟 120ms"}
            },
            "suggestions": []
        }
        report = format_cli_report(diag)
        self.assertIn("综合评定: [HEALTHY]", report)
        self.assertIn("PASS", report)
        self.assertIn("Docker 守护进程连通", report)

    def test_format_cli_report_with_errors_and_suggestions(self):
        diag = {
            "overall_status": "error",
            "summary": "发现 1 项错误，1 项警告",
            "checks": {
                "docker": {"status": "error", "message": "Docker 连接断开"},
                "pc_power": {"status": "warning", "message": "MAC 格式不规范"},
                "aria2": {"status": "disabled", "message": "未启用"}
            },
            "suggestions": [
                "检查宿主机 docker.sock 挂载及容器权限",
                "请在 .env 中正确配置 TARGET_PC_MAC 地址"
            ]
        }
        report = format_cli_report(diag)
        self.assertIn("综合评定: [ERROR]", report)
        self.assertIn("FAIL", report)
        self.assertIn("WARN", report)
        self.assertIn("OFF", report)
        self.assertIn("修复建议:", report)
        self.assertIn("检查宿主机 docker.sock", report)

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
