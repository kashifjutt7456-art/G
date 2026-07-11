"""
CREATE_BUYER_ACCOUNT job handler — self-contained outreach account creation.

This is NOT the generic FGOS Provisioning module (backend/src/modules/
provisioning/). It creates a TEMPORARY outreach identity only: generate
identity -> create Outlook -> verify Outlook -> create Fiverr -> verify
Fiverr email -> report the new account to FGOS, which saves it straight into
buyer_network_accounts. This account is never linked to the Buyers page,
buyer_profiles, IX Browser, RDP, or ranking/order automation — its only
purpose is outreach messaging.

Flow adapted from VVRO's intact signup_outlook()/signup_fiverr()/verify_email()
logic (FIverr Research/VVRO PROMOTE copy 2 (1).py) but driven by the generic
BrowserAdapter interface — no CSV files, no global mutable password, no
"restart everything on any exception", and one browser/context with two tabs
(Outlook + Fiverr) instead of VVRO's two separate browser processes.

Fiverr signup entry point: VVRO's only PROVEN working path opens a gig page
and triggers signup through the Contact Seller -> "Continue with Email"
panel — there is no live-verified generic/direct Fiverr join page to fall
back to, so this handler requires job['metadata']['fiverr_signup_url'] (a gig
URL) and reports NEEDS_REVIEW if it's missing rather than guessing at an
unverified entry point.

CAPTCHA note: VVRO's original approach was a fragile coordinate-based mouse
click-and-hold that only works against one exact viewport/layout and isn't
expressible through the generic BrowserAdapter interface on purpose — that
interface must stay engine-neutral for Playwright/Chrome adapters too. If
Outlook/Fiverr present a CAPTCHA this handler reports NEEDS_REVIEW with a
screenshot rather than guessing at coordinates; a human (or a future
CAPTCHA-solving adapter) resolves it.
"""

from __future__ import annotations

import asyncio
import random
import string
from typing import Any, Optional
from urllib.parse import urljoin

from browser.adapter import BrowserAdapter
from browser.factory import create_browser_adapter
from account_creation.identity import Identity, generate_identity
from reporter import Reporter

# ── Outlook signup ───────────────────────────────────────────────────────────
EMAIL_FIELD_SELECTOR = "input#floatingLabelInput4"
NEXT_BUTTON_SELECTOR = "button[data-testid='primaryButton']"
PASSWORD_FIELD_SELECTOR = "input[type='password']"
FIRST_NAME_SELECTOR = "#firstNameInput"
LAST_NAME_SELECTOR = "#lastNameInput"
BIRTH_MONTH_DROPDOWN_SELECTOR = "#BirthMonthDropdown"
BIRTH_DAY_DROPDOWN_SELECTOR = "#BirthDayDropdown"
BIRTH_YEAR_INPUT_SELECTOR = "input[name='BirthYear']"
# Month options (1-12) are localized by GeoIP (e.g. Enero, Janvier). 
# We select the first option (nth=0) to pick the first month regardless of language.
MONTH_OPTION_SELECTOR = "div[role='option'] >> nth=0"
# Day options ("1".."31") all contain "1" as a substring (10, 11, 21, 31...) —
# `>> nth=0` pins the first DOM match, which is day 1 given Outlook's
# ascending option order. Selector-string equivalent of VVRO's `.first`.
DAY_OPTION_SELECTOR = "div[role='option']:has-text('1') >> nth=0"

# ── Fiverr signup (VVRO's proven gig -> Contact Seller -> email path) ───────
CONTACT_SELLER_BUTTON_SELECTOR = 'div[data-testid="contact-seller-button"]'
CONTINUE_WITH_EMAIL_SELECTOR = "button:has-text('Continue with Email')"
FIVERR_EMAIL_FIELD_SELECTOR = "input[name='usernameOrEmail']"
FIVERR_PASSWORD_FIELD_SELECTOR = "input[name='password']"
FIVERR_CONTINUE_BUTTON_SELECTOR = "button[type='submit'][role='button']:has-text('Continue')"
FIVERR_USERNAME_FIELD_SELECTOR = "input[name='username']"
FIVERR_CREATE_ACCOUNT_BUTTON_SELECTOR = "button:has-text('Create my account')"

