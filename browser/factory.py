"""
Browser adapter factory — instantiates the adapter FGOS chose via
job.browser_profile.browser_type. The runner never decides which browser;
it only knows how to construct the one it was told to use.
"""

from __future__ import annotations

from browser.adapter import BrowserAdapter
from browser.camoufox_adapter import CamoufoxAdapter

_REGISTRY: dict[str, type[BrowserAdapter]] = {
    "camoufox": CamoufoxAdapter,
    # "playwright": PlaywrightAdapter,  # future
    # "chrome": ChromeAdapter,          # future
}


def create_browser_adapter(browser_type: str) -> BrowserAdapter:
    cls = _REGISTRY.get(browser_type)
    if cls is None:
        raise ValueError(
            f"Unknown browser_type '{browser_type}' — FGOS sent an adapter this runner "
            f"doesn't implement yet. Known: {list(_REGISTRY)}"
        )
    return cls()
