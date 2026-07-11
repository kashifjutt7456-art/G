import asyncio
import sys
import os

# Add buyer_network_runner to python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from browser.factory import create_browser_adapter

async def test_single_adapter(engine_name: str):
    print(f"\n==========================================")
    print(f"Testing browser engine: {engine_name}")
    print(f"==========================================")
    
    try:
        browser = create_browser_adapter(engine_name)
    except Exception as e:
        print(f"[-] Failed to instantiate adapter '{engine_name}': {e}")
        return False

    try:
        # Launch headless for testing
        fingerprint_config = {
            "headless": True,
            "window": [1280, 800],
            "os": "windows"
        }
        
        print(f"[!] Starting browser '{engine_name}'...")
        await browser.start(fingerprint_config)
        
        print(f"[!] Navigating to test page...")
        await browser.open("https://example.com")
        
        url = await browser.current_url()
        title = await browser.page_title()
        print(f"[+] Navigation successful. URL: {url}, Title: {title}")
        
        print(f"[!] Taking screenshot...")
        screenshot_bytes = await browser.screenshot()
        print(f"[+] Screenshot size: {len(screenshot_bytes)} bytes")
        
        print(f"[!] Fetching session state...")
        state = await browser.get_session_state()
        cookies_count = len(state.get("cookies", []))
        print(f"[+] Session state retrieved. Cookies found: {cookies_count}")
        
        print(f"[!] Closing browser '{engine_name}'...")
        await browser.close()
        print(f"[+] Engine '{engine_name}' passed all basic tests!")
        return True
        
    except Exception as e:
        print(f"[-] Test failed for engine '{engine_name}': {e}")
        try:
            await browser.close()
        except Exception:
            pass
        return False

async def main():
    engines_to_test = [
        "playwright_chromium",
        "camoufox",
        "cloakbrowser",
        "nodriver"
    ]
    
    results = {}
    for engine in engines_to_test:
        success = await test_single_adapter(engine)
        results[engine] = "PASSED" if success else "FAILED"
        
    print("\n==========================================")
    print("FINAL TEST RESULTS SUMMARY:")
    print("==========================================")
    for engine, status in results.items():
        icon = "[+]" if status == "PASSED" else "[-]"
        print(f"{icon} {engine}: {status}")
    print("==========================================")

if __name__ == "__main__":
    # Ensure correct event loop execution
    asyncio.run(main())
