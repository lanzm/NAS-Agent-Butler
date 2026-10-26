"""Outbound URL validation and pinned public HTTP fetching."""

import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urljoin, urlsplit


MAX_REDIRECTS = 3
MAX_RESPONSE_BYTES = 256 * 1024


def _resolve_public(hostname: str, port: int) -> list[str]:
    """Resolve a host and reject it unless every resolved address is globally routable."""
    try:
        addresses = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except (OSError, socket.gaierror) as exc:
        raise ValueError("目标主机无法解析") from exc

    ips = []
    for entry in addresses:
        ip_text = entry[4][0].split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(ip_text)
        except ValueError as exc:
            raise ValueError("目标主机解析结果无效") from exc
        if not ip.is_global:
            raise ValueError("目标地址不允许访问")
        if ip_text not in ips:
            ips.append(ip_text)
    if not ips:
        raise ValueError("目标主机没有可用地址")
    return ips


def validate_public_url(url: str, schemes=("http", "https")) -> tuple[bool, str]:
    """Validate URL syntax and reject local/private/reserved destinations."""
    try:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        if scheme not in schemes:
            return False, f"不支持的下载协议 `{scheme}`"
        if not parts.hostname or "@" in parts.netloc:
            return False, "下载链接必须包含有效主机且不能包含内嵌凭据"
        port = parts.port or (443 if scheme == "https" else 80)
        _resolve_public(parts.hostname, port)
        return True, ""
    except (ValueError, UnicodeError) as exc:
        return False, str(exc) or "下载链接无效"


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port=port, timeout=timeout)
        self._pinned_ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, port, ip, timeout, context):
        super().__init__(host, port=port, timeout=timeout, context=context)
        self._pinned_ip = ip

    def connect(self):
        raw_sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw_sock, server_hostname=self.host)
        except Exception:
            raw_sock.close()
            raise


def fetch_public_url(url: str, timeout: float = 2.5, max_bytes: int = MAX_RESPONSE_BYTES) -> bytes:
    """Fetch a public HTTP(S) URL while pinning each connection to its validated IP."""
    current_url = url
    context = ssl.create_default_context()

    for redirect_count in range(MAX_REDIRECTS + 1):
        parts = urlsplit(current_url)
        scheme = parts.scheme.lower()
        if scheme not in ("http", "https") or not parts.hostname or "@" in parts.netloc:
            raise ValueError("目标 URL 不允许访问")
        port = parts.port or (443 if scheme == "https" else 80)
        ips = _resolve_public(parts.hostname, port)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        conn_cls = _PinnedHTTPSConnection if scheme == "https" else _PinnedHTTPConnection
        conn = conn_cls(parts.hostname, port, ips[0], timeout, context) if scheme == "https" else conn_cls(parts.hostname, port, ips[0], timeout)
        try:
            conn.request("GET", path, headers={
                "User-Agent": "Mozilla/5.0 (compatible; NAS-Agent-Butler/1.0)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Connection": "close",
            })
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                response.close()
                if not location or redirect_count >= MAX_REDIRECTS:
                    raise ValueError("网页重定向次数超限或地址缺失")
                current_url = urljoin(current_url, location)
                continue
            if response.status < 200 or response.status >= 300:
                raise ValueError(f"网页返回 HTTP {response.status}")
            content_type = response.getheader("Content-Type", "").lower()
            if content_type and not any(t in content_type for t in ("text/", "application/xhtml+xml", "application/xml")):
                raise ValueError("目标内容类型不允许读取")
            payload = response.read(max_bytes + 1)
            if len(payload) > max_bytes:
                raise ValueError("网页内容超过大小限制")
            return payload
        finally:
            conn.close()
    raise ValueError("网页重定向次数超限")
