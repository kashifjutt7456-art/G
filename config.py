"""
Buyer Network Runner — configuration.

Env-var only. No hardcoded paths, no hardcoded secrets (VVRO's original sin).
"""

from __future__ import annotations

import os
import random
import socket
from dataclasses import dataclass


def _bool_env(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Config:
    # FGOS backend
    api_url: str = os.environ.get(
        "FGOS_API_URL", "https://api.fgos.site/api/v1/ingestion/buyer-network"
    )
    api_key: str = os.environ.get("BUYER_NETWORK_API_KEY", "")

    # Runner identity (stable id recommended so heartbeat history is legible)
    runner_id: str = os.environ.get(
        "RUNNER_ID", f"bn-runner-{socket.gethostname()[-8:]}-{random.randint(1000, 9999)}"
    )

    # Loop tuning
    poll_interval_sec: float = float(os.environ.get("BN_POLL_INTERVAL_SEC", "5"))
    heartbeat_interval_sec: float = float(os.environ.get("BN_HEARTBEAT_INTERVAL_SEC", "20"))
    http_timeout_sec: float = float(os.environ.get("BN_HTTP_TIMEOUT_SEC", "20"))
    http_retries: int = int(os.environ.get("BN_HTTP_RETRIES", "3"))

    # Debug/dev
    dry_run: bool = _bool_env("BN_DRY_RUN", False)

    def validate(self) -> None:
        if not self.api_key:
            raise RuntimeError(
                "BUYER_NETWORK_API_KEY is required (dedicated key — do NOT reuse SCRAPER_API_KEY)."
            )
