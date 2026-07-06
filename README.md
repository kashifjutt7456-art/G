# Buyer Network Runner

Hands, not brain. FGOS (`backend/src/modules/buyer_network/`) decides
everything — campaigns, targets, messages, cadence, accounts, browser/VPN
choice, retries. This process only: registers implicitly via heartbeat,
claims one job at a time, executes it with the adapters FGOS told it to use,
and reports the result. It never reads a CSV, never picks a target, never
decides when to send a follow-up.

Reference material only (not ported directly): `FIverr Research/VVRO PROMOTE
copy 2 (1).py`. Camoufox + BrowserForge + playwright-stealth launch code and
human-typing helpers were extracted into `browser/camoufox_adapter.py`; the
plaintext-CSV storage, hardcoded paths, global mutable password, and
whole-pipeline-restart-on-any-exception pattern were explicitly left behind.

## Architecture

```
main.py            entry point — claim loop + idle heartbeat
job_manager.py      claims a job, resolves adapters, dispatches by job_type
api_client.py       HTTP client for claim / heartbeat / result / credentials
accounts.py         fetches real credentials on demand (never in the claim payload)
reporter.py         step -> heartbeat; collects screenshots/log_refs; terminal report
browser/
  adapter.py         BrowserAdapter interface (start/open/click/type/upload/screenshot/close)
  camoufox_adapter.py  concrete impl (from VVRO's reusable parts)
  factory.py         picks the adapter FGOS specified via browser_profile.browser_type
vpn/
  adapter.py         VPNAdapter interface (connect/disconnect/rotate/status)
  pia_adapter.py      OpenVPN-config-based (same pattern as the scraper fleet's workflow)
  nord_adapter.py     stub — NotImplementedError until Nord is actually needed
  no_vpn_adapter.py   no-op
  factory.py         picks the adapter FGOS specified via network_profile.provider
outreach/
  send_message.py    SEND_MESSAGE job — login, open gig, send exact text FGOS provided
account_creation/
  create_buyer_account.py  CREATE_BUYER_ACCOUNT job — Outlook -> Fiverr signup -> report.
                            Self-contained outreach identity creation — NOT the generic
                            FGOS Provisioning module. Never linked to the Buyers page,
                            buyer_profiles, IX Browser, RDP, or ranking/order automation.
  identity.py         in-memory-only synthetic identity generation
```

## Run locally

```bash
cd buyer_network_runner
pip install -r requirements.txt
python -m camoufox fetch   # one-time browser binary fetch, per Camoufox docs

set BUYER_NETWORK_API_KEY=<the dedicated key — NOT the scraper key>
set FGOS_API_URL=https://api.fgos.site/api/v1/ingestion/buyer-network
set RUNNER_ID=bn-runner-local-1

python main.py
```

(On Linux/macOS use `export` instead of `set`.)

## Protocol

Reuses the existing FGOS Buyer Network runner protocol exactly
(`backend/src/modules/buyer_network/buyer-network-bot.controller.ts`):

| Endpoint | Purpose |
|---|---|
| `POST /claim` | atomically claim the next WAITING job from an active campaign |
| `POST /heartbeat` | report liveness/step; response may set `kill: true` (abort now) |
| `POST /result` | terminal outcome: `COMPLETED \| FAILED \| BLOCKED \| NEEDS_REVIEW` |
| `POST /credentials/account` | fetch a buyer account's real password (audited) |
| `POST /credentials/network` | fetch a VPN profile's real password (audited) |

`job.job_type` dispatches to a handler in `job_manager.py`:
`SEND_MESSAGE` -> `outreach/send_message.py`, `CREATE_BUYER_ACCOUNT` ->
`account_creation/create_buyer_account.py`. `CHECK_MESSAGES`/`FOLLOW_UP` are
reserved for a later phase — adding one is "write a handler module + one line
in `job_manager._HANDLERS`", not a protocol change.

## Safety

- Every job's outcome is reported to FGOS — no silent runs.
- Credentials are fetched, used, and discarded per job; never written to disk.
- `BUYER_NETWORK_EXECUTION_ENABLED=false` (backend default) means `claim()`
  always returns nothing — flip it only when ready to go live.
- A campaign set to `paused`/`cancelled` causes the next heartbeat to return
  `kill: true`; every handler checks this before each side-effecting step.
