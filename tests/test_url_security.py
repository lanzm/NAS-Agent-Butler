import unittest
from unittest.mock import patch

from app.url_security import fetch_public_url, validate_public_url


class TestPublicURLSecurity(unittest.TestCase):
    def test_rejects_private_literal_addresses_and_credentials(self):
        for url in (
            "http://127.0.0.1/",
            "http://10.1.2.3/",
            "http://169.254.169.254/latest/meta-data/",
            "http://[::1]/",
            "http://user:pass@example.com/",
        ):
            with self.subTest(url=url):
                allowed, _ = validate_public_url(url)
                self.assertFalse(allowed)

    def test_rejects_dns_name_resolving_to_private_address(self):
        private_addr = (2, 1, 6, "", ("192.168.1.9", 443))
        with patch("app.url_security.socket.getaddrinfo", return_value=[private_addr]):
            allowed, message = validate_public_url("https://public.example/path")
        self.assertFalse(allowed)
        self.assertIn("目标地址不允许访问", message)

    def test_rejects_mixed_public_and_private_dns_answers(self):
        answers = [
            (2, 1, 6, "", ("8.8.8.8", 443)),
            (2, 1, 6, "", ("10.0.0.2", 443)),
        ]
        with patch("app.url_security.socket.getaddrinfo", return_value=answers):
            allowed, _ = validate_public_url("https://mixed.example/path")
        self.assertFalse(allowed)

    @patch("app.url_security._PinnedHTTPConnection")
    @patch("app.url_security._PinnedHTTPSConnection")
    def test_redirect_target_is_revalidated(self, mock_https_conn, mock_http_conn):
        from app.url_security import _resolve_public as real_resolve

        def resolve_side_effect(host, port):
            if host == "public.example":
                return ["8.8.8.8"]
            return real_resolve(host, port)

        with patch("app.url_security._resolve_public", side_effect=resolve_side_effect):
            first = mock_https_conn.return_value
            first_response = first.getresponse.return_value
            first_response.status = 302
            first_response.getheader.return_value = "http://127.0.0.1/admin"
            with self.assertRaisesRegex(ValueError, "目标地址不允许访问"):
                fetch_public_url("https://public.example/start")

    @patch("app.url_security._resolve_public", return_value=["8.8.8.8"])
    @patch("app.url_security._PinnedHTTPSConnection")
    def test_response_body_is_bounded(self, mock_connection, _mock_resolve):
        response = mock_connection.return_value.getresponse.return_value
        response.status = 200
        response.getheader.return_value = "text/html"
        response.read.return_value = b"x" * 5
        with self.assertRaisesRegex(ValueError, "超过大小限制"):
            fetch_public_url("https://public.example/", max_bytes=4)


if __name__ == "__main__":
    unittest.main()
