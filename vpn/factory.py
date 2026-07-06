"""VPN adapter factory — instantiates the adapter FGOS chose via
job.network_profile.provider. The runner never decides the network."""

from __future__ import annotations

from vpn.adapter import VPNAdapter
from vpn.no_vpn_adapter import NoVPNAdapter
from vpn.nord_adapter import NordAdapter
from vpn.pia_adapter import PIAAdapter

_REGISTRY: dict[str, type[VPNAdapter]] = {
    "PIA": PIAAdapter,
    "Nord": NordAdapter,
    "None": NoVPNAdapter,
}


def create_vpn_adapter(provider: str) -> VPNAdapter:
    cls = _REGISTRY.get(provider, NoVPNAdapter)
    return cls()
