"""NoVPNAdapter — no-op passthrough. Used when network_profile.provider == 'None'."""

from __future__ import annotations

from typing import Optional

from vpn.adapter import VPNAdapter


class NoVPNAdapter(VPNAdapter):
    async def connect(self, credentials: Optional[dict[str, str]], country: Optional[str]) -> None:
        return

    async def disconnect(self) -> None:
        return

    async def rotate(self) -> None:
        return

    async def status(self) -> str:
        return "disconnected"
