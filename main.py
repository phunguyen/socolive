import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

from playwright.async_api import async_playwright

# These sites rotate domains constantly. Candidate base URLs come from (in order):
#   1) $SOCOLIVE_BASE (comma-separated)   2) base.txt (one per line)   3) built-in default
# The crawler tries each until one loads, and follows redirects to the live domain.
# To update fast: edit base.txt in the GitHub web UI — the push triggers a fresh run.
def load_bases():
    env = os.environ.get("SOCOLIVE_BASE", "")
    if env.strip():
        return [u.strip() for u in env.split(",") if u.strip()]
    f = Path(__file__).parent / "base.txt"
    if f.exists():
        lines = [l.strip() for l in f.read_text().splitlines()]
        bases = [l for l in lines if l and not l.startswith("#")]
        if bases:
            return bases
    return ["https://socolivef.cv/"]

BASES = load_bases()
OUTPUT_DIR = Path(os.environ.get("SOCOLIVE_OUT", "output"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

HEADLESS = os.environ.get("SOCOLIVE_HEADLESS", "1") != "0"  # CI needs headless
MAX_MATCHES = int(os.environ.get("SOCOLIVE_MAX", "40"))  # cap detail visits
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

# window.streamData = {...};  — the real HLS URLs live here, one per broadcaster
STREAMDATA_RE = re.compile(r"window\.streamData\s*=\s*(\{.*?\})\s*;", re.DOTALL)


def strip_query(url: str) -> str:
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))


def pretty_from_slug(slug: str) -> str:
    # dong-nai-u21-vs-shb-da-nang-u21-17-07-2026-1530 -> "Dong Nai U21 Vs Shb Da Nang U21"
    slug = re.sub(r"[-/]\d{2}-\d{2}-\d{4}.*$", "", slug)  # drop trailing date/time
    return slug.replace("-", " ").strip().title()


async def goto_retry(page, url, tries=3):
    for i in range(tries):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=90000)
            return True
        except Exception as e:
            if i == tries - 1:
                print(f"   ⚠️  bỏ qua (goto fail): {url}  {e.__class__.__name__}")
                return False
            await asyncio.sleep(2.5)
    return False


