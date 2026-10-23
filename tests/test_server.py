# -*- coding: utf-8 -*-
"""
tests/test_server.py - 内部 Webhook 服务、健康检查端点与 Docker 客户端单例测试
"""

import io
import unittest
from unittest.mock import MagicMock
from app.main import InternalNotifyHandler
from app.docker_client import get_docker_client


class TestInternalWebhookServer(unittest.TestCase):
    """测试内部 Webhook 与健康检查端点"""

    def test_health_check_get(self):
        handler = InternalNotifyHandler.__new__(InternalNotifyHandler)
        handler.path = "/health"
        handler.wfile = io.BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        handler.do_GET()
        handler.send_response.assert_called_with(200)
        self.assertIn(b"healthy", handler.wfile.getvalue())

    def test_not_found_get(self):
        handler = InternalNotifyHandler.__new__(InternalNotifyHandler)
        handler.path = "/unknown_path"
        handler.send_response = MagicMock()
        handler.end_headers = MagicMock()

        handler.do_GET()
        handler.send_response.assert_called_with(404)


class TestDockerClient(unittest.TestCase):
    """测试 Docker 客户端的单例模式"""

    def test_docker_client_singleton(self):
        c1 = get_docker_client()
        c2 = get_docker_client()
        self.assertIs(c1, c2)


if __name__ == "__main__":
    unittest.main()
