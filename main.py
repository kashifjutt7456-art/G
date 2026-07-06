"""
Buyer Network Runner — entry point.

Start -> load config -> claim loop -> execute job (browser + vpn adapters
FGOS chose) -> report result -> repeat forever. FGOS is the brain: this
process makes no decisions about targets, messages, timing, or accounts. It
registers implicitly on first heartbeat/claim (no separate register call in
the current backend protocol) and heartbeats as part of each job's step
reporting; an idle heartbeat keeps the runner visible between jobs.
"""

from __future__ import annotations

import asyncio

from api_client import ApiClient
from config import Config
from job_manager import JobManager
from logger import get_logger

log = get_logger(__name__)


async def _idle_heartbeat_loop(api: ApiClient, manager: JobManager, interval_sec: float) -> None:
    """Keeps the runner visible in the Workers tab while claim() is returning
    'none'. Skips while a job is running — the job's own step heartbeats
    (which carry job_id/account_id) would otherwise be raced/overwritten."""
    while True:
        if not manager.busy:
            api.heartbeat(status="online", current_step="idle")
        await asyncio.sleep(interval_sec)


async def _main() -> None:
    config = Config()
    config.validate()
    log.info(
        "Buyer Network Runner starting (id=%s, api=%s, dry_run=%s)",
        config.runner_id, config.api_url, config.dry_run,
    )
    api = ApiClient(config)
    manager = JobManager(config, api)

    await asyncio.gather(
        manager.run_forever(),
        _idle_heartbeat_loop(api, manager, config.heartbeat_interval_sec),
    )


def main() -> None:
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        log.info("runner stopped")


if __name__ == "__main__":
    main()