class SocoliveCrawler:
    def __init__(self):
        self.matches = []  # {slug, name, detail_url, anchors:[{name,url}]}
        self.base = BASES[0]  # resolved live base (used for m3u referrer)
        self.challenged = 0   # detail pages we couldn't read (bot challenge)

    async def run(self):
        async with async_playwright() as p:
            # headless Chromium gets a stripped bot-challenge page (no streamData);
            # these flags make it look like a real browser so we get the full page.
            browser = await p.chromium.launch(
                headless=HEADLESS, args=["--disable-blink-features=AutomationControlled"]
            )
            context = await browser.new_context(viewport={"width": 1600, "height": 900}, user_agent=UA)
            await context.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});window.chrome={runtime:{}};"
            )
            page = await context.new_page()

            for candidate in BASES:
                print(f"🌐 Thử trang chủ: {candidate}")
                if await goto_retry(page, candidate, tries=2):
                    break
            else:
                print("❌ Không domain nào truy cập được. Cập nhật base.txt.")
                await browser.close()
                return False  # domain dead → fail the CI job → GitHub emails owner
            await asyncio.sleep(5)
            base = page.url  # follows redirects to the live domain
            self.base = base

            hrefs = await page.eval_on_selector_all(
                'a[href*="/truc-tiep/"]',
                "els => [...new Set(els.map(e => e.getAttribute('href')))]",
            )
            # one URL per match (by path), preferring a ?blv= variant — the bare
            # URL is sometimes gated while the broadcaster URL serves streamData.
            by_path = {}
            for h in hrefs:
                full = urljoin(base, h)
                path = urlparse(full).path
                if "/truc-tiep/" not in path:
                    continue
                if path not in by_path or "blv=" in full:
                    by_path[path] = full
            detail_urls = list(by_path.values())
            print(f"📋 {len(detail_urls)} trận. Vào chi tiết tối đa {MAX_MATCHES}...\n")

            if not detail_urls:
                # home loaded but no matches → parked page / structure changed / soft block.
                # Don't overwrite the last good m3u; fail so we get alerted.
                print("❌ Trang chủ không có trận nào — có thể domain đã đổi cấu trúc/bị chặn.")
                await browser.close()
                return False

            for i, url in enumerate(detail_urls[:MAX_MATCHES], 1):
                await self.crawl_detail(page, url, i)

            await browser.close()

        # Blocked run: nothing captured but pages were being challenged → don't
        # overwrite the last good m3u with an empty one; fail so we get alerted.
        if not self.matches and self.challenged:
            print("❌ Không lấy được trận nào do bị chặn — giữ m3u cũ, không ghi đè.")
            return False

        self.save_data()
        return True  # 0 trận live (challenged==0) vẫn OK — thật sự không có trận phát

    async def crawl_detail(self, page, url, idx):
        slug = urlparse(url).path.rstrip("/").split("/")[-1]
        name = pretty_from_slug(slug)

        html, challenged = await self._fetch_with_streamdata(page, url)
        anchors = self._parse_anchors(html)

        if anchors:
            self.matches.append({"slug": slug, "name": name, "detail_url": url, "anchors": anchors})
            print(f"   ✓ [{idx}] {name}  → {len(anchors)} luồng")
        elif challenged:
            self.challenged += 1
            print(f"   ⚠️  [{idx}] {name}  → bị chặn/challenge (không đọc được streamData)")
        else:
            print(f"   – [{idx}] {name}  → không có luồng (chưa live?)")

    async def _fetch_with_streamdata(self, page, url):
        # Returns (html, challenged). Fast path: streamData is in the initial HTML
        # for live matches, and a real not-live page carries the site's player
        # assets — so we can tell "not live" from "bot challenge" without waiting.
        # Only the small stripped challenge page triggers a reload retry.
        html = ""
        for _ in range(3):
            if not await goto_retry(page, url, tries=2):
                continue
            await asyncio.sleep(1.2)
            html = await page.content()
            if "window.streamData" in html:
                return html, False  # live — got the data
            if "stream-player-plugin" in html or "jwplayer" in html:
                return html, False  # real page, just not live → don't retry
            await asyncio.sleep(2.0)  # small challenge page → reload and retry
        return html, True

    @staticmethod
    def _parse_anchors(html):
        anchors = []
        m = STREAMDATA_RE.search(html)
        if m:
            try:
                for a in json.loads(m.group(1)).get("anchors", []):
                    su = a.get("streamUrl")
                    if su and ".m3u8" in su:
                        label = (a.get("nickName") or "").strip() or f"BLV {a.get('roomID', '')}"
                        anchors.append({"name": label, "url": su})
            except json.JSONDecodeError:
                pass
        return anchors

    def save_data(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        with open(OUTPUT_DIR / f"matches_{ts}.json", "w", encoding="utf-8") as f:
            json.dump(self.matches, f, ensure_ascii=False, indent=2)
        self.export_m3u()

    def export_m3u(self):
        path = OUTPUT_DIR / "socolive.m3u"
        streams = 0
        with open(path, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for match in self.matches:
                for a in match["anchors"]:
                    title = f'{match["name"]} — {a["name"]}' if a["name"] else match["name"]
                    f.write(f'#EXTINF:-1 group-title="{match["name"]}",{title}\n')
                    # niues.live checks Referer/UA; VLC & friends honor these hints
                    f.write(f"#EXTVLCOPT:http-referrer={self.base}\n")
                    f.write(f"#EXTVLCOPT:http-user-agent={UA}\n")
                    f.write(f"{a['url']}\n")
                    streams += 1
        print(f"\n📺 M3U: {path}  ({len(self.matches)} trận, {streams} luồng)")
        if self.challenged:
            print(f"⚠️  {self.challenged} trang bị chặn/challenge — có thể sót trận. IP runner có thể bị rate-limit.")
        print("⏳ Lưu ý: URL .m3u8 có auth_key hết hạn sau ~vài giờ — chạy lại khi cần.")
        self.export_index(streams)

    def export_index(self, streams):
        # minimal landing page for GitHub Pages
        rows = []
        for match in self.matches:
            links = " · ".join(
                f'<a href="{a["url"]}">{a["name"] or "stream"}</a>' for a in match["anchors"]
            )
            rows.append(f"<li><b>{match['name']}</b><br><small>{links}</small></li>")
        updated = datetime.now().strftime("%Y-%m-%d %H:%M")
        html = f"""<!doctype html><meta charset="utf-8">
<title>Socolive M3U</title>
<style>body{{font-family:system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem}}
li{{margin:.6rem 0}}a{{color:#0a58ca;text-decoration:none}}code{{background:#eee;padding:.15rem .35rem;border-radius:4px}}</style>
<h1>📺 Socolive M3U</h1>
<p>Cập nhật: {updated} · {len(self.matches)} trận · {streams} luồng</p>
<p><b>Playlist:</b> <a href="socolive.m3u">socolive.m3u</a>
 — mở link này trong VLC / OTT Navigator / IINA.</p>
<ol>{''.join(rows) or '<li>Chưa có trận nào đang live.</li>'}</ol>"""
        (OUTPUT_DIR / "index.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    import sys
    ok = asyncio.run(SocoliveCrawler().run())
    sys.exit(0 if ok else 1)
