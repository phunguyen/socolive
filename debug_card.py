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

        print("Đang truy cập...")
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=90000)
        await asyncio.sleep(6)

        # Lấy 1 link đầu tiên để xem cấu trúc HTML cha
        link = page.locator('a[href*="/truc-tiep/"]').first
        href = await link.get_attribute("href")
        print(f"href: {href}\n")

        # In HTML của parent container (3 cấp lên)
        parent_html = await page.evaluate("""
            (el) => {
                let p = el;
                for (let i = 0; i < 5; i++) {
                    if (p.parentElement) p = p.parentElement;
                }
                return p.outerHTML.substring(0, 3000);
            }
        """, await link.element_handle())
        print("Parent HTML (5 levels up):\n", parent_html)

        # Thử tìm card container bằng selector phổ biến
        for selector in ['.match-item', '.match-card', '.item-match', '.card', '[class*="match"]', '[class*="card"]']:
            count = await page.locator(selector).count()
            if count > 0:
                print(f"\nSelector '{selector}': {count} elements")
                el = page.locator(selector).first
                print(await el.inner_text())
                break

        await browser.close()

asyncio.run(debug())
