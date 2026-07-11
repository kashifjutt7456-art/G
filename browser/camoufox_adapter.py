"""
CamoufoxAdapter — first BrowserAdapter implementation.

Extracted and cleaned from the VVRO reference script (FIverr Research/VVRO
PROMOTE copy 2 (1).py): Camoufox launch, BrowserForge fingerprint generation,
playwright-stealth, the navigator/canvas init-script, and human-like typing.
Everything decision-related (which gig, what message, CSV state, VPN control)
was deliberately left behind — this class only drives a browser.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, Optional

from browser.adapter import BrowserAdapter
from logger import get_logger

log = get_logger(__name__)

try:
    from camoufox import AsyncCamoufox
except ImportError:  # pragma: no cover - surfaced clearly at runtime instead
    AsyncCamoufox = None  # type: ignore[assignment,misc]

try:
    from browserforge.fingerprints import FingerprintGenerator, Screen
except ImportError:  # pragma: no cover - surfaced clearly at runtime instead
    FingerprintGenerator = None  # type: ignore[assignment,misc]
    Screen = None  # type: ignore[assignment,misc]


# NOTE: No navigator init_script overrides here.
# Camoufox already patches webdriver/automation flags natively at the C++ level.
# Object.defineProperty overrides on navigator are themselves a PerimeterX bot
# signal — they leave tampered property descriptors that PerimeterX probes for
# via Object.getOwnPropertyDescriptor(navigator, 'webdriver').


class CamoufoxAdapter(BrowserAdapter):
    def __init__(self) -> None:
        self._camoufox_cm: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._pages: dict[str, Any] = {}
        self._active: Optional[str] = None
        self._tab_seq: int = 0

    @property
    def _page(self) -> Any:
        """The active tab's Page — every existing open/click/type/upload/
        screenshot/current_url/page_title method body is unchanged and just
        keeps reading this property, so single-tab callers see no behavior
        change from the tab registry below."""
        return self._pages.get(self._active) if self._active else None

    def _register_tab(self, page: Any) -> str:
        handle = f"tab-{self._tab_seq}"
        self._tab_seq += 1
        self._pages[handle] = page
        self._active = handle
        return handle

    async def start(self, fingerprint_config: dict[str, Any], proxy: Optional[dict[str, Any]] = None) -> None:
        if AsyncCamoufox is None:
            raise RuntimeError("camoufox is not installed — `pip install camoufox[geoip]`")

        headless = bool(fingerprint_config.get("headless", False))
        window = tuple(fingerprint_config.get("window", (1280, 800)))
        humanize = bool(fingerprint_config.get("humanize", True))
        block_webrtc = bool(fingerprint_config.get("block_webrtc", True))
        os_name = fingerprint_config.get("os", "windows")

        fp_headers: dict[str, str] = {}
        locale: str | None = None
        fonts: Optional[list[str]] = None
        if FingerprintGenerator is not None and Screen is not None:
            try:
                bf_screen = Screen(min_width=window[0], max_width=window[0], min_height=window[1], max_height=window[1])
                # Camoufox is Firefox-based — must generate Firefox fingerprints.
                # Chrome fingerprints on a Firefox engine = instant UA/header mismatch
                # that PerimeterX catches. Do NOT use browser="chrome" here.
                fg = FingerprintGenerator(browser="firefox")
                fp = fg.generate(os=os_name, screen=bf_screen)
                locale = getattr(fp, "locale", None)
                fp_fonts = getattr(fp, "fonts", None)
                if isinstance(fp_fonts, list) and fp_fonts:
                    fonts = random.sample(fp_fonts, k=min(len(fp_fonts), random.randint(3, 6)))
            except Exception as e:  # noqa: BLE001 - fingerprinting is best-effort
                log.warning("Fingerprint generation failed, continuing without it: %s", e)

        camoufox_kwargs: dict[str, Any] = {
            "os": os_name,
            "humanize": humanize,
            "block_webrtc": block_webrtc,
            "headless": headless,
            "window": window,
            "geoip": True,  # Automatically matches timezone, locale, and coordinates to the VPN IP
            "firefox_user_prefs": {
                # Disable WebGL entirely. GitHub Actions uses "Mesa/llvmpipe" software rendering,
                # which is the #1 dead giveaway for a datacenter/VM to PerimeterX.
                # Disabled WebGL just looks like a privacy-hardened browser (like Tor).
                "webgl.disabled": True
            }
        }
        if fonts:
            camoufox_kwargs["fonts"] = fonts
        if proxy:
            camoufox_kwargs["proxy"] = {
                "server": f"{proxy.get('scheme', 'http')}://{proxy['host']}:{proxy['port']}",
                "username": proxy.get("username"),
                "password": proxy.get("password"),
            }

        self._camoufox_cm = AsyncCamoufox(**camoufox_kwargs)
        # AsyncCamoufox.__aenter__() returns a PlaywrightBrowserContext directly,
        # NOT a bare Browser. Calling .new_context() on it triggers a protocol
        # error (Browser.setDefaultViewport with isMobile not in scheme).
        # The correct pattern is to use the returned object as the context itself.
        self._context = await self._camoufox_cm.__aenter__()

        # NOTE: playwright-stealth is NOT applied here.
        # It is a Chromium-specific library that injects Chrome patches (e.g.
        # chrome.runtime, plugins array) that are meaningless — and broken —
        # on a Firefox engine and actively worsen the fingerprint consistency.
        # Camoufox handles all stealth natively; no JS-level overrides needed.

        page = await self._context.new_page()
        self._register_tab(page)

    async def open(self, url: str, timeout_ms: int = 60000) -> None:
        await self._page.goto(url, timeout=timeout_ms)

    async def click(self, selector: str, timeout_ms: int = 15000, **kwargs: Any) -> None:
        locator = self._page.locator(selector)
        if kwargs.get("force"):
            kwargs.pop("force")
            await locator.click(timeout=timeout_ms, force=True)
            return
            
        await locator.wait_for(state="visible", timeout=timeout_ms)
        await locator.click(timeout=timeout_ms, **kwargs)

    async def type(self, selector: str, text: str, humanize: bool = True, **kwargs: Any) -> None:
        locator = self._page.locator(selector)
        await locator.wait_for(state="visible", timeout=15000)
        if not humanize:
            await locator.fill(text, **kwargs)
            return
        # Human-like typing with occasional backspace-retry, ported from VVRO.
        for char in text:
            await locator.type(char, delay=random.uniform(0.05, 0.18))
            if random.random() < 0.1:
                await locator.press("Backspace")
                await asyncio.sleep(random.uniform(0.2, 0.5))
                await locator.type(char, delay=random.uniform(0.05, 0.18))

    async def upload(self, selector: str, file_path: str) -> None:
        file_input = self._page.locator(selector)
        await file_input.wait_for(state="attached", timeout=10000)
        await file_input.first.set_input_files(file_path)

    async def screenshot(self) -> bytes:
        return await self._page.screenshot(type="png")

    async def current_url(self) -> Optional[str]:
        return self._page.url if self._page else None

    async def page_title(self) -> Optional[str]:
        return await self._page.title() if self._page else None

    # ── Multi-tab support ────────────────────────────────────────────────────
    async def open_tab(self, url: str, timeout_ms: int = 60000) -> str:
        page = await self._context.new_page()
        handle = self._register_tab(page)
        await page.goto(url, timeout=timeout_ms)
        return handle

    async def switch_tab(self, handle: str) -> None:
        if handle not in self._pages:
            raise ValueError(f"Unknown tab handle '{handle}'")
        self._active = handle
        page = self._pages[handle]
        # bring_to_front + settle delay — ported from VVRO's focus_page().
        try:
            await page.bring_to_front()
        except Exception as e:  # noqa: BLE001 - best-effort focus
            log.debug("bring_to_front failed (continuing): %s", e)
        await asyncio.sleep(0.35 + random.random() * 0.25)

    async def close_tab(self, handle: str) -> None:
        page = self._pages.pop(handle, None)
        if page is None:
            return
        try:
            await page.close()
        except Exception as e:  # noqa: BLE001
            log.debug("tab close failed (continuing): %s", e)
        if self._active == handle:
            self._active = next(iter(self._pages), None)

    async def current_tab(self) -> str:
        if self._active is None:
            raise RuntimeError("No active tab — browser not started")
        return self._active

    async def wait_for(self, selector: str, timeout_ms: int = 15000) -> bool:
        try:
            await self._page.locator(selector).wait_for(state="visible", timeout=timeout_ms)
            return True
        except Exception:
            return False

    async def query_links(self, selector: str) -> list[dict[str, str]]:
        locator = self._page.locator(selector)
        count = await locator.count()
        links: list[dict[str, str]] = []
        for i in range(count):
            anchor = locator.nth(i)
            try:
                href = await anchor.get_attribute("href")
            except Exception:  # noqa: BLE001
                href = None
            if not href:
                continue
            try:
                text = (await anchor.text_content()) or ""
            except Exception:  # noqa: BLE001
                text = ""
            links.append({"href": href, "text": text.strip()})
        return links

    async def get_session_state(self) -> dict[str, Any]:
        if self._context is None:
            return {}
        try:
            return await self._context.storage_state()
        except Exception as e:  # noqa: BLE001 - session capture is best-effort
            log.warning("Failed to capture session state (continuing): %s", e)
            return {}

    async def close(self) -> None:
        try:
            if self._context is not None:
                await self._context.close()
        except Exception as e:  # noqa: BLE001
            log.debug("context close failed (continuing): %s", e)
        try:
            if self._camoufox_cm is not None:
                await self._camoufox_cm.__aexit__(None, None, None)
        except Exception as e:  # noqa: BLE001
            log.debug("camoufox teardown failed (continuing): %s", e)
        self._pages = {}
        self._active = None
        self._context = None
        self._camoufox_cm = None
