"""
NordAdapter — NordVPN over OpenVPN, on the SAME shared OpenVPNAdapter base as
PIA (connect / IP-verify / daemon / teardown are inherited, not re-implemented).

Only Nord-specific config sourcing lives here:
  1. Ask Nord's public recommendations API for the best server in the desired
     country (ISO-2 -> Nord country_id map; falls back to global best).
  2. Download that single server's UDP .ovpn config.

Auth: Nord *service credentials* (a username/password pair from the Nord
dashboard "Manual setup" — NOT your account email/password, and NOT the Linux
app "service token"). They map onto network_profile.username / .password, the
same shape PIA uses, so FGOS storage/credential-fetch is unchanged.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

import requests

from logger import get_logger
from vpn.openvpn_common import OpenVPNAdapter

log = get_logger(__name__)

_RECOMMEND_URL = "https://api.nordvpn.com/v1/servers/recommendations"
_CONFIG_URL_TMPL = "https://downloads.nordcdn.com/configs/files/ovpn_udp/servers/{host}.udp.ovpn"
_CONFIG_DIR = Path(tempfile.gettempdir()) / "fgos_nord_configs"

# ISO-2 country code -> Nord country_id (common set; extend as needed).
_NORD_COUNTRY_ID = {
    "US": 228, "GB": 227, "UK": 227, "DE": 81, "CA": 38, "AU": 13,
    "NL": 153, "FR": 74, "SE": 208, "CH": 209, "SG": 195, "JP": 108,
}


class NordAdapter(OpenVPNAdapter):
    provider_name = "Nord"

    def _recommended_host(self, country: Optional[str]) -> str:
        params: dict[str, object] = {"limit": 1}
        cid = _NORD_COUNTRY_ID.get((country or "").strip().upper()[:2]) if country else None
        if cid:
            params["filters[country_id]"] = cid
        resp = requests.get(_RECOMMEND_URL, params=params, timeout=20)
        resp.raise_for_status()
        servers = resp.json()
        if not servers:
            raise RuntimeError(f"Nord recommendations API returned no servers for country={country!r}.")
        host = servers[0].get("hostname")
        if not host:
            raise RuntimeError("Nord recommendations API response missing hostname.")
        log.info("Nord recommended server for %s: %s", country or "auto", host)
        return host

    async def _resolve_config(self, country: Optional[str]) -> Path:
        host = self._recommended_host(country)
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        config_path = _CONFIG_DIR / f"{host}.udp.ovpn"
        if not config_path.exists():
            url = _CONFIG_URL_TMPL.format(host=host)
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            config_path.write_bytes(resp.content)
        return config_path
