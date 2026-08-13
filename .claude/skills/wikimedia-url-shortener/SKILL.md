---
name: wikimedia-url-shortener
description: Create and expand w.wiki short URLs (Wikimedia's URL shortener) — redirect behavior, the missing expansion API, the browser CORS trap, server-side resolution patterns, and creation via the meta.wikimedia.org API
license: MIT
compatibility: opencode
depends_on: [wikimedia-api-access, wikimedia-auth-oauth]
skill_discovery_hints:
  - keywords: ["w.wiki", "short URL", "URL shortener", "shorten link", "shortlink", "Wikimedia URL Shortener", "UrlShortener"]
  - keywords: ["expand short url", "resolve redirect", "w.wiki api", "shortenurl"]
  - keywords: ["QR code", "qrcode", "special:urlshortener"]
last_verified: 2026-08-12
---

# Wikimedia URL Shortener (w.wiki)

> ⚠️ **User-Agent required:** All requests to `w.wiki` and `meta.wikimedia.org`
> need a descriptive User-Agent. See the
> **[wikimedia-api-access](../wikimedia-api-access/SKILL.md)** skill.

## What It Is

**w.wiki** is the Wikimedia Foundation's URL shortener, built on the
[Extension:UrlShortener](https://www.mediawiki.org/wiki/Extension:UrlShortener)
extension. Short URLs look like `https://w.wiki/TR9R` (or bare `w.wiki/TR9R`)
and **301-redirect** to the target URL.

- **Create** short URLs at `https://meta.wikimedia.org/wiki/Special:UrlShortener`
  or via the API (below). Requires edit rights on Meta-Wiki.
- **Expand** a short URL: **there is no expansion API** (see Gotcha 1) — the
  only way is to follow the redirect.
- **QR code** for any URL: `https://meta.wikimedia.org/wiki/Special:QrCode?url=<url>`
  (302s to a PNG).

## Quick Reference

| Task | Method |
|---|---|
| Expand a short URL (server-side) | `curl -sI https://w.wiki/CODE` → read `location:` header (or `curl -sL` to follow) |
| Expand in Node | `await fetch(url)` — `resp.url` is the final target after redirects |
| Expand in Python | `requests.head(url, allow_redirects=True)` → `resp.url` |
| Create (API) | `POST https://meta.wikimedia.org/w/api.php?action=shortenurl&url=...&format=json` (auth required) |
| Create (UI) | `https://meta.wikimedia.org/wiki/Special:UrlShortener` |
| QR code | `https://meta.wikimedia.org/wiki/Special:QrCode?url=<encoded>` |
| Manage short URLs | `https://meta.wikimedia.org/wiki/Special:ManageShortUrls` |

## Verified Facts (2026-08-12)

- `https://w.wiki/TR9R` → **301** → `https://commons.wikimedia.org/wiki/Commons:WikiPortraits/Bento-demo.json`.
- The 301 response carries `access-control-allow-origin: *`, but the **target
  page sends no CORS headers** — see Gotcha 2 for why browser-side expansion
  fails.
- **No API on w.wiki itself**: `https://w.wiki/api.php?...` is treated as a
  *short code* and returns an HTML "Wikimedia Error / Short URL Not Found"
  page. The `action=shortenurl` API module lives on **meta.wikimedia.org**
  (verified via `action=paraminfo&modules=shortenurl`), not w.wiki.
- `shortenurl` params: `url` (required, string), `qrcode` (boolean).
- Rate limits (per meta.wikimedia.org/wiki/Wikimedia_URL_Shortener):
  **10 creations / 2 minutes** for IPs, **50 / 2 minutes** for logged-in users.
- `Special:UrlShortener` (HTTP 200) and `Special:QrCode?url=...` (HTTP 302 →
  QR PNG) both exist on meta.

## Gotchas (don't rediscover these)

1. **There is no way to "look up" a w.wiki code without following the
   redirect.** No expansion endpoint exists — not on w.wiki, not in the API.
   The extension docs mention `action=shortenurl` (creation only). Expand by
   following the redirect and reading the final URL.

2. **Browsers cannot expand w.wiki links to wiki pages.** `fetch('https://w.wiki/CODE')`
   in a browser fails with `TypeError: Failed to fetch`: the browser follows
   the 301 (whose own response is CORS-permitted), then the target page
   (e.g. `commons.wikimedia.org`) sends **no CORS headers**, so the final
   response is blocked. `redirect: 'manual'` gives an opaque response with no
   readable `Location` header. **Fix:** expand server-side (curl / Node /
   Python), or add a same-origin resolver endpoint to your own server that
   follows the redirect and returns the final URL as JSON (see
   `deploy/server.js` `/api/resolve` in the WikiBento project for a working
   Node 20 zero-dependency implementation).

3. **w.wiki is not a MediaWiki API surface.** Anything under `w.wiki/` is
   interpreted as a short code — `api.php`, `w/`, etc. all 404 with "Short URL
   Not Found". Route API calls to meta.wikimedia.org instead.

4. **Creating short URLs requires authentication** (edit rights on Meta-Wiki)
   and the action is a write op: use POST with a CSRF token (see
   [wikimedia-auth-oauth](../wikimedia-auth-oauth/SKILL.md)). Anonymous POST
   returns a generic Wikimedia Error page, not JSON.

5. **Rate limits are per-user/IP and low** (10/2 min anon). For bulk
   shortening, batch is not a thing here — pace requests or use the UI.

## SOP 1: Expand a w.wiki Short URL

### curl (read the Location header — no body fetched)

```bash
curl -sI "https://w.wiki/TR9R" | grep -i '^location:'
# location: https://commons.wikimedia.org/wiki/Commons:WikiPortraits/Bento-demo.json
```

### Node (browser-unavailable; server-side only)

```javascript
const resp = await fetch('https://w.wiki/TR9R', { redirect: 'follow' });
console.log(resp.url); // final URL after redirects
```

### Python

```python
import requests
resp = requests.head('https://w.wiki/TR9R', allow_redirects=True, timeout=15)
print(resp.url)  # final URL after redirects
```

### Browser (the CORS trap — needs a server-side helper)

A browser `fetch()` cannot read the target (Gotcha 2). Pattern that works:
your own server exposes `GET /api/resolve?url=<https-url>`, follows the
redirect server-side, and returns `{"url": "<final>"}`; the client then
fetches the target through a CORS-enabled path (e.g. the MediaWiki Action
API `action=parse&prop=wikitext&origin=*` for wiki pages). See the WikiBento
`src/lib/share.js` + `deploy/server.js` for a tested reference implementation.

## SOP 2: Create a Short URL (API)

Requires a logged-in session with edit rights on meta.wikimedia.org.

```bash
# 1. Get a CSRF token
TOKEN=$(curl -s "https://meta.wikimedia.org/w/api.php?action=query&meta=tokens&type=csrf&format=json" \
  -b cookies.txt -A "$WIKIMEDIA_USER_AGENT" | python3 -c "import json,sys; print(json.load(sys.stdin)['query']['tokens']['csrftoken'])")

# 2. Shorten
curl -s -X POST "https://meta.wikimedia.org/w/api.php?action=shortenurl&format=json" \
  -b cookies.txt -A "$WIKIMEDIA_USER_AGENT" \
  --data-urlencode "url=https://commons.wikimedia.org/wiki/Commons:WikiPortraits/Bento-demo.json" \
  --data-urlencode "token=$TOKEN"
# → { "shortenurl": { "shorturl": "https://w.wiki/XXXX", ... } }
```

Pass `qrcode=1` to also get QR code data in the response.

## Use Cases

- **Shareable dashboard configs**: `https://wikibento.toolforge.org/?config=https://w.wiki/TR9R`
  — short, phone-friendly URLs that survive QR scanning (WikiBento verified
  this end-to-end 2026-08-12).
- **QR codes for demos/GLAM events**: `Special:QrCode?url=...` gives a PNG
  without any API call.
- **Link shorteners in templates/messages** where full URLs bloat wikitext.
