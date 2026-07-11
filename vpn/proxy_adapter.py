from __future__ import annotations

from typing import Any, Optional

from logger import get_logger
from vpn.adapter import VPNAdapter

log = get_logger(__name__)


class ProxyAdapter(VPNAdapter):
    """
    ProxyAdapter — exposes residential or static proxies directly to the
    BrowserAdapter via as_proxy(). Unlike OpenVPN adapters (PIA/Nord), this does
    NOT establish a system-level VPN tunnel; instead, it returns the HTTP/SOCKS
    credentials which Camoufox/Playwright loads directly.
    """

    def __init__(self) -> None:
        self._connected = False
        self._proxy_dict: Optional[dict[str, Any]] = None

    async def connect(self, credentials: Optional[dict[str, Any]], country: Optional[str]) -> None:
        if not credentials:
            raise RuntimeError("Proxy credentials missing.")

        username = credentials.get("username")
        password = credentials.get("password")
        metadata = credentials.get("metadata") or {}

        host = metadata.get("host") or credentials.get("host")
        port = metadata.get("port") or credentials.get("port")
        scheme = metadata.get("scheme") or credentials.get("scheme") or "http"

        if not host or not port:
            raise RuntimeError(f"Proxy host/port missing in profile metadata: {metadata}")

        self._proxy_dict = {
            "host": str(host),
            "port": int(port),
            "username": username,
            "password": password,
            "scheme": scheme,
        }
        self._connected = True
        log.info("Proxy configuration resolved: %s://%s:%s", scheme, host, port)

    async def disconnect(self) -> None:
        self._proxy_dict = None
        self._connected = False

    async def rotate(self) -> None:
        pass

    async def status(self) -> str:
        return "connected" if self._connected else "disconnected"

    def as_proxy(self) -> Optional[dict[str, Any]]:
        return self._proxy_dict
