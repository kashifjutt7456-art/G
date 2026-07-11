"""
openvpn_common — shared OpenVPN plumbing for every config-file-based VPN
adapter (PIA, Nord, …). Concentrates the logic that used to live only in
PIAAdapter so a second provider does NOT copy-paste it:

  • openvpn binary presence check
  • credential validation
  • public-IP capture (before) + verification (after) with country/ISP
  • `sudo openvpn --daemon` launch + wait-for-"Initialization Sequence
    Completed" / fail-fast on AUTH_FAILED / timeout
  • disconnect / status

A concrete adapter only implements `provider_name` and `_resolve_config()`
(where its .ovpn comes from). Same OpenVPN-config approach the scraper fleet
workflow already uses — NOT VVRO's Windows-only piactl.exe.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

from logger import get_logger
from vpn.adapter import VPNAdapter

log = get_logger(__name__)

_IP_LOOKUP_URL = "http://ip-api.com/json"


@dataclass
class IPInfo:
    ip: str
    country: Optional[str] = None
    isp: Optional[str] = None

    def __str__(self) -> str:
        return f"{self.ip}" + (f" ({self.country})" if self.country else "")


def get_public_ip(timeout: float = 10.0) -> Optional[IPInfo]:
    """Best-effort public IP + country/ISP. Returns None on failure (caller
    decides whether that's fatal)."""
    try:
        resp = requests.get(_IP_LOOKUP_URL, timeout=timeout)
        if resp.status_code == 200:
            d = resp.json()
            if d.get("status") == "success" or d.get("query"):
                return IPInfo(ip=d.get("query", ""), country=d.get("countryCode") or d.get("country"), isp=d.get("isp"))
    except Exception as e:  # noqa: BLE001
        log.warning("public IP lookup failed: %s", e)
    return None


class OpenVPNAdapter(VPNAdapter):
    """Base for OpenVPN-config providers. Subclass implements provider_name +
    _resolve_config()."""

    #: overridden by subclass
    provider_name: str = "OpenVPN"

    def __init__(self) -> None:
        self._proc_started = False
        self._connected = False
        self._log_path = Path(tempfile.gettempdir()) / f"fgos_{self.provider_name.lower()}_openvpn.log"
        self._auth_path = Path(tempfile.gettempdir()) / f"fgos_{self.provider_name.lower()}_auth.txt"
        self.before_ip: Optional[IPInfo] = None
        self.after_ip: Optional[IPInfo] = None
        self.exit_country: Optional[str] = None

    # ── subclass hook ────────────────────────────────────────────────────────
    async def _resolve_config(self, country: Optional[str]) -> Path:
        """Return a local path to the .ovpn config to use for `country`."""
        raise NotImplementedError

    # ── shared connect/verify ────────────────────────────────────────────────
    async def connect(self, credentials: Optional[dict[str, str]], country: Optional[str]) -> None:
        if shutil.which("openvpn") is None:
            raise RuntimeError(
                "openvpn binary not found — install it on the runner host "
                "(the GitHub workflow does this via `apt-get install openvpn`)."
            )
        if not credentials or not credentials.get("username") or not credentials.get("password"):
            raise RuntimeError(
                f"{self.provider_name} credentials missing — fetch via "
                "api_client.get_network_credentials()."
            )

        # 1) Capture IP BEFORE the tunnel (the runner's own exit).
        self.before_ip = get_public_ip()
        log.info("[%s] IP before VPN: %s", self.provider_name, self.before_ip or "unknown")

        # 2) Resolve the provider-specific config + write the auth file.
        config_path = await self._resolve_config(country)
        self._auth_path.write_text(f"{credentials['username']}\n{credentials['password']}\n")
        os.chmod(self._auth_path, 0o600)

        # 3) Launch OpenVPN as a daemon and wait for the tunnel.
        cmd = [
            "sudo", "openvpn",
            "--config", str(config_path),
            "--auth-user-pass", str(self._auth_path),
            "--auth-nocache",
            "--daemon",
            "--log", str(self._log_path),
        ]
        if self._log_path.exists():
            subprocess.run(["sudo", "rm", "-f", str(self._log_path)], check=False)
        subprocess.run(cmd, check=True, capture_output=True)
        self._proc_started = True
        await self._wait_for_tunnel()

        # 4) Capture IP AFTER + verify it actually changed.
        self.after_ip = get_public_ip()
        log.info("[%s] IP after VPN: %s", self.provider_name, self.after_ip or "unknown")
        if self.before_ip and self.after_ip and self.before_ip.ip and self.before_ip.ip == self.after_ip.ip:
            await self.disconnect()
            raise RuntimeError(
                f"{self.provider_name} tunnel came up but public IP did not change "
                f"({self.before_ip.ip}) — refusing to proceed."
            )
        self._connected = True
        self.exit_country = self.after_ip.country if self.after_ip else country
        log.info(
            "[%s] VPN active: %s -> %s (exit country=%s)",
            self.provider_name, self.before_ip, self.after_ip, self.exit_country,
        )

    async def _wait_for_tunnel(self, attempts: int = 30, interval: float = 2.0) -> None:
        for _ in range(attempts):
            await asyncio.sleep(interval)
            if not self._log_path.exists():
                continue
            subprocess.run(["sudo", "chmod", "644", str(self._log_path)], check=False)
            text = self._log_path.read_text(errors="ignore")
            if "Initialization Sequence Completed" in text:
                return
            if "AUTH_FAILED" in text:
                raise RuntimeError(f"{self.provider_name} VPN authentication failed.")
        raise RuntimeError(f"{self.provider_name} VPN connection timed out.")

    async def disconnect(self) -> None:
        if self._proc_started:
            subprocess.run(["sudo", "pkill", "-f", "openvpn"], capture_output=True)
        self._connected = False
        self._proc_started = False

    async def rotate(self) -> None:
        await self.disconnect()
        # Caller re-invokes connect() with a different country to rotate region.

    async def status(self) -> str:
        return "connected" if self._connected else "disconnected"

    def ip_summary(self) -> str:
        """Compact before→after string for the Workers heartbeat/current_step."""
        b = self.before_ip.ip if self.before_ip else "?"
        a = self.after_ip.ip if self.after_ip else "?"
        return f"{b} → {a} ({self.exit_country or '?'} via {self.provider_name})"
