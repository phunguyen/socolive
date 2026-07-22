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
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

VN = timezone(timedelta(hours=7))  # match times are displayed in VN time

API = os.environ.get("SOCOLIVE_API", "https://json.vnres.co").rstrip("/")
REFERER = os.environ.get("SOCOLIVE_REF", "https://socoliveaus.co/")
OUTPUT_DIR = Path(os.environ.get("SOCOLIVE_OUT", "output"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
MAX_ROOMS = int(os.environ.get("SOCOLIVE_MAX", "150"))  # cap detail fetches
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
# SOCOLIVE_INSECURE=1 forces TLS verify off. Otherwise we verify, but fall back
# to unverified automatically if a corporate MITM proxy breaks the cert chain
# (the data is public JSON, so integrity isn't security-critical here).
_INSECURE = os.environ.get("SOCOLIVE_INSECURE") == "1"
_CTX = ssl._create_unverified_context() if _INSECURE else None


def _urlopen(req):
    global _INSECURE, _CTX
    try:
        return urllib.request.urlopen(req, timeout=30, context=_CTX)
    except urllib.error.URLError as e:
        if not _INSECURE and "CERTIFICATE_VERIFY_FAILED" in str(e.reason):
            print("⚠️  TLS verify thất bại (proxy MITM?) — thử lại không verify")
            _INSECURE = True
            _CTX = ssl._create_unverified_context()
            return urllib.request.urlopen(req, timeout=30, context=_CTX)
        raise


def fetch(path):
    url = f"{API}/{path}?v={int(time.time() * 1000)}"
    origin = REFERER.rstrip("/")
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": REFERER,
        "Origin": origin,
        "Accept": "*/*",
        "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    })
    raw = _urlopen(req).read().decode("utf-8", "replace")
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


def match_meta():
    """title -> {league, host, guest, hostIcon, guestIcon, time_ms}.

    matches.json has kickoff time + team names/logos. Live-room `title` is
    "<subCateName>: <hostName> vs <guestName>", so we join on that. Best-effort:
    returns {} on any failure and the caller falls back to the raw title.
    """
    try:
        d = fetch("matches.json")
    except Exception as e:
        print(f"⚠️  matches.json lỗi ({e.__class__.__name__}) — bỏ qua time/logo")
        return {}
    ms = []

    def collect(o):
        if isinstance(o, dict):
            if "hostName" in o and "anchors" in o:
                ms.append(o)
            else:
                for v in o.values():
                    collect(v)
        elif isinstance(o, list):
            for v in o:
                collect(v)

    collect(d.get("data"))
    out = {}
    for m in ms:
        league = (m.get("subCateName") or m.get("categoryName") or "").strip()
        host = (m.get("hostName") or "").strip()
        guest = (m.get("guestName") or "").strip()
        key = f"{league}: {host} vs {guest}".strip()
        out[key] = {
            "league": league,
            "host": host,
            "guest": guest,
            "hostIcon": m.get("hostIcon") or "",
            "guestIcon": m.get("guestIcon") or "",
            "time_ms": m.get("matchTime") or 0,
        }
    return out


def fmt_time(ms):
    return datetime.fromtimestamp(ms / 1000, VN).strftime("%H:%M %d/%m") if ms else ""


def run():
    print(f"🔌 API = {API}")
    try:
        rooms = live_rooms()
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        print(f"❌ all_live_rooms.json → HTTP {e.code}. Body: {body!r}")
        return False
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

    # enrich with match time + team logos (best-effort), group by match title.
    # Drop rooms not in the schedule (rebroadcast/commentary) — but only if
    # matches.json loaded; if it failed (meta empty) keep all, don't publish empty.
    meta = match_meta()
    matches = {}
    dropped = 0
    for r in live:
        m = meta.get(r["title"])
        if meta and m is None:
            dropped += 1
            continue
        matches.setdefault(r["title"], {"meta": m, "rooms": []})["rooms"].append(r)
    if dropped:
        print(f"🚫 Bỏ {dropped} luồng không có trong lịch matches.json")

    n_streams = sum(len(v["rooms"]) for v in matches.values())
    export(matches, n_streams)
    return True


def export(matches, n_streams):
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    (OUTPUT_DIR / f"matches_{ts}.json").write_text(
        json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    m3u = OUTPUT_DIR / "socolive.m3u"
    with m3u.open("w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for title, info in matches.items():
            meta = info["meta"]
            if meta:
                league = meta["league"] or "Live"
                teams = f'{meta["host"]} vs {meta["guest"]}'
                t = fmt_time(meta["time_ms"])
                logo = meta["hostIcon"]
            else:  # no schedule entry (e.g. rebroadcast room) → fall back to title
                league = title.split(":")[0].strip() if ":" in title else "Live"
                teams, t, logo = title, "", ""
            head = f"{t} {teams}".strip()
            logo_attr = f' tvg-logo="{logo}"' if logo else ""
            for r in info["rooms"]:
                name = f'{head} — {r["blv"]}' if r["blv"] else head
                f.write(f'#EXTINF:-1{logo_attr} group-title="{league}",{name}\n')
                # pull hosts check Referer/UA; VLC & friends honor these hints
                f.write(f"#EXTVLCOPT:http-referrer={REFERER}\n")
                f.write(f"#EXTVLCOPT:http-user-agent={UA}\n")
                f.write(f"{r['url']}\n")

    print(f"📺 M3U: {m3u}  ({len(matches)} trận, {n_streams} luồng)")
    print("⏳ Lưu ý: URL .m3u8 có auth_key hết hạn sau ~vài giờ — chạy lại khi cần.")

    rows = []
    for title, info in matches.items():
        meta = info["meta"]
        if meta:
            ico = lambda u: f'<img src="{u}" width="18" style="vertical-align:middle">' if u else ""
            head = (f'{ico(meta["hostIcon"])} <b>{meta["host"]} vs {meta["guest"]}</b> '
                    f'{ico(meta["guestIcon"])} <small>{meta["league"]} · {fmt_time(meta["time_ms"])}</small>')
        else:
            head = f"<b>{title}</b>"
        links = " · ".join(f'<a href="{r["url"]}">{r["blv"] or "stream"}</a>' for r in info["rooms"])
        rows.append(f"<li>{head}<br><small>{links}</small></li>")
    updated = datetime.now(VN).strftime("%Y-%m-%d %H:%M")
    (OUTPUT_DIR / "index.html").write_text(
        f"""<!doctype html><meta charset="utf-8">
<title>Socolive M3U</title>
<style>body{{font-family:system-ui,sans-serif;max-width:820px;margin:2rem auto;padding:0 1rem}}
li{{margin:.7rem 0}}a{{color:#0a58ca;text-decoration:none}}img{{border-radius:3px}}</style>
<h1>📺 Socolive M3U</h1>
<p>Cập nhật: {updated} (VN) · {len(matches)} trận · {n_streams} luồng</p>
<p><b>Playlist:</b> <a href="socolive.m3u">socolive.m3u</a> — mở trong VLC / OTT Navigator / IINA.</p>
<ol>{''.join(rows) or '<li>Chưa có trận nào đang live.</li>'}</ol>""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)
