"""
PlaywrightAdapter — implements BrowserAdapter using Playwright.
Supports multiple engines (chromium, firefox, webkit) and applies playwright-stealth
to evade bot detection.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, Optional

from browser.adapter import BrowserAdapter
from logger import get_logger

try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None

try:
    from playwright_stealth import stealth_async
except ImportError:
    stealth_async = None

try:
    from browserforge.fingerprints import FingerprintGenerator, Screen
except ImportError:
    FingerprintGenerator = None
    Screen = None

log = get_logger(__name__)

class PlaywrightAdapter(BrowserAdapter):
    def __init__(self, browser_type: str = "chromium") -> None:
        """browser_type can be 'chromium', 'firefox', or 'webkit'"""
        self._engine_type = browser_type
        self._playwright = None
        self._browser = None
        self._context = None
        self._pages: dict[str, Any] = {}
        self._active: Optional[str] = None
        self._tab_seq: int = 0

    @property
    def _page(self) -> Any:
        return self._pages.get(self._active) if self._active else None

    def _register_tab(self, page: Any) -> str:
        handle = f"tab-{self._tab_seq}"
        self._tab_seq += 1
        self._pages[handle] = page
        self._active = handle
        return handle

    async def start(self, fingerprint_config: dict[str, Any], proxy: Optional[dict[str, Any]] = None) -> None:
        if async_playwright is None:
            raise RuntimeError("playwright is not installed — `pip install playwright`")

        self._playwright = await async_playwright().start()
        
        # Select the engine
        if self._engine_type == "firefox":
            engine = self._playwright.firefox
        elif self._engine_type == "webkit":
            engine = self._playwright.webkit
        else:
            engine = self._playwright.chromium

        headless = bool(fingerprint_config.get("headless", False))
        
        launch_args = {
            "headless": headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars"
            ] if self._engine_type == "chromium" else []
        }

        if proxy:
            launch_args["proxy"] = {
                "server": f"{proxy.get('scheme', 'http')}://{proxy['host']}:{proxy['port']}",
                "username": proxy.get("username"),
                "password": proxy.get("password"),
            }

        self._browser = await engine.launch(**launch_args)

        # Generate fingerprint using BrowserForge if possible
        window = tuple(fingerprint_config.get("window", (1280, 800)))
        os_name = fingerprint_config.get("os", "windows")
        locale = None
        user_agent = None

        if FingerprintGenerator is not None and Screen is not None:
            try:
                bf_screen = Screen(min_width=window[0], max_width=window[0], min_height=window[1], max_height=window[1])
                # Try to map engine to browserforge browser string
                bf_browser = "chrome" if self._engine_type == "chromium" else "firefox" if self._engine_type == "firefox" else "safari"
                fg = FingerprintGenerator(browser=bf_browser)
                fp = fg.generate(os=os_name, screen=bf_screen)
                locale = getattr(fp, "locale", None)
                user_agent = getattr(fp, "navigator", {}).get("userAgent")
            except Exception as e:
                log.warning("Fingerprint generation failed: %s", e)

        context_args = {
            "viewport": {"width": window[0], "height": window[1]}
        }
        if locale:
            context_args["locale"] = locale
        if user_agent:
            context_args["user_agent"] = user_agent

        self._context = await self._browser.new_context(**context_args)
        
        page = await self._context.new_page()
        
        # Apply playwright-stealth to the page to hide webdriver signatures
        if stealth_async is not None:
            try:
                await stealth_async(page)
            except Exception as e:
                log.warning("Failed to apply stealth: %s", e)
                
        self._register_tab(page)

    async def open(self, url: str, timeout_ms: int = 60000) -> None:
        await self._page.goto(url, timeout=timeout_ms)

    async def click(self, selector: str, timeout_ms: int = 15000, **kwargs: Any) -> None:
        locator = self._page.locator(selector)
        if kwargs.get("force"):
            kwargs.pop("force")
            await locator.first.evaluate("node => node.click()")
            return
            
        await locator.wait_for(state="visible", timeout=timeout_ms)
        await locator.click(timeout=timeout_ms, **kwargs)

    async def type(self, selector: str, text: str, humanize: bool = True, **kwargs: Any) -> None:
        locator = self._page.locator(selector)
        await locator.wait_for(state="visible", timeout=15000)
        if not humanize:
            await locator.fill(text, **kwargs)
            return
        
        for char in text:
            await locator.type(char, delay=random.uniform(0.05, 0.18))
            if random.random() < 0.1:
                await locator.press("Backspace")
                await asyncio.sleep(random.uniform(0.2, 0.5))
                await locator.type(char, delay=random.uniform(0.05, 0.18))

    async def press_and_hold(self, selector: str, duration_ms: int = 10000) -> None:
        locator = self._page.locator(selector)
        await locator.wait_for(state="visible", timeout=15000)
        
        box = await locator.bounding_box()
        if not box:
            raise ValueError(f"Could not calculate bounding box for '{selector}'")
            
        x = box["x"] + box["width"] / 2
        y = box["y"] + box["height"] / 2
        
        await self._page.mouse.move(x + random.uniform(-2, 2), y + random.uniform(-2, 2))
        
        log.info(f"[{self._engine_type}] Pressing and holding '{selector}' for {duration_ms}ms")
        await self._page.mouse.down()
        await asyncio.sleep(duration_ms / 1000.0)
        await self._page.mouse.up()
        
        await self._page.mouse.move(x + random.uniform(10, 50), y + random.uniform(10, 50))

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

    async def open_tab(self, url: str, timeout_ms: int = 60000) -> str:
        page = await self._context.new_page()
        if stealth_async is not None:
            try:
                await stealth_async(page)
            except Exception as e:
                log.warning("Failed to apply stealth on new tab: %s", e)
        handle = self._register_tab(page)
        await page.goto(url, timeout=timeout_ms)
        return handle

    async def switch_tab(self, handle: str) -> None:
        if handle not in self._pages:
            raise ValueError(f"Unknown tab handle '{handle}'")
        self._active = handle
        page = self._pages[handle]
        try:
            await page.bring_to_front()
        except Exception as e:
            log.debug("bring_to_front failed (continuing): %s", e)
        await asyncio.sleep(0.35 + random.random() * 0.25)

    async def close_tab(self, handle: str) -> None:
        page = self._pages.pop(handle, None)
        if page is None:
            return
        try:
            await page.close()
        except Exception as e:
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
            except Exception:
                href = None
            if not href:
                continue
            try:
                text = (await anchor.text_content()) or ""
            except Exception:
                text = ""
            links.append({"href": href, "text": text.strip()})
        return links

    async def get_session_state(self) -> dict[str, Any]:
        if self._context is None:
            return {}
        try:
            return await self._context.storage_state()
        except Exception as e:
            log.warning("Failed to capture session state (continuing): %s", e)
            return {}

    async def close(self) -> None:
        try:
            if self._context is not None:
                await self._context.close()
        except Exception as e:
            log.debug("context close failed: %s", e)
            
        try:
            if self._browser is not None:
                await self._browser.close()
        except Exception as e:
            log.debug("browser close failed: %s", e)
            
        try:
            if self._playwright is not None:
                await self._playwright.stop()
        except Exception as e:
            log.debug("playwright stop failed: %s", e)
            
        self._pages = {}
        self._active = None
        self._context = None
        self._browser = None
        self._playwright = None
