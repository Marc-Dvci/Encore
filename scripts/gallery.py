"""3:2 gallery captures (1500x1000 at 2x) of the key screens of a running Encore."""
import asyncio, sys
from playwright.async_api import async_playwright
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8077"
OUT = sys.argv[2] if len(sys.argv) > 2 else "../gallery"

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={"width": 1500, "height": 1000}, device_scale_factor=2)
        pg = await ctx.new_page()
        async def shot(name, path=None, wait=None, scroll=None, settle=3000):
            if path:
                await pg.goto(BASE + path)
            if wait:
                await pg.wait_for_selector(wait, timeout=120000)
            await pg.wait_for_timeout(settle)
            if scroll:
                await pg.locator(scroll).first.evaluate("e => e.scrollIntoView({block: 'start'})")
                await pg.evaluate("window.scrollBy(0, -96)")
                await pg.wait_for_timeout(600)
            await pg.screenshot(path=f"{OUT}/{name}.png")
            print(name)
        await shot("01_today", "/", "text=Music hour")
        await shot("02_resident_era", "/residents/r-tomasz", "text=Songs and singers")
        await shot("03_resident_songs", None, None, "h2:has-text('Songs and singers')", 500)
        await shot("04_confirm_favourite", None, None, "text=Which one do they mean", 300)
        await shot("05_lounge_pick", "/lounge", "text=Fit for every resident")
        await shot("06_lounge_cost", None, None, "h2:has-text('What each way')", 300)
        await shot("07_lounge_matrix", None, None, "h2:has-text('Fit for every resident')", 300)
        await shot("08_music_hour", "/lounge?tab=music", "text=A song for everyone")
        await pg.goto(BASE + "/residents/r-tomasz")
        await pg.wait_for_selector("text=Plan session")
        await pg.locator("button:has-text('Plan session')").click()
        await pg.wait_for_url("**/session/**", timeout=120000)
        await shot("09_session_words", None, "text=What to say")
        await pg.locator(".react:has-text('Lit up')").nth(1).click()
        await pg.wait_for_selector(".effect", timeout=60000)
        await shot("10_session_learning", None, None, ".effect", 500)
        await shot("11_session_common_ground", None, None, "text=Something Priya and Tomasz share", 300)
        await pg.goto(BASE + "/ask")
        await pg.locator("button:has-text('Pick the lounge film')").click()
        await pg.wait_for_selector(".trace", timeout=120000)
        await pg.locator(".trace details summary").first.click()
        await shot("12_ask_encore", None, None, None, 800)
        await shot("13_what_qloo_saw", "/qloo", "text=Most recent requests")
        await shot("14_how_it_works_results", "/how", "text=Data and limits", "h2:has-text('Encore against a model')", 1000)
        await shot("15_activity_record", "/record/r-tomasz", "text=Participation and response")
        dark = await b.new_context(viewport={"width": 1500, "height": 1000}, device_scale_factor=2, color_scheme="dark")
        pg = await dark.new_page()
        await shot("16_resident_dark", "/residents/r-giuseppe", "text=Songs and singers")
        await b.close()
asyncio.run(main())
