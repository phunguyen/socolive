import asyncio
from playwright.async_api import async_playwright

BASE_URL = "https://socolive16.cv/"

async def debug():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = await context.new_page()
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=90000)
        await asyncio.sleep(6)

        # Click tennis tab
        await page.get_by_text("TENNIS", exact=False).first.click(timeout=10000)
        await asyncio.sleep(4)

        cards = await page.locator('.match-item').all()
        print(f"Tennis: {len(cards)} cards\n")

        for i, card in enumerate(cards[:3]):
            text = await card.inner_text()
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            html = await card.inner_html()
            print(f"--- Card #{i+1} ---")
            print(f"lines: {lines}")
            print(f"html (500): {html[:500]}")
            print()

        await browser.close()

asyncio.run(debug())
