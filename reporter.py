"""
Reporter — thin wrapper that turns "step X happening now" into a heartbeat
call, and collects screenshot/log refs for the terminal result. FGOS's
Workers tab renders whatever current_step says, live, via WebSocket.
"""

from __future__ import annotations

from typing import Any, Optional

from api_client import ApiClient
from logger import get_logger

log = get_logger(__name__)


class Reporter:
    def __init__(
        self,
        api: ApiClient,
        job_id: str,
        account_id: Optional[str] = None,
        browser_type: Optional[str] = None,
        network_provider: Optional[str] = None,
    ):
        self.api = api
        self.job_id = job_id
        self.account_id = account_id
        # Display-only, for the Workers tab — set once from the job's resolved
        # browser_profile/network_profile and echoed on every heartbeat.
        self.browser_type = browser_type
        self.network_provider = network_provider
        self.network_status: Optional[str] = None
        self.screenshots: list[str] = []
        self.log_refs: list[str] = []

    def step(self, message: str, browser_status: str = "ok") -> bool:
        """Report the current step. Returns True if the runner should CONTINUE,
        False if FGOS says to abort (campaign paused/killed mid-job)."""
        log.info("[job %s] %s", self.job_id, message)
        res = self.api.heartbeat(
            job_id=self.job_id,
            status="online",
            browser_status=browser_status,
            browser_type=self.browser_type,
            network_provider=self.network_provider,
            network_status=self.network_status,
            current_step=message,
            account_id=self.account_id,
        )
        if res is None:
            # Transport failure — don't kill the job over a dropped heartbeat.
            return True
        return not res.get("kill", False)

    def add_screenshot_ref(self, ref: str) -> None:
        self.screenshots.append(ref)

    def add_log_ref(self, ref: str) -> None:
        self.log_refs.append(ref)

    def complete(self, metadata: Optional[dict[str, Any]] = None, account_result: Optional[dict[str, Any]] = None) -> None:
        self.api.report(
            job_id=self.job_id, state="COMPLETED",
            screenshots=self.screenshots, log_refs=self.log_refs,
            metadata=metadata or {}, account_result=account_result,
        )

    def fail(self, reason: str, metadata: Optional[dict[str, Any]] = None) -> None:
        self.api.report(
            job_id=self.job_id, state="FAILED", error_reason=reason,
            screenshots=self.screenshots, log_refs=self.log_refs, metadata=metadata or {},
        )

    def blocked(self, reason: str, metadata: Optional[dict[str, Any]] = None) -> None:
        self.api.report(
            job_id=self.job_id, state="BLOCKED", error_reason=reason,
            screenshots=self.screenshots, log_refs=self.log_refs, metadata=metadata or {},
        )

    def needs_review(self, reason: str, metadata: Optional[dict[str, Any]] = None) -> None:
        self.api.report(
            job_id=self.job_id, state="NEEDS_REVIEW", error_reason=reason,
            screenshots=self.screenshots, log_refs=self.log_refs, metadata=metadata or {},
        )
