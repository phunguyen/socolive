// Cloudflare Worker: proxy for the Socolive JSON API (json.vnres.co).
//
// The API blocks datacenter IPs (GitHub Actions runners get 403). A Worker
// fetches it from inside Cloudflare's network, which bypasses that block.
// Point the crawler at this Worker's URL via SOCOLIVE_API.
//
// Locked to json.vnres.co and *.json paths so it can't be used as an open proxy.

const UPSTREAM = "https://json.vnres.co";
const REFERER = "https://socoliveaus.co/";
const UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36";

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (!url.pathname.endsWith(".json")) {
      return new Response("Not found", { status: 404 });
    }
    const target = UPSTREAM + url.pathname + url.search;
    const upstream = await fetch(target, {
      headers: {
        "User-Agent": UA,
        Referer: REFERER,
        Origin: REFERER.replace(/\/$/, ""),
        Accept: "*/*",
        "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
      },
      cf: { cacheTtl: 8, cacheEverything: true }, // small cache eases upstream load
    });
    const body = await upstream.text();
    return new Response(body, {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") || "application/json",
        "access-control-allow-origin": "*",
        "cache-control": "public, max-age=8",
      },
    });
  },
};
