"""
VPNAdapter — interface. FGOS decides the network per campaign/account via the
job's network_profile (provider: PIA | Nord | None); the runner just
instantiates the matching adapter. Deliberately NOT VVRO's piactl.exe
(Windows-desktop-only, not GitHub-runner-portable) — real adapters use
OpenVPN config files, same as the existing scraper fleet workflow.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class VPNAdapter(ABC):
    @abstractmethod
    async def connect(self, credentials: Optional[dict[str, str]], country: Optional[str]) -> None:
        """Establish the VPN/proxy connection. No-op for NoVPNAdapter."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Tear down the connection. Must be safe to call twice."""

    @abstractmethod
    async def rotate(self) -> None:
        """Rotate to a different exit node/region, if supported."""

    @abstractmethod
    async def status(self) -> str:
        """'connected' | 'disconnected' | 'error'."""

    def as_proxy(self) -> Optional[dict[str, str]]:
        """If this adapter exposes itself as a local HTTP/SOCKS proxy (rather
        than a system-level VPN interface), return the proxy dict the
        BrowserAdapter should use. None means "no proxy — VPN is system-wide
        or absent"."""
        return None
