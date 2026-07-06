"""
Buyer Network Runner — API client.

Thin HTTP wrapper over FGOS's existing claim/heartbeat/result/credentials
protocol (backend/src/modules/buyer_network/buyer-network-bot.controller.ts).
FGOS is the brain: this client only moves bytes, it never decides what job to
run or what to send. Retries with backoff, same pattern as the scraper
fleet's fgos_api() helper (Minimal scrapper/Mainbot_http.py) — proven in
production for this repo.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import requests

from config import Config
from logger import get_logger

log = get_logger(__name__)


class ApiClient:
    def __init__(self, config: Config):
        self.config = config
        self.headers = {
            "Content-Type": "application/json",
            "x-api-key": config.api_key,
        }

    def _post(self, path: str, payload: dict) -> Optional[dict[str, Any]]:
        url = f"{self.config.api_url}/{path}"
        last_err: Optional[str] = None
        for attempt in range(self.config.http_retries):
            try:
                resp = requests.post(
                    url, json=payload, headers=self.headers, timeout=self.config.http_timeout_sec
                )
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except ValueError:
                        return {}
                last_err = f"HTTP {resp.status_code}: {resp.text[:300]}"
                log.warning("[%s] attempt %d/%d: %s", path, attempt + 1, self.config.http_retries, last_err)
            except requests.RequestException as e:
                last_err = str(e)
                log.warning("[%s] attempt %d/%d: %s", path, attempt + 1, self.config.http_retries, last_err)
            if attempt < self.config.http_retries - 1:
                time.sleep(2 ** attempt)
        log.error("[%s] FAILED after %d attempts: %s", path, self.config.http_retries, last_err)
        return None

    # ── Runner protocol ──────────────────────────────────────────────────────
    def claim(self) -> Optional[dict[str, Any]]:
        """Claim the next available job. Returns {status, job?} or None on
        transport failure (caller should back off and retry, not crash)."""
        return self._post("claim", {"runner_id": self.config.runner_id})

    def heartbeat(
        self,
        job_id: Optional[str] = None,
        status: str = "online",
        browser_status: Optional[str] = None,
        browser_type: Optional[str] = None,
        network_provider: Optional[str] = None,
        network_status: Optional[str] = None,
        current_step: Optional[str] = None,
        account_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Reports liveness. Response may include kill=True — the campaign was
        paused/cancelled server-side; the runner MUST abort the current job.
        browser_type/network_provider/network_status are display-only fields
        for the Workers tab (which browser engine + VPN this runner is using)."""
        payload: dict[str, Any] = {"runner_id": self.config.runner_id, "status": status}
        if job_id:
            payload["job_id"] = job_id
        if browser_status:
            payload["browser_status"] = browser_status
        if browser_type:
            payload["browser_type"] = browser_type
        if network_provider:
            payload["network_provider"] = network_provider
        if network_status:
            payload["network_status"] = network_status
        if current_step:
            payload["current_step"] = current_step
        if account_id:
            payload["account_id"] = account_id
        return self._post("heartbeat", payload)

    def report(
        self,
        job_id: str,
        state: str,
        error_reason: Optional[str] = None,
        screenshots: Optional[list[str]] = None,
        log_refs: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        account_result: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        """Report the terminal outcome of a job. state must be one of
        COMPLETED | FAILED | BLOCKED | NEEDS_REVIEW."""
        payload: dict[str, Any] = {
            "runner_id": self.config.runner_id,
            "job_id": job_id,
            "state": state,
        }
        if error_reason:
            payload["error_reason"] = error_reason
        if screenshots:
            payload["screenshots"] = screenshots
        if log_refs:
            payload["log_refs"] = log_refs
        if metadata:
            payload["metadata"] = metadata
        if account_result:
            payload["account_result"] = account_result
        return self._post("result", payload)

    # ── Credentials — the ONLY way the runner learns a real secret. Fetched
    #    on demand, authenticated, and audited server-side on every call. ────
    def get_account_credentials(self, account_id: str) -> Optional[dict[str, Any]]:
        res = self._post("credentials/account", {"runner_id": self.config.runner_id, "account_id": account_id})
        if not res or res.get("status") != "ok":
            return None
        return res.get("credentials")

    def get_network_credentials(self, profile_id: str) -> Optional[dict[str, Any]]:
        res = self._post("credentials/network", {"runner_id": self.config.runner_id, "profile_id": profile_id})
        if not res or res.get("status") != "ok":
            return None
        return res.get("credentials")

    # ── Attachments — step-2 inbox upload. Bytes are fetched on demand
    #    (base64-over-JSON), same pattern as credential lookups. ────────────────
    def get_attachment(self, attachment_id: str) -> Optional[dict[str, Any]]:
        res = self._post("attachments/download", {"runner_id": self.config.runner_id, "attachment_id": attachment_id})
        if not res or res.get("status") != "ok":
            return None
        return res.get("attachment")
