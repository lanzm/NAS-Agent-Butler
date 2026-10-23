# -*- coding: utf-8 -*-
"""
test_p1_reliability.py - P1 级别架构与可靠性重构单元回归测试
"""

import time
import unittest
import threading
from app.mcp_client import MCPClient
from app.docker_client import get_docker_client
from app.weather_calendar_helper import get_calendar_info


class TestP1Reliability(unittest.TestCase):

    def test_mcp_client_tools_caching_and_thread_safety(self):
        """测试 MCPClient 工具定义缓存与并发自增 ID 的线程安全性"""
        client = MCPClient()
        client.start()
        try:
            tools_first = client.get_openai_tools()
            self.assertIsInstance(tools_first, list)
            self.assertGreater(len(tools_first), 0)

            # 再次获取，指针应完全一致（命中内存缓存）
            tools_second = client.get_openai_tools()
            self.assertIs(tools_first, tools_second)

            # 强制刷新，返回新列表
            tools_refreshed = client.get_openai_tools(force_refresh=True)
            self.assertEqual(len(tools_first), len(tools_refreshed))

            # 并发请求自增 ID 线程安全测试
            generated_ids = set()
            lock = threading.Lock()

            def worker():
                for _ in range(50):
                    req_id = client._next_id()
                    with lock:
                        generated_ids.add(req_id)

            threads = [threading.Thread(target=worker) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # 10 线程 * 50 次 = 500 个独立不重复的 ID
            self.assertEqual(len(generated_ids), 500)
        finally:
            client.stop()

    def test_docker_client_singleton(self):
        """测试 Docker 客户端的单例模式调用"""
        c1 = get_docker_client()
        c2 = get_docker_client()
        self.assertIs(c1, c2)

    def test_weather_calendar_info_integration(self):
        """测试日历与生活信息的聚合与回退保障"""
        cal = get_calendar_info()
        self.assertIn("solar_date", cal)
        self.assertIn("lunar_date", cal)
        self.assertNotEqual(cal["lunar_date"], "农历未知")
        self.assertIn("formatted_calendar", cal)
        self.assertIn("countdown_summary", cal)


if __name__ == "__main__":
    unittest.main()