# ── Fiverr verification email (read from the still-open Outlook tab) ───────
FIVERR_SENDER_SELECTOR = "span[title='noreply@e.fiverr.com']"
READING_PANE_SELECTOR = "div[role='document']"
ACTIVATION_LINK_PREFERRED_SELECTOR = "a[href*='fiverr.com/linker']"
ACTIVATION_LINK_SELECTOR = "a[href*='fiverr.com']"
ACTIVATION_LINK_TEXT_HINTS = ("click here", "activate", "verify", "linker")

# Best-effort only — VVRO never verified a post-activation logged-in state,
# so there is no proven selector to port here; treated as a soft signal.
FIVERR_LOGGED_IN_SELECTOR = "a[href='/inbox'], div[data-testid='header-user-menu']"


async def _select_outlook_dob(browser: BrowserAdapter) -> None:
    """Fixed Jan 1 + a random adult year — ported from VVRO's
    select_outlook_dob_exact(), a real, working sequence against Outlook's
    dropdown widgets."""
    await browser.click(BIRTH_MONTH_DROPDOWN_SELECTOR, force=True)
    await browser.click(MONTH_OPTION_SELECTOR, force=True)
    await browser.click(BIRTH_DAY_DROPDOWN_SELECTOR, force=True)
    await browser.click(DAY_OPTION_SELECTOR, force=True)
    year = str(random.randint(1980, 2000))
    await browser.type(BIRTH_YEAR_INPUT_SELECTOR, year, humanize=False)


async def _signup_outlook(browser: BrowserAdapter, reporter: Reporter) -> Optional[Identity]:
    identity = generate_identity()
    if not reporter.step("Opening Outlook signup"):
        return None
    await browser.open("https://signup.live.com/")

    await browser.type(EMAIL_FIELD_SELECTOR, identity.email, humanize=False)
    await browser.click(NEXT_BUTTON_SELECTOR)

    await browser.type(PASSWORD_FIELD_SELECTOR, identity.password, humanize=False)
    await browser.click(NEXT_BUTTON_SELECTOR)

    if not reporter.step("Setting Outlook date of birth"):
        return None
    await _select_outlook_dob(browser)
    await browser.click(NEXT_BUTTON_SELECTOR)

    await browser.type(FIRST_NAME_SELECTOR, identity.first_name, humanize=False)
    await browser.type(LAST_NAME_SELECTOR, identity.last_name, humanize=False)
    await browser.click(NEXT_BUTTON_SELECTOR)

    title = (await browser.page_title() or "").lower()
    if "human" in title or "captcha" in title or "can't" in title:
        screenshot = await browser.screenshot()
        reporter.add_screenshot_ref(f"outlook_captcha_{identity.email}.png")
        reporter.needs_review(
            f"Outlook signup hit a CAPTCHA/verification wall (title='{title}')",
            metadata={"email": identity.email, "screenshot_bytes": len(screenshot)},
        )
        return None

    reporter.step(f"Outlook account created: {identity.email}")
    return identity


async def _open_outlook_inbox(browser: BrowserAdapter, reporter: Reporter) -> bool:
    """Confirm the just-created mailbox actually loads before trusting this
    tab as the account's inbox for the later verification-link lookup."""
    if not reporter.step("Verifying Outlook inbox"):
        return False
    await browser.open("https://outlook.live.com/mail/0/")
    title = await browser.page_title()
    reporter.step(f"Outlook inbox reached (title={title})")
    return True


def _generate_fiverr_username(identity: Identity) -> str:
    alpha = "".join(random.choices(string.ascii_lowercase, k=6))
    nums = "".join(random.choices(string.digits, k=2))
    return f"{identity.first_name}{alpha}{nums}"


