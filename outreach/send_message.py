"""
SEND_MESSAGE job handler.

FGOS already decided WHAT to send and to WHOM — this handler only executes
the legacy two-step, same-session flow: STEP 1 open the gig, click Contact
Seller, send the first message. STEP 2, same session, open the seller's
inbox thread and send a second message with an optional attachment. This is
NOT a delayed follow-up — both steps run back to back inside one job. No
cadence decisions (wait X days / drip) happen here or anywhere else in this
repo.

Fiverr-specific selectors are intentionally isolated to this module (not the
BrowserAdapter) — a future platform gets its own outreach/<platform>_send.py
using the same generic BrowserAdapter methods.
"""

from __future__ import annotations

import base64
import os
import tempfile
from typing import Any

from browser.adapter import BrowserAdapter
from reporter import Reporter

CONTACT_BUTTON_SELECTOR = 'div[data-testid="contact-seller-button"]'
MESSAGE_BOX_SELECTOR = 'textarea[data-testid="message-box"]'
SEND_BUTTON_SELECTOR = "button[role='button']:has-text('Send message')"
ATTACHMENT_INPUT_SELECTOR = "input[name='attachments']"
# Fiverr's inbox thread view uses the same message-composer widget as the gig
# "Contact Seller" modal (same data-testids) — reused rather than guessed.
INBOX_MESSAGE_BOX_SELECTOR = MESSAGE_BOX_SELECTOR
INBOX_SEND_BUTTON_SELECTOR = SEND_BUTTON_SELECTOR
INBOX_ATTACHMENT_INPUT_SELECTOR = ATTACHMENT_INPUT_SELECTOR
LOGIN_URL = "https://www.fiverr.com/login"
LOGIN_EMAIL_SELECTOR = "input[name='usernameOrEmail']"
LOGIN_PASSWORD_SELECTOR = "input[name='password']"
LOGIN_SUBMIT_SELECTOR = "button[type='submit']"


async def _login_if_needed(browser: BrowserAdapter, job: dict[str, Any], reporter: Reporter) -> bool:
    """Log into the assigned buyer account using credentials fetched by
    JobManager (job['_account_credentials']) — never the claim payload."""
    creds = job.get("_account_credentials")
    if not creds or not creds.get("password"):
        reporter.fail("No account credentials available for SEND_MESSAGE login")
        return False
    if not reporter.step(f"Logging in as {creds.get('username')}"):
        reporter.blocked("Aborted by FGOS (campaign paused) before login")
        return False
    await browser.open(LOGIN_URL)
    await browser.type(LOGIN_EMAIL_SELECTOR, creds["username"], humanize=False)
    await browser.type(LOGIN_PASSWORD_SELECTOR, creds["password"], humanize=False)
    await browser.click(LOGIN_SUBMIT_SELECTOR)
    return True


async def _send_inbox_attachment(browser: BrowserAdapter, reporter: Reporter, attachment_id: str) -> None:
    """Fetch attachment bytes on demand (base64-over-JSON, same pattern as
    credential lookups) and upload via a local temp file — browser.upload()
    takes a file path, not bytes. Failure here is logged and swallowed by the
    caller's try/except so it surfaces as NEEDS_REVIEW, not a lost step-1 send."""
    fetched = reporter.api.get_attachment(attachment_id)
    if not fetched:
        reporter.step(f"Attachment {attachment_id} fetch failed (continuing without it)")
        return
    raw = base64.b64decode(fetched["data_base64"])
    suffix = os.path.splitext(fetched.get("file_name") or "")[1]
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(raw)
        tmp.close()
        await browser.upload(INBOX_ATTACHMENT_INPUT_SELECTOR, tmp.name)
    finally:
        os.unlink(tmp.name)


async def run(browser: BrowserAdapter, job: dict[str, Any], reporter: Reporter) -> None:
    target = job.get("target") or {}
    seller_username = target.get("seller_username")
    gig_url = target.get("gig_url")
    message = job.get("message")
    inbox_message = job.get("inbox_message")
    attachments = job.get("attachments") or []

    if not gig_url or not message:
        reporter.fail("SEND_MESSAGE job missing target.gig_url or message")
        return

    if not await _login_if_needed(browser, job, reporter):
        return

    # ── STEP 1: gig → Contact Seller → send first message ──────────────────
    if not reporter.step(f"Opening gig {seller_username or ''}"):
        reporter.blocked("Aborted by FGOS (campaign paused) before opening gig")
        return
    await browser.open(gig_url)

    if not reporter.step("Opening contact composer"):
        reporter.blocked("Aborted by FGOS (campaign paused) before contacting seller")
        return
    await browser.click(CONTACT_BUTTON_SELECTOR)

    if not reporter.step("Typing message"):
        reporter.blocked("Aborted by FGOS (campaign paused) mid-compose")
        return
    await browser.type(MESSAGE_BOX_SELECTOR, message, humanize=True)

    if not reporter.step("Sending message (step 1)"):
        reporter.blocked("Aborted by FGOS (campaign paused) before send")
        return
    await browser.click(SEND_BUTTON_SELECTOR)

    if not inbox_message:
        # No step-2 template configured for this campaign — one-step send is complete.
        reporter.step("Completed")
        reporter.complete(metadata={"seller_username": seller_username, "gig_url": gig_url, "step2": False})
        return

    # ── STEP 2: same session, seller inbox → send second message + optional
    #    attachment. From here on, step 1 has already been sent — any failure
    #    (including an FGOS abort) is reported as NEEDS_REVIEW, never FAILED
    #    or a plain abort, so a naive retry doesn't re-fire step 1 into the
    #    (campaign_id, seller_username) unique constraint. ────────────────────
    if not seller_username:
        reporter.needs_review("Step 1 sent, but no seller_username to open inbox for step 2")
        return

    try:
        if not reporter.step("Opening inbox thread"):
            reporter.needs_review("Step 1 sent; aborted by FGOS before step 2 (inbox)")
            return
        await browser.open(f"https://www.fiverr.com/inbox/{seller_username}")

        if not reporter.step("Typing inbox message"):
            reporter.needs_review("Step 1 sent; aborted by FGOS mid step-2 compose")
            return
        await browser.type(INBOX_MESSAGE_BOX_SELECTOR, inbox_message, humanize=True)

        for attachment_id in attachments:
            try:
                await _send_inbox_attachment(browser, reporter, attachment_id)
            except Exception as e:  # noqa: BLE001 - attachment failure shouldn't kill the step-2 send
                reporter.step(f"Attachment failed (continuing): {e}")

        if not reporter.step("Sending inbox message (step 2)"):
            reporter.needs_review("Step 1 sent; aborted by FGOS before step-2 send")
            return
        await browser.click(INBOX_SEND_BUTTON_SELECTOR)
    except Exception as e:  # noqa: BLE001 - step 1 already sent, never downgrade to FAILED
        reporter.needs_review(f"Step 1 sent, step 2 failed: {e}", metadata={"seller_username": seller_username, "gig_url": gig_url})
        return

    reporter.step("Completed")
    reporter.complete(metadata={"seller_username": seller_username, "gig_url": gig_url, "step2": True})
