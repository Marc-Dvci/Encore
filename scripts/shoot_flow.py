"""Screenshot the session flow and the agent against a running Encore."""
import asyncio, sys
from playwright.async_api import async_playwright
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8077"
OUT = sys.argv[2] if len(sys.argv) > 2 else "../shots"
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await (await b.new_context(viewport={"width": 1366, "height": 900})).new_page()
        await pg.goto(BASE + "/")
        await pg.wait_for_selector("text=Plan session", timeout=120000)
        await pg.locator("button:has-text('Plan session')").first.click()
        await pg.wait_for_url("**/session/**", timeout=120000)
        await pg.wait_for_selector("text=What to say")
        await pg.wait_for_timeout(3000)
        await pg.screenshot(path=f"{OUT}/session.png", full_page=True)
        await pg.locator(".react:has-text('Lit up')").nth(1).click()
        await pg.wait_for_selector(".effect", timeout=60000)
        await pg.wait_for_timeout(800)
        await pg.screenshot(path=f"{OUT}/session-react.png", full_page=True)
        await pg.goto(BASE + "/ask")
        await pg.locator("button:has-text('Priya is sitting with Tomasz')").click()
        await pg.wait_for_selector(".msg.model >> nth=0", timeout=120000)
        await pg.wait_for_selector(".trace", timeout=120000)
        await pg.locator(".trace details summary").first.click()
        await pg.wait_for_timeout(800)
        await pg.screenshot(path=f"{OUT}/ask.png", full_page=True)
        m = await (await b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)).new_page()
        await m.goto(BASE + "/")
        await m.wait_for_selector("text=Music hour")
        await m.wait_for_timeout(2500)
        await m.screenshot(path=f"{OUT}/mobile-today.png", full_page=False)
        print("ok")
        await b.close()
asyncio.run(main())