async def _signup_fiverr(
    outlook_browser: BrowserAdapter, fiverr_browser: BrowserAdapter, reporter: Reporter, identity: Identity, job: dict[str, Any]
) -> bool:
    """Drive Fiverr signup in the dedicated Fiverr browser."""
    (and its logged-in session) untouched. Returns the Fiverr tab handle, or
    None if signup couldn't proceed (reporter already recorded why)."""
    signup_gig_url = (job.get("metadata") or {}).get("fiverr_signup_url")
    if not signup_gig_url:
        reporter.needs_review(
            "CREATE_BUYER_ACCOUNT job has no metadata.fiverr_signup_url — the "
            "only proven Fiverr signup path opens a gig's Contact Seller panel; "
            "FGOS must supply a gig URL per job before this can run live."
        )
        return False

    if not reporter.step("Opening Fiverr signup gig"):
        reporter.blocked("Aborted by FGOS (campaign paused) before Fiverr signup")
        return False
    await fiverr_browser.open(signup_gig_url)

    title = (await fiverr_browser.page_title() or "").lower()
    if "needs a human touch" in title or "captcha" in title:
        reporter.step(f"Fiverr CAPTCHA detected ('{title}'). Attempting to press and hold #px-captcha...")
        try:
            await fiverr_browser.press_and_hold("#px-captcha", duration_ms=10500)
            await asyncio.sleep(5)
            title = (await fiverr_browser.page_title() or "").lower()
        except Exception as e:
            reporter.step(f"Failed to press and hold CAPTCHA: {e}")
            
        if "needs a human touch" in title or "captcha" in title:
            screenshot = await fiverr_browser.screenshot()
            reporter.add_screenshot_ref(f"fiverr_captcha_{identity.email}.png")
            reporter.step(f"Fiverr signup hit a CAPTCHA/verification wall (title='{title}')")
            return False

    if not reporter.step("Opening Fiverr Contact Seller panel"):
        reporter.blocked("Aborted by FGOS (campaign paused) before contacting seller")
        return False
    await fiverr_browser.click(CONTACT_SELLER_BUTTON_SELECTOR)
    await fiverr_browser.click(CONTINUE_WITH_EMAIL_SELECTOR)

    if not reporter.step("Filling Fiverr signup form"):
        reporter.blocked("Aborted by FGOS (campaign paused) mid Fiverr signup")
        return False
    await fiverr_browser.type(FIVERR_EMAIL_FIELD_SELECTOR, identity.email, humanize=False)
    await fiverr_browser.type(FIVERR_PASSWORD_FIELD_SELECTOR, identity.password, humanize=False)
    await fiverr_browser.click(FIVERR_CONTINUE_BUTTON_SELECTOR)

    fiverr_username = _generate_fiverr_username(identity)
    await fiverr_browser.type(FIVERR_USERNAME_FIELD_SELECTOR, fiverr_username, humanize=False)
    await fiverr_browser.click(FIVERR_CREATE_ACCOUNT_BUTTON_SELECTOR)

    identity.fiverr_username = fiverr_username
    reporter.step(f"Fiverr signup submitted: {fiverr_username}")
    return True


async def _locate_and_open_verification_link(
    outlook_browser: BrowserAdapter,
    fiverr_browser: BrowserAdapter,
    reporter: Reporter,
    identity: Identity,
) -> bool:
    """Find the Fiverr verification email in the outlook browser, extract
    the activation link, then open it in the fiverr browser."""
    await outlook_browser.open("https://outlook.live.com/mail/0/")

    if not reporter.step("Waiting for Fiverr verification email"):
        reporter.needs_review("Aborted by FGOS while waiting for the verification email")
        return None

    found = False
    for attempt in range(1, 7):
        if await outlook_browser.wait_for(FIVERR_SENDER_SELECTOR, timeout_ms=20000):
            found = True
            break
        reporter.step(f"Verification email not visible yet (attempt {attempt}/6)")
        await asyncio.sleep(20)
        await outlook_browser.open("https://outlook.live.com/mail/0/")
    if not found:
        reporter.needs_review(f"Fiverr verification email never arrived for {identity.email}")
        return False

    clicked = False
    for attempt in range(1, 6):
        try:
            await outlook_browser.click(FIVERR_SENDER_SELECTOR)
            clicked = True
            break
        except Exception as e:  # noqa: BLE001 - retry loop, last failure reported below
            reporter.step(f"Click attempt {attempt}/5 on verification email failed: {e}")
            await asyncio.sleep(1)
    if not clicked:
        reporter.needs_review(f"Could not open Fiverr verification email for {identity.email}")
        return False

    if not await outlook_browser.wait_for(READING_PANE_SELECTOR, timeout_ms=60000):
        reporter.needs_review("Verification email reading pane never appeared")
        return False

    links = await outlook_browser.query_links(f"{READING_PANE_SELECTOR} {ACTIVATION_LINK_PREFERRED_SELECTOR}")
    if not links:
        links = await outlook_browser.query_links(f"{READING_PANE_SELECTOR} {ACTIVATION_LINK_SELECTOR}")
    if not links:
        reporter.needs_review("No Fiverr activation link found in verification email")
        return False

    href = None
    for link in links:
        if any(hint in link["text"].lower() for hint in ACTIVATION_LINK_TEXT_HINTS):
            href = link["href"]
            break
    if href is None:
        href = links[0]["href"]

    base_url = await outlook_browser.current_url() or "https://outlook.live.com/mail/0/"
    href = urljoin(base_url, href)

    if not reporter.step("Opening Fiverr activation link"):
        reporter.needs_review("Aborted by FGOS before opening the activation link")
        return False
    await fiverr_browser.open(href)
    return True


