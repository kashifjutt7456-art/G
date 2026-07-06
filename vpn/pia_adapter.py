"""
PIAAdapter — PIA over OpenVPN. Only the config SOURCE lives here now; connect,
credential handling, before/after public-IP verification, daemon launch, and
teardown are shared in openvpn_common.OpenVPNAdapter (so Nord doesn't copy it).

Downloads PIA's published OpenVPN config bundle and picks the region config
matching network_profile.country (e.g. "us_east"). Deliberately NOT VVRO's
piactl.exe (Windows-desktop-only) — GitHub Ubuntu runners have openvpn, not the
PIA desktop client. Requires `openvpn` + `sudo` on the host (the workflow
provisions them when vpn=pia).
"""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path
from typing import Optional

import requests

from logger import get_logger
from vpn.openvpn_common import OpenVPNAdapter

log = get_logger(__name__)

PIA_CONFIG_ZIP_URL = "https://www.privateinternetaccess.com/openvpn/openvpn.zip"
_DEFAULT_CONFIG_DIR = Path(tempfile.gettempdir()) / "fgos_pia_configs"


class PIAAdapter(OpenVPNAdapter):
    provider_name = "PIA"

    def _ensure_configs(self) -> Path:
        if _DEFAULT_CONFIG_DIR.exists() and any(_DEFAULT_CONFIG_DIR.glob("*.ovpn")):
            return _DEFAULT_CONFIG_DIR
        _DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        zip_path = Path(tempfile.gettempdir()) / "pia_openvpn.zip"
        resp = requests.get(PIA_CONFIG_ZIP_URL, timeout=30)
        resp.raise_for_status()
        zip_path.write_bytes(resp.content)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(_DEFAULT_CONFIG_DIR)
        return _DEFAULT_CONFIG_DIR

    async def _resolve_config(self, country: Optional[str]) -> Path:
        config_dir = self._ensure_configs()
        region = country or "us_california"
        config_path = config_dir / f"{region}.ovpn"
        if not config_path.exists():
            candidates = sorted(config_dir.glob("us_*.ovpn")) or sorted(config_dir.glob("*.ovpn"))
            if not candidates:
                raise RuntimeError("No PIA OpenVPN configs found after download.")
            config_path = candidates[0]
            log.warning("PIA region '%s' not found, using '%s' instead", region, config_path.stem)
        return config_path
