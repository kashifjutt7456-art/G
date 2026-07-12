"""
BrowserAdapter — interface. FGOS decides WHICH browser engine via the job's
browser_profile (browser_type: camoufox | playwright | chrome); the runner
just instantiates the matching adapter and calls these methods. No job/outreach
logic belongs here — this is purely "drive a browser."
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class BrowserAdapter(ABC):
    """One browser session. A fresh adapter instance is created per job."""

    @abstractmethod
    async def start(self, fingerprint_config: dict[str, Any], proxy: Optional[dict[str, Any]] = None) -> None:
        """Launch the browser + context with the given fingerprint config and
        optional proxy (host/port/username/password), already resolved by the
        caller via the network adapter — this method never talks to a VPN."""

    @abstractmethod
    async def open(self, url: str, timeout_ms: int = 60000) -> None:
        """Navigate the active page to url."""

    @abstractmethod
    async def click(self, selector: str, timeout_ms: int = 15000) -> None:
        """Click the first element matching selector."""

    @abstractmethod
    async def type(self, selector: str, text: str, humanize: bool = True) -> None:
        """Type text into the element matching selector."""

    @abstractmethod
    async def press_and_hold(self, selector: str, duration_ms: int = 10000) -> None:
        """Simulate a mouse press and hold on an element for the specified duration (for CAPTCHAs)."""

    @abstractmethod
    async def press_and_hold_at(self, x: int, y: int, duration_ms: int = 15000) -> None:
        """Simulate a mouse press and hold at specific coordinates (for CAPTCHAs)."""

    @abstractmethod
    async def upload(self, selector: str, file_path: str) -> None:
        """Attach a local file to a file input matching selector."""

    @abstractmethod
    async def screenshot(self) -> bytes:
        """Return a PNG screenshot of the current page."""

    @abstractmethod
    async def close(self) -> None:
        """Tear down the browser/context. Must be safe to call twice."""

    # ── Multi-tab support. One browser/context, N tabs — a handle identifies
    #    a tab; whichever tab was most recently opened or switch_tab()'d is
    #    "active" and is what open/click/type/upload/screenshot/current_url/
    #    page_title operate on. A fresh adapter starts with exactly one tab
    #    already active (created by start()), so single-tab callers (e.g.
    #    outreach/send_message.py) need zero changes. ───────────────────────
    @abstractmethod
    async def open_tab(self, url: str, timeout_ms: int = 60000) -> str:
        """Open a new tab, navigate it to url, make it the active tab, and
        return a handle usable with switch_tab()/close_tab()."""

    @abstractmethod
    async def switch_tab(self, handle: str) -> None:
        """Make the given tab active. Subsequent open/click/type/upload/
        screenshot/current_url/page_title calls target it until switch_tab()
        is called again."""

    @abstractmethod
    async def close_tab(self, handle: str) -> None:
        """Close a tab. Safe to call on the currently-active tab — the
        adapter falls back to another open tab as active if so."""

    @abstractmethod
    async def current_tab(self) -> str:
        """Return the handle of the currently-active tab."""

    # ── DOM escape hatches — narrow, engine-neutral primitives for cases
    #    click()/type() don't cover. Fiverr/Outlook-specific selector and
    #    link-preference logic stays in handler modules, not here. ──────────
    @abstractmethod
    async def wait_for(self, selector: str, timeout_ms: int = 15000) -> bool:
        """Wait for selector to become visible in the active tab. Returns
        True/False, never raises — for existence checks (e.g. "did the
        reading pane load") without a try/except at every call site."""

    @abstractmethod
    async def query_links(self, selector: str) -> list[dict[str, str]]:
        """Return [{href, text}] for every anchor matching selector in the
        active tab."""

    @abstractmethod
    async def get_session_state(self) -> dict[str, Any]:
        """Return serializable session state (cookies + storage) for the
        current browser context — shared across all tabs since they share
        one context."""

    # ── Convenience helpers shared by all adapters (not abstract — adapters
    #    may override, but the default is fine for most). ─────────────────────
    async def current_url(self) -> Optional[str]:
        return None

    async def page_title(self) -> Optional[str]:
        return None
