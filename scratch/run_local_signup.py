import asyncio
from browser.factory import create_browser_adapter
from account_creation.identity import generate_identity
from account_creation.create_buyer_account import _signup_fiverr, _signup_outlook

class MockReporter:
    def step(self, msg): print(f"STEP: {msg}"); return True
    def fail(self, msg): print(f"FAIL: {msg}")
    def needs_review(self, msg, **kwargs): print(f"NEEDS REVIEW: {msg} {kwargs}")
    def complete(self, **kwargs): print(f"COMPLETE: {kwargs}")
    def add_screenshot_ref(self, ref): print(f"SCREENSHOT: {ref}")
    def blocked(self, msg): print(f"BLOCKED: {msg}")

async def main():
    identity = generate_identity()
    print(f"Generated identity: {identity.email} / {identity.password}")
    
    # We will use normal playwright for outlook
    outlook_browser = create_browser_adapter("playwright_chromium")
    # We will use cloakbrowser for fiverr to test stealth
    fiverr_browser = create_browser_adapter("cloakbrowser")
    
    reporter = MockReporter()
    
    # Run browsers locally with headless=False so you can see what happens!
    await outlook_browser.start({"headless": False})
    await fiverr_browser.start({"headless": False})
    
    try:
        # Step 1: Outlook Signup
        print("Starting Outlook Signup...")
        outlook_identity = await _signup_outlook(outlook_browser, reporter)
        if outlook_identity:
            identity = outlook_identity
            print("Outlook signup success!")
        else:
            print("Outlook signup failed, but continuing to Fiverr anyway for CAPTCHA testing.")
            
        # Step 2: Fiverr Signup
        job = {"metadata": {"fiverr_signup_url": "https://www.fiverr.com/s/9VpeQZ1"}} # a random dummy gig URL format, or use fiverr homepage directly to trigger contact seller if possible.
        # Actually, let's just go to Fiverr directly if we can't find a gig.
        # The script clicks "Contact Seller", so we need a real gig.
        job["metadata"]["fiverr_signup_url"] = "https://www.fiverr.com/yossef_saad/create-a-creative-animated-explainer-video"
        
        print("Starting Fiverr Signup...")
        res = await _signup_fiverr(outlook_browser, fiverr_browser, reporter, identity, job)
        print("Fiverr signup result:", res)
        
        print("Test finished. Keeping browsers open for 15 seconds to inspect...")
        await asyncio.sleep(15)
        
    finally:
        await outlook_browser.close()
        await fiverr_browser.close()

if __name__ == "__main__":
    asyncio.run(main())
