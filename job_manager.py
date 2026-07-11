"""
JobManager — claim loop + job_type dispatch.

This is the ONLY place that branches on job_type, and even here it's just
"which handler module do I call" — the handler modules themselves receive a
fully-resolved job payload from FGOS (target, message, browser_profile,
network_profile already decided) and never make their own decisions about
what to do next. No local retry/backoff logic beyond "wait and poll again" —
FGOS's stuck-job auto-release cron handles jobs a runner never reports back.
"""

from __future__ import annotations

import asyncio
from typing import Any

from accounts import AccountManager
from api_client import ApiClient
from browser.factory import create_browser_adapter
from config import Config
from logger import get_logger
from outreach import send_message
from account_creation import create_buyer_account
from reporter import Reporter
from vpn.factory import create_vpn_adapter

log = get_logger(__name__)

_HANDLERS = {
    "SEND_MESSAGE": send_message.run,
    "CREATE_BUYER_ACCOUNT": create_buyer_account.run,
    # "CHECK_MESSAGES": ...   # future
    # "FOLLOW_UP": ...        # future — still just "send this now", not cadence logic
}


class JobManager:
    def __init__(self, config: Config, api: ApiClient):
        self.config = config
        self.api = api
        self.accounts = AccountManager(api)
        # Guards against the idle heartbeat loop racing a job's own heartbeats
        # (both would otherwise clobber current_job_id/current_step server-side).
        self.busy = False

    async def run_forever(self) -> None:
        log.info("Runner %s starting claim loop", self.config.runner_id)
        while True:
            job = await self._claim_once()
            if job is None:
                await asyncio.sleep(self.config.poll_interval_sec)
                continue
            self.busy = True
            try:
                await self._execute(job)
            except Exception as e:  # noqa: BLE001 - one job failing must not kill the runner
                log.exception("Unhandled error executing job %s: %s", job.get("job_id"), e)
                self.api.report(job_id=job["job_id"], state="FAILED", error_reason=f"unhandled: {e}")
            finally:
                self.busy = False

    async def _claim_once(self) -> dict[str, Any] | None:
        res = self.api.claim()
        if res is None:
            return None  # transport failure — poll loop backs off and retries
        if res.get("status") != "ok":
            return None  # 'none' (nothing claimable) or 'error' — both just wait
        return res.get("job")

    async def _execute(self, job: dict[str, Any]) -> None:
        job_type = job.get("job_type", "SEND_MESSAGE")
        handler = _HANDLERS.get(job_type)
        if handler is None:
            log.error("No handler for job_type '%s' — reporting FAILED", job_type)
            self.api.report(job_id=job["job_id"], state="FAILED", error_reason=f"unsupported job_type: {job_type}")
            return

        account = job.get("account") or {}
        browser_profile = job.get("browser_profile") or {"browser_type": "camoufox", "fingerprint_config": {}}
        network_profile = job.get("network_profile")

        reporter = Reporter(
            self.api, job_id=job["job_id"], account_id=account.get("account_id"),
            browser_type=browser_profile.get("browser_type"),
            network_provider=(network_profile or {}).get("provider", "None"),
        )

        vpn = create_vpn_adapter((network_profile or {}).get("provider", "None"))
        proxy: dict[str, Any] | None = None
        if network_profile and network_profile.get("provider") not in (None, "None"):
            if not reporter.step(f"Connecting network ({network_profile['provider']})"):
                reporter.blocked("Aborted by FGOS (campaign paused) before network connect")
                return
            net_creds = self.accounts.load_network_credentials(network_profile["profile_id"])
            try:
                await vpn.connect(net_creds, network_profile.get("country") or "US")
                proxy = vpn.as_proxy()
                reporter.network_status = await vpn.status()
                # Surface before/after IP + exit country in the live Workers feed
                # (OpenVPN adapters expose ip_summary(); NoVPN does not).
                ip_summary = getattr(vpn, "ip_summary", None)
                if callable(ip_summary):
                    reporter.step(f"VPN {network_profile['provider']} up: {ip_summary()}")
            except Exception as e:  # noqa: BLE001
                reporter.network_status = "error"
                reporter.fail(f"VPN connect failed: {e}")
                return

        primary_browser = browser_profile.get("browser_type", "camoufox")
        # Build priority queue of browsers to attempt
        engines_to_try = [primary_browser]
        all_engines = ["cloakbrowser", "camoufox", "nodriver", "playwright_chromium"]
        for eng in all_engines:
            if eng not in engines_to_try:
                engines_to_try.append(eng)

        success = False
        last_error = None
        browser = None

        for engine in engines_to_try:
            reporter.step(f"Attempting job execution using browser: {engine}")
            try:
                browser = create_browser_adapter(engine)
            except ValueError as e:
                reporter.step(f"Skipping browser {engine} (not configured/implemented): {e}")
                continue

            try:
                if not reporter.step(f"Starting browser: {engine}"):
                    reporter.blocked(f"Aborted by FGOS before starting browser: {engine}")
                    return
                
                await browser.start(browser_profile.get("fingerprint_config", {}), proxy)
                
                # Real credentials are fetched here, never carried in the job payload.
                if account.get("account_id") and job_type != "CREATE_BUYER_ACCOUNT":
                    creds = self.accounts.load_account_credentials(account["account_id"])
                    if creds is None:
                        reporter.fail(f"Could not fetch credentials for account {account['account_id']}")
                        return
                    job = {**job, "_account_credentials": creds}
                
                job["_proxy"] = proxy
                await handler(browser, job, reporter)
                success = True
                reporter.step(f"Success with browser: {engine}")
                break
            except Exception as e:
                last_error = e
                log.warning(f"Browser {engine} failed during execution: {e}")
                reporter.step(f"Browser {engine} failed: {e}")
                try:
                    await browser.close()
                except Exception:
                    pass
                browser = None

        if not success:
            reporter.fail(f"All attempted browsers failed. Last error: {last_error}")
            return
        
        try:
            # We succeeded, so now clean up the successful browser
            if browser:
                await browser.close()
        finally:
            if network_profile and network_profile.get("provider") not in (None, "None"):
                await vpn.disconnect()