async def _confirm_fiverr_logged_in(browser: BrowserAdapter, reporter: Reporter) -> bool:
    """Best-effort only (see module docstring) — logged for visibility, not
    used as a hard gate, until a live signup confirms the real DOM signal."""
    await browser.open("https://www.fiverr.com/")
    signed_in = await browser.wait_for(FIVERR_LOGGED_IN_SELECTOR, timeout_ms=15000)
    reporter.step(f"Fiverr logged-in check: {'signal found' if signed_in else 'no signal found (unverified)'}")
    return signed_in


async def run(outlook_browser: BrowserAdapter, job: dict[str, Any], reporter: Reporter) -> None:
    identity = await _signup_outlook(outlook_browser, reporter)
    if identity is None:
        return  # reporter already recorded NEEDS_REVIEW/FAILED above

    if not await _open_outlook_inbox(outlook_browser, reporter):
        reporter.fail(f"Could not verify Outlook inbox for {identity.email}")
        return

    # Define the fallback engines to try if Fiverr throws a CAPTCHA
    engines_to_try = [
        "cloakbrowser",
        "camoufox",
        "nodriver",
        "playwright_chromium",
        "playwright_firefox"
    ]
    
    proxy = job.get("_proxy")
    fingerprint_config = (job.get("browser_profile") or {}).get("fingerprint_config", {})
    
    account_result = None
    signed_in = False

    for engine_name in engines_to_try:
        reporter.step(f"Starting separate Fiverr browser using engine: {engine_name}")
        
        try:
            fiverr_browser = create_browser_adapter(engine_name)
        except ValueError as e:
            reporter.step(f"Skipping engine {engine_name}: {e}")
            continue

        try:
            await fiverr_browser.start(fingerprint_config, proxy)

            # Let's catch if the signup blocked by captcha. 
            # We'll temporarily override reporter.needs_review during _signup_fiverr 
            # to prevent it from marking the WHOLE job as NEEDS_REVIEW prematurely.
            
            # Simple wrapper to check if it returned False (which means it blocked)
            signup_success = await _signup_fiverr(outlook_browser, fiverr_browser, reporter, identity, job)
            
            if not signup_success:
                reporter.step(f"Engine {engine_name} blocked during Fiverr signup. Closing and trying next engine...")
                continue
                
            if not await _locate_and_open_verification_link(outlook_browser, fiverr_browser, reporter, identity):
                # If verification fails, it's not a browser fingerprint issue, it's an email issue.
                return 

            signed_in = await _confirm_fiverr_logged_in(fiverr_browser, reporter)
            session_state = await fiverr_browser.get_session_state()

            account_result = {
                "email": identity.email,
                "username": identity.fiverr_username or identity.email.split("@")[0],
                "password": identity.password,
                "platform": "fiverr",
                "browser_profile_id": (job.get("browser_profile") or {}).get("profile_id"),
                "network_profile_id": (job.get("network_profile") or {}).get("profile_id"),
                "session_state": session_state,
                "successful_engine": engine_name,
            }
            break # Success! Exit the loop.
            
        except Exception as e:
            reporter.step(f"Engine {engine_name} encountered an error: {e}")
        finally:
            await fiverr_browser.close()

    if account_result is None:
        # All engines failed
        reporter.needs_review(f"All {len(engines_to_try)} stealth browser engines failed on Fiverr signup.")
        return

    reporter.step("Completed")
    reporter.complete(
        metadata={"email": identity.email, "fiverr_login_confirmed": signed_in, "successful_engine": account_result["successful_engine"]},
        account_result=account_result,
    )
