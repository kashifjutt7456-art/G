"""
CloakBrowserAdapter — implements BrowserAdapter using CloakBrowser.
CloakBrowser patches Chromium at the C++ level to bypass bot detection.
Since it returns a standard Playwright Browser, we reuse Playwright automation APIs.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, Optional

from browser.adapter import BrowserAdapter
from logger import get_logger

log = get_logger(__name__)

try:
    from cloakbrowser import launch_async
except ImportError:
    launch_async = None


class CloakBrowserAdapter(BrowserAdapter):
    def __init__(self) -> None:
        self._browser: Any = None
        self._context: Any = None
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
        if launch_async is None:
            raise RuntimeError("cloakbrowser is not installed — `pip install cloakbrowser[geoip]`")

        headless = bool(fingerprint_config.get("headless", False))
        humanize = bool(fingerprint_config.get("humanize", True))

        launch_kwargs: dict[str, Any] = {
            "headless": headless,
            "humanize": humanize,
            "geoip": True,  # Auto-detects timezone and locale from proxy IP
        }

        if proxy:
            # CloakBrowser supports standard proxy dict structure
            launch_kwargs["proxy"] = {
                "server": f"{proxy.get('scheme', 'http')}://{proxy['host']}:{proxy['port']}",
                "username": proxy.get("username"),
                "password": proxy.get("password"),
            }

        log.info(f"Launching CloakBrowser (headless={headless}, humanize={humanize})")
        self._browser = await launch_async(**launch_kwargs)

        window = tuple(fingerprint_config.get("window", (1280, 800)))
        context_args = {
            "viewport": {"width": 1280, "height": 800}
        }
        self._context = await self._browser.new_context(**context_args)
        
        page = await self._context.new_page()
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

    async def press_and_hold_at(self, x: int, y: int, duration_ms: int = 15000) -> None:
        log.info(f"[CloakBrowser] Pressing and holding at ({x}, {y}) for {duration_ms}ms")
        await self._page.mouse.move(x, y)
        await self._page.mouse.down()
        await asyncio.sleep(duration_ms / 1000.0)
        await self._page.mouse.up()
        await self._page.mouse.move(x + random.uniform(10, 50), y + random.uniform(10, 50))

    async def press_and_hold(self, selector: str, duration_ms: int = 10000) -> None:
        locator = self._page.locator(selector)
        await locator.wait_for(state="visible", timeout=15000)
        
        box = await locator.bounding_box()
        if not box:
            raise ValueError(f"Could not calculate bounding box for '{selector}'")
            
        x = box["x"] + box["width"] / 2
        y = box["y"] + box["height"] / 2
        
        await self._page.mouse.move(x + random.uniform(-2, 2), y + random.uniform(-2, 2))
        
        log.info(f"[CloakBrowser] Pressing and holding '{selector}' for {duration_ms}ms")
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
            
        self._pages = {}
        self._active = None
        self._context = None
        self._browser = None
