"""
Browser adapter factory — instantiates the adapter FGOS chose via
job.browser_profile.browser_type. The runner never decides which browser;
it only knows how to construct the one it was told to use.
"""

from __future__ import annotations

from browser.adapter import BrowserAdapter
from browser.camoufox_adapter import CamoufoxAdapter
from browser.playwright_adapter import PlaywrightAdapter

def create_browser_adapter(browser_type: str) -> BrowserAdapter:
    if browser_type == "camoufox":
        return CamoufoxAdapter()
    elif browser_type == "playwright_chromium":
        return PlaywrightAdapter(browser_type="chromium")
    elif browser_type == "playwright_firefox":
        return PlaywrightAdapter(browser_type="firefox")
    elif browser_type == "playwright_webkit":
        return PlaywrightAdapter(browser_type="webkit")
    elif browser_type == "cloakbrowser":
        from browser.cloakbrowser_adapter import CloakBrowserAdapter
        return CloakBrowserAdapter()
    elif browser_type == "nodriver":
        from browser.nodriver_adapter import NodriverAdapter
        return NodriverAdapter()
    else:
        raise ValueError(
            f"Unknown browser_type '{browser_type}' — FGOS sent an adapter this runner "
            f"doesn't implement yet. Known: camoufox, cloakbrowser, nodriver, playwright_chromium, playwright_firefox, playwright_webkit"
        )
