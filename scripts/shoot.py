"""Screenshot the main pages of a running Encore (headless) for a visual check."""
import asyncio, sys
from playwright.async_api import async_playwright
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8077"
OUT = sys.argv[2] if len(sys.argv) > 2 else "../shots"
PAGES = [("today", "/", "text=Music hour"), ("resident", "/residents/r-tomasz", "text=Songs and singers"),
         ("lounge", "/lounge", "text=Fit for every resident"), ("music", "/lounge?tab=music", "text=A song for everyone"),
         ("residents", "/residents", "text=Carers"), ("qloo", "/qloo", "text=Most recent requests"), ("how", "/how", "text=Data and limits")]
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        for scheme in ("light", "dark"):
            ctx = await b.new_context(viewport={"width": 1366, "height": 900}, color_scheme=scheme)
            pg = await ctx.new_page()
            errs = []
            pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            for name, path, wait in PAGES if scheme == "light" else PAGES[:3]:
                await pg.goto(BASE + path)
                try:
                    await pg.wait_for_selector(wait, timeout=90000)
                except Exception as e:
                    print("timeout", name)
                await pg.wait_for_timeout(3500)
                await pg.screenshot(path=f"{OUT}/{name}-{scheme}.png", full_page=True)
                print("shot", name, scheme)
            if errs: print("console errors:", errs[:5])
            await ctx.close()
        await b.close()
asyncio.run(main())
