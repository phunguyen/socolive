"""Socolive live-stream crawler.

The Socolive web frontends (socolivef.cv, socoliveaus.co, …) rotate domains and
sit behind Cloudflare, which challenges datacenter IPs (GitHub Actions) on the
player pages. But they all read from one static JSON API on a stable CDN host:

    https://json.vnres.co/all_live_rooms.json      -> live matches + rooms (JSONP)
    https://json.vnres.co/room/<roomNum>/detail.json -> that room's stream URLs

So we skip the browser entirely and hit the API directly over plain HTTP:
fast, no bot-challenge, and domain-rotation stops mattering.
"""
import json
import os
import ssl
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

API = os.environ.get("SOCOLIVE_API", "https://json.vnres.co").rstrip("/")
REFERER = os.environ.get("SOCOLIVE_REF", "https://socoliveaus.co/")
OUTPUT_DIR = Path(os.environ.get("SOCOLIVE_OUT", "output"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
MAX_ROOMS = int(os.environ.get("SOCOLIVE_MAX", "150"))  # cap detail fetches
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
# SOCOLIVE_INSECURE=1 skips TLS verify (only for a local MITM proxy; CI verifies).
_CTX = ssl._create_unverified_context() if os.environ.get("SOCOLIVE_INSECURE") == "1" else None


def fetch(path):
    url = f"{API}/{path}?v={int(time.time() * 1000)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": REFERER, "Accept": "*/*"})
    raw = urllib.request.urlopen(req, timeout=30, context=_CTX).read().decode("utf-8", "replace")
    a, b = raw.find("("), raw.rfind(")")  # strip JSONP wrapper: name({...})
    if a != -1 and b > a:
        raw = raw[a + 1:b]
    return json.loads(raw)


def live_rooms():
    """All currently-live rooms, deduped by roomNum."""
    d = fetch("all_live_rooms.json")
    out = {}
    for group in d.get("data", {}).values():
        if not isinstance(group, list):
            continue
        for r in group:
            rn = r.get("roomNum")
            if r.get("liveStatus") == 1 and rn:
                # BLV name lives in anchor.nickName; `detail` is sometimes a blurb
                blv = ((r.get("anchor") or {}).get("nickName") or r.get("detail") or "").strip()
                out[str(rn)] = {
                    "room": str(rn),
                    "title": (r.get("title") or "").strip() or "Live",
                    "blv": blv,
                }
    return list(out.values())


def stream_url(room):
    try:
        st = fetch(f"room/{room}/detail.json").get("data", {}).get("stream") or {}
        return st.get("hdM3u8") or st.get("m3u8")  # prefer HD
    except Exception:
        return None


def run():
    try:
        rooms = live_rooms()
    except Exception as e:
        print(f"❌ Không lấy được all_live_rooms.json: {e.__class__.__name__}: {e}")
        return False  # API down/blocked → keep last good m3u, fail so CI alerts

    print(f"📋 {len(rooms)} phòng đang LIVE (lấy stream tối đa {MAX_ROOMS})...")
    rooms = rooms[:MAX_ROOMS]
    with ThreadPoolExecutor(max_workers=10) as ex:
        for r, url in zip(rooms, ex.map(lambda x: stream_url(x["room"]), rooms)):
            r["url"] = url or ""

    live = [r for r in rooms if r["url"].startswith("http")]

    if rooms and not live:
        # rooms listed but no stream URLs → detail API likely blocked; don't
        # overwrite the last good playlist, fail so we get alerted.
        print("❌ Có phòng live nhưng không lấy được stream nào — giữ m3u cũ.")
        return False

    # group rooms by match title
    matches = {}
    for r in live:
        matches.setdefault(r["title"], []).append(r)

    export(matches, len(live))
    return True


def export(matches, n_streams):
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    (OUTPUT_DIR / f"matches_{ts}.json").write_text(
        json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    m3u = OUTPUT_DIR / "socolive.m3u"
    with m3u.open("w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for title, rooms in matches.items():
            for r in rooms:
                name = f'{title} — {r["blv"]}' if r["blv"] else title
                f.write(f'#EXTINF:-1 group-title="{title}",{name}\n')
                # pull hosts check Referer/UA; VLC & friends honor these hints
                f.write(f"#EXTVLCOPT:http-referrer={REFERER}\n")
                f.write(f"#EXTVLCOPT:http-user-agent={UA}\n")
                f.write(f"{r['url']}\n")

    print(f"📺 M3U: {m3u}  ({len(matches)} trận, {n_streams} luồng)")
    print("⏳ Lưu ý: URL .m3u8 có auth_key hết hạn sau ~vài giờ — chạy lại khi cần.")

    rows = []
    for title, rooms in matches.items():
        links = " · ".join(f'<a href="{r["url"]}">{r["blv"] or "stream"}</a>' for r in rooms)
        rows.append(f"<li><b>{title}</b><br><small>{links}</small></li>")
    updated = datetime.now().strftime("%Y-%m-%d %H:%M")
    (OUTPUT_DIR / "index.html").write_text(
        f"""<!doctype html><meta charset="utf-8">
<title>Socolive M3U</title>
<style>body{{font-family:system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem}}
li{{margin:.6rem 0}}a{{color:#0a58ca;text-decoration:none}}</style>
<h1>📺 Socolive M3U</h1>
<p>Cập nhật: {updated} · {len(matches)} trận · {n_streams} luồng</p>
<p><b>Playlist:</b> <a href="socolive.m3u">socolive.m3u</a> — mở trong VLC / OTT Navigator / IINA.</p>
<ol>{''.join(rows) or '<li>Chưa có trận nào đang live.</li>'}</ol>""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)
