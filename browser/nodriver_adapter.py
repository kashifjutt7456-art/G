"""
NodriverAdapter — implements BrowserAdapter using nodriver.
nodriver communicates directly via Chrome DevTools Protocol (CDP) to avoid WebDriver signatures.
"""

from __future__ import annotations

import asyncio
import base64
import os
import random
from typing import Any, Optional
from urllib.parse import urlparse

from browser.adapter import BrowserAdapter
from logger import get_logger

log = get_logger(__name__)

try:
    import nodriver as uc
    from nodriver.cdp import input_ as cdp_input
    from nodriver.cdp import dom as cdp_dom
    from nodriver.cdp import page as cdp_page
except ImportError:
    uc = None
    cdp_input = None
    cdp_dom = None
    cdp_page = None


class NodriverAdapter(BrowserAdapter):
    def __init__(self) -> None:
        self._browser: Any = None
        self._pages: dict[str, Any] = {}
        self._active: Optional[str] = None
        self._tab_seq: int = 0

    @property
    def _page(self) -> Any:
        """The active tab (nodriver Tab object)"""
        return self._pages.get(self._active) if self._active else None

    def _register_tab(self, page: Any) -> str:
        handle = f"tab-{self._tab_seq}"
        self._tab_seq += 1
        self._pages[handle] = page
        self._active = handle
        return handle

    async def start(self, fingerprint_config: dict[str, Any], proxy: Optional[dict[str, Any]] = None) -> None:
        if uc is None:
            raise RuntimeError("nodriver is not installed — `pip install nodriver`")

        headless = bool(fingerprint_config.get("headless", False))
        window = tuple(fingerprint_config.get("window", (1280, 800)))

        # Build chrome args
        browser_args = [
            f"--window-size={window[0]},{window[1]}"
        ]

        if proxy:
            # Check if there is credentials
            proxy_url = f"{proxy.get('scheme', 'http')}://{proxy['host']}:{proxy['port']}"
            if proxy.get("username") and proxy.get("password"):
                # Note: chromium proxy auth via args is sometimes tricky, but we provide it standard
                proxy_url = f"{proxy.get('username')}:{proxy.get('password')}@{proxy['host']}:{proxy['port']}"
            browser_args.append(f"--proxy-server={proxy_url}")

        log.info(f"Launching nodriver (headless={headless}) with args: {browser_args}")
        
        # uc.start returns a Browser instance
        self._browser = await uc.start(
            headless=headless,
            browser_args=browser_args
        )

        # Retrieve the initial main tab
        # Wait a tiny moment for tabs list to populate
        await asyncio.sleep(0.5)
        tabs = self._browser.tabs
        if tabs:
            page = tabs[0]
        else:
            page = await self._browser.get()  # Opens a tab

        self._register_tab(page)

    async def open(self, url: str, timeout_ms: int = 60000) -> None:
        # In nodriver, page.get(url) navigates and waits for page load
        # We wrap this in a timeout helper if needed, but nodriver get() is already blocking
        await self._page.get(url)

    async def click(self, selector: str, timeout_ms: int = 15000) -> None:
        # Find element by CSS selector
        el = await self._page.select(selector)
        if not el:
            raise ValueError(f"Element not found: '{selector}'")
        await el.click()

    async def type(self, selector: str, text: str, humanize: bool = True) -> None:
        el = await self._page.select(selector)
        if not el:
            raise ValueError(f"Element not found: '{selector}'")

        if not humanize:
            await el.send_keys(text)
            return

        # Simulate human typing
        for char in text:
            await el.send_keys(char)
            await asyncio.sleep(random.uniform(0.05, 0.18))
            # Simulate occasional typo and backspace
            if random.random() < 0.08:
                # Send Backspace key event
                await self._page.send(cdp_input.dispatch_key_event(type_="rawKeyDown", windows_virtual_key_code=8))
                await self._page.send(cdp_input.dispatch_key_event(type_="keyUp", windows_virtual_key_code=8))
                await asyncio.sleep(random.uniform(0.2, 0.5))
                # Retype correct character
                await el.send_keys(char)

    async def press_and_hold(self, selector: str, duration_ms: int = 10000) -> None:
        el = await self._page.select(selector)
        if not el:
            raise ValueError(f"Element not found: '{selector}'")

        # Get layout coordinates via CDP
        box_model = await el.get_box_model()
        if not box_model or not getattr(box_model, "content", None):
            raise ValueError(f"Could not calculate bounding box for '{selector}'")

        content = box_model.content
        # content is [x1, y1, x2, y2, x3, y3, x4, y4]
        x = (content[0] + content[4]) / 2
        y = (content[1] + content[5]) / 2

        log.info(f"[Nodriver] Pressing and holding '{selector}' at ({x}, {y}) for {duration_ms}ms")
        
        # Dispatch Mouse Down
        await self._page.send(cdp_input.dispatch_mouse_event(
            type_=cdp_input.MouseEventType.mouse_pressed,
            x=x,
            y=y,
            button=cdp_input.MouseButton.left,
            click_count=1
        ))

        await asyncio.sleep(duration_ms / 1000.0)

        # Dispatch Mouse Up
        await self._page.send(cdp_input.dispatch_mouse_event(
            type_=cdp_input.MouseEventType.mouse_released,
            x=x,
            y=y,
            button=cdp_input.MouseButton.left,
            click_count=1
        ))

    async def upload(self, selector: str, file_path: str) -> None:
        el = await self._page.select(selector)
        if not el:
            raise ValueError(f"Element not found: '{selector}'")

        abs_path = os.path.abspath(file_path)
        log.info(f"[Nodriver] Uploading file '{abs_path}' to element '{selector}'")
        
        await self._page.send(
            cdp_dom.set_file_input_files(
                files=[abs_path],
                node_id=el.node_id
            )
        )

    async def screenshot(self) -> bytes:
        result = await self._page.send(
            cdp_page.capture_screenshot(format="png", from_surface=True)
        )
        return base64.b64decode(result.data)

    async def current_url(self) -> Optional[str]:
        if not self._page:
            return None
        try:
            return await self._page.evaluate("window.location.href")
        except Exception:
            return None

    async def page_title(self) -> Optional[str]:
        if not self._page:
            return None
        try:
            return await self._page.evaluate("document.title")
        except Exception:
            return None

    async def open_tab(self, url: str, timeout_ms: int = 60000) -> str:
        # browser.get(url) opens a new tab in nodriver
        page = await self._browser.get(url)
        return self._register_tab(page)

    async def switch_tab(self, handle: str) -> None:
        if handle not in self._pages:
            raise ValueError(f"Unknown tab handle '{handle}'")
        self._active = handle
        # nodriver tabs don't need explicit bring_to_front; navigating them makes them targetable
        await asyncio.sleep(0.35 + random.random() * 0.25)

    async def close_tab(self, handle: str) -> None:
        page = self._pages.pop(handle, None)
        if page is None:
            return
        try:
            # tab.close() is async in nodriver
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
        start_time = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - start_time) < (timeout_ms / 1000.0):
            try:
                el = await self._page.select(selector)
                if el:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
        return False

    async def query_links(self, selector: str) -> list[dict[str, str]]:
        # Find all anchors matching selector
        # nodriver select_all returns list of Elements
        elements = await self._page.select_all(selector)
        links: list[dict[str, str]] = []
        for el in elements:
            try:
                # get attribute
                href = el.attrs.get("href") if hasattr(el, "attrs") else None
                if not href:
                    href = await el.evaluate("node => node.getAttribute('href')")
            except Exception:
                href = None
            if not href:
                continue
            try:
                text = (await el.text) or ""
            except Exception:
                text = ""
            links.append({"href": href, "text": text.strip()})
        return links

    async def get_session_state(self) -> dict[str, Any]:
        if not self._page:
            return {}
        try:
            cookies = await self._page.get_cookies()
            serialized_cookies = []
            for c in cookies:
                serialized_cookies.append({
                    "name": getattr(c, "name", ""),
                    "value": getattr(c, "value", ""),
                    "domain": getattr(c, "domain", ""),
                    "path": getattr(c, "path", "/"),
                    "expires": getattr(c, "expires", -1),
                    "httpOnly": getattr(c, "http_only", False) or getattr(c, "httpOnly", False),
                    "secure": getattr(c, "secure", False),
                })
            
            # Local Storage
            local_storage = {}
            try:
                local_storage = await self._page.get_local_storage()
            except Exception:
                pass
                
            origins = []
            if local_storage:
                origin_url = await self.current_url()
                if origin_url:
                    parsed = urlparse(origin_url)
                    origin = f"{parsed.scheme}://{parsed.netloc}"
                    origins.append({
                        "origin": origin,
                        "localStorage": [{"key": k, "value": v} for k, v in local_storage.items()]
                    })
                    
            return {
                "cookies": serialized_cookies,
                "origins": origins
            }
        except Exception as e:
            log.warning("Failed to capture session state (continuing): %s", e)
            return {}

    async def close(self) -> None:
        self._pages = {}
        self._active = None
        try:
            if self._browser is not None:
                # In nodriver, stop is the method to close browser and cleanup
                await self._browser.stop()
        except Exception as e:
            log.debug("nodriver stop failed: %s", e)
        self._browser = None
