# -*- coding: utf-8 -*-
"""
test_collector.py - 宿主机硬件采集与指标阈值告警单元测试
"""

import unittest
from unittest.mock import patch, MagicMock
from app.collector import (
    human_bytes,
    calc_container_uptime,
    SystemCollector
)


class TestCollector(unittest.TestCase):

    def test_human_bytes(self):
        """测试字节单位转换"""
        self.assertEqual(human_bytes(0), "0B")
        self.assertEqual(human_bytes(1024), "1.0KB")
        self.assertEqual(human_bytes(1024 * 1024), "1.0MB")
        self.assertEqual(human_bytes(int(1024 * 1024 * 1024 * 2.5)), "2.5GB")
        self.assertEqual(human_bytes(1024 ** 4), "1.0TB")

    @patch("app.collector.get_docker_client")
    def test_get_docker_containers_safe_image_lookup(self, mock_get_client):
        """测试容器镜像被删（悬空/已清除）时，直接安全读取 attrs 且不触发 404 崩溃"""
        mock_client = MagicMock()
        mock_c1 = MagicMock()
        mock_c1.name = "caddy"
        mock_c1.status = "running"
        mock_c1.attrs = {
            "State": {"Status": "running", "StartedAt": "2026-11-06T10:00:00Z"},
            "Config": {"Image": "caddy:2.8-alpine"}
        }

        # 模拟镜像已被 docker image prune 删掉的停止容器：c.image 如果被访问会抛异常
        mock_c2 = MagicMock()
        mock_c2.name = "old_orphaned_app"
        mock_c2.status = "exited"
        mock_c2.attrs = {
            "State": {"Status": "exited", "StartedAt": ""},
            "Config": {},
            "Image": "sha256:abcdef1234567890"
        }
        type(mock_c2).image = property(lambda self: (_ for _ in ()).throw(Exception("404 ImageNotFound")))

        mock_client.containers.list.return_value = [mock_c1, mock_c2]
        mock_get_client.return_value = mock_client

        collector = SystemCollector()
        containers, alarms = collector.get_docker_containers()

        self.assertEqual(len(containers), 2)
        self.assertEqual(containers[0]["name"], "caddy")
        self.assertEqual(containers[0]["image"], "caddy:2.8-alpine")
        self.assertEqual(containers[1]["name"], "old_orphaned_app")
        self.assertEqual(containers[1]["image"], "sha256:abcde")

    def test_calc_container_uptime_unstarted(self):
        """测试未启动容器的运行时间解析"""
        self.assertEqual(calc_container_uptime(""), "未启动")
        self.assertEqual(calc_container_uptime("0001-01-01T00:00:00Z"), "未启动")

    @patch("psutil.cpu_percent")
    @patch("psutil.virtual_memory")
    @patch("psutil.swap_memory")
    def test_collect_normal(self, mock_swap, mock_mem, mock_cpu):
        """测试正常指标下无告警"""
        mock_cpu.return_value = 20.0
        
        mem_mock = MagicMock()
        mem_mock.percent = 40.0
        mem_mock.used = 4 * (1024 ** 3)
        mem_mock.total = 16 * (1024 ** 3)
        mock_mem.return_value = mem_mock

        swap_mock = MagicMock()
        swap_mock.percent = 0.0
        swap_mock.total = 0
        mock_swap.return_value = swap_mock

        collector = SystemCollector()
        data = collector.collect()

        self.assertFalse(data["is_alarm"])
        self.assertEqual(len(data["alarms"]), 0)
        self.assertEqual(data["cpu_usage"], 20)
        self.assertEqual(data["mem_usage"], 40)

    @patch("psutil.cpu_percent")
    @patch("psutil.virtual_memory")
    @patch("psutil.swap_memory")
    def test_collect_dynamic_threshold_override(self, mock_swap, mock_mem, mock_cpu):
        """测试通过 thresholds 参数动态覆盖告警阈值"""
        mock_cpu.return_value = 50.0  # 默认阈值是 85%，此时本不应报警
        
        mem_mock = MagicMock()
        mem_mock.percent = 40.0
        mem_mock.used = 4 * (1024 ** 3)
        mem_mock.total = 16 * (1024 ** 3)
        mock_mem.return_value = mem_mock

        swap_mock = MagicMock()
        swap_mock.percent = 0.0
        swap_mock.total = 0
        mock_swap.return_value = swap_mock

        collector = SystemCollector()
        
        # 1. 默认阈值下（85%），50% 不触发告警
        data_default = collector.collect()
        self.assertFalse(data_default["is_alarm"])

        # 2. 动态传入严格阈值（cpu: 40%），50% 应该触发告警
        custom_thresholds = {"cpu": 40, "memory": 90, "disk": 95}
        data_custom = collector.collect(thresholds=custom_thresholds)
        self.assertTrue(data_custom["is_alarm"])
        self.assertTrue(any("CPU 使用率持续偏高" in a for a in data_custom["alarms"]))


if __name__ == "__main__":
    unittest.main()
