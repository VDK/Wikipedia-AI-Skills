---
name: flickr-wayback-recovery
description: Recover a deleted or offline Flickr account from the Wayback Machine (CDX enumeration, metadata scraping, image download) and batch-upload the photos that are missing from Wikimedia Commons via pattypan
license: MIT
compatibility: opencode
depends_on: [flickr, pattypan, wikimedia-commons, wikimedia-api-access]
skill_discovery_hints:
  - keywords: ["Wayback Machine", "CDX", "deleted Flickr", "Flickr account gone", "404 photo page", "archived photos"]
  - keywords: ["Flickr rescue", "account recovery", "Internetstiftelsen", "Internetdagarna", "photo ID"]
  - keywords: ["batch upload", "pattypan", "Commons upload", "missing photos", "GLAM recovery"]
last_verified: 2026-08-08
---

> **Derived from the production Internetstiftelsen rescue (2026)** — a deleted
> Flickr account (`44783532@N07` / alias `stiftelsen`, ~1,100 archived photos)
> was recovered from the Wayback Machine and 675 of its photos were re-uploaded
> to Commons in one pattypan batch. The pipeline, the CDX queries, the
> `modelExport` parser, the manifest schema, and every guardrail below are what
> that run actually used. A condensed worked example lives in
> `references/internetstiftelsen-case-study.md`.

When a Flickr account is deleted (or made private), every photo page and the
`flickr.com/photos/<nsid>/` people page return 404, but the **Wayback Machine
usually still holds archived copies of the photo pages and their images**. This
skill turns those archives into a clean pattypan upload of the photos that are
**not yet on Commons** — matched by Flickr ID, never by filename.

## When to use this skill

- "This Flickr account disappeared — can we recover the photos?"
- "Flickr account X is deleted; upload the photos that aren't on Commons yet"
- Any task that mentions the Wayback CDX API, archived Flickr pages, or
  "rescue" of a deleted GLAM/institutional Flickr account (e.g. Internetstiftelsen).

Use this skill **instead of** [flickr](../flickr/SKILL.md) when the live Flickr
API has nothing to offer (the account is gone, so `flickr.people.findByUsername`
404s). Use [flickr](../flickr/SKILL.md) when the account is still live.

## Pipeline at a glance

1. **Enumerate** every archived photo ID via the CDX API (both URL forms).
2. **Dedupe against Commons** — skip photos already uploaded (match by Flickr ID).
3. **Scrape** per-photo metadata from archived photo pages (title, description,
   date, license, tags, owner).
4. **Download** the best archived image per photo.
5. **Build** a pattypan manifest (13 columns, Commons-safe wikitext).
6. **Validate** the manifest, then upload with pattypan.

---

## SOP: 1 — Enumerate photo IDs via the Wayback CDX API

### CDX basics (memorize)

The CDX API returns a capture listing as JSON:

```
https://web.archive.org/cdx/search/cdx?url=<url-pattern>&output=json&fl=timestamp,original,statuscode,digest&filter=statuscode:200&collapse=digest
```

- `url` is a **glob pattern** — the account uses `.../photos/<nsid>/*` and the
  alias form `.../photos/<username>/*`.
- `fl=` selects columns; always request `timestamp,original,statuscode,digest`.
- `collapse=digest` dedupes captures of the same page content; `filter=statuscode:200`
  drops error/redirect captures.
- Response is `[["timestamp","original","statuscode","digest"], [...row...], ...]`.
- A raw replayed page is `https://web.archive.org/web/<timestamp>/<original>` ;
  append `id_` right after the timestamp to get the **raw** response
  (`/web/<ts>id_/<url>`), which is what you want for images and HTML you parse.

### Query both URL forms

The CDX holds captures under **two** URL shapes — the NSID
(`flickr.com/photos/44783532@N07/<id>/`) and the username alias
(`flickr.com/photos/stiftelsen/<id>/`). Query **both** and union the photo IDs;
one form is often missing captures the other has.

### The trailing-slash pitfall

The first extraction regex required a trailing slash (`/photos/<account>/(\d+)/`)
and silently dropped **209 IDs** whose only captures use the NSID form without
the trailing slash. Use a regex that tolerates the optional trailing slash and
the `in/<pool>` suffix:

```python
PHOTO_RE = re.compile(
    r"/photos/(?:44783532@N07|stiftelsen)/(\d+)/?"
    r"(?:in/(?:photostream|set-[\w]+|album-[\w]+|pool-[\w]+))?/?$"
)
```

### Etiquette

The CDX API is not rate-limited formally but can be slow or flaky. Use one
`requests.Session()` / `urllib` opener, send a descriptive `User-Agent`, sleep
~1 s between calls, and retry on timeout/connection errors with backoff. Save
the full CDX result to disk (`wayback_full.json`) so later steps don't re-query.

```python
import json, re, time, urllib.parse, urllib.request

CDX = "https://web.archive.org/cdx/search/cdx"
def cdx_rows(account_url):
    qs = urllib.parse.urlencode({
        "url": account_url, "output": "json", "fl": "timestamp,original,statuscode,digest",
        "filter": "statuscode:200", "collapse": "digest",
    })
    req = urllib.request.Request(f"{CDX}?{qs}", headers={"User-Agent": UA})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                rows = json.load(r)
            return [dict(zip(rows[0], row)) for row in rows[1:]]
        except Exception:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("CDX query failed")

rows = []
for form in ("https://www.flickr.com/photos/44783532@N07/*",
             "https://www.flickr.com/photos/stiftelsen/*"):
    rows += cdx_rows(form)
    time.sleep(1)

photo_ids = sorted({int(m.group(1)) for r in rows
                    if (m := PHOTO_RE.search(r["original"]))})
```

---

## SOP: 2 — Find which photos are already on Commons

Match by **Flickr ID**, not by Commons filename — uploaders rename files freely.
An ID can appear in a Commons file's **title** (`Name (12345678901).jpg`),
**wikitext** (`|Source = [https://www.flickr.com/photos/<nsid>/<id>/ ...]`), or
**Structured Data** (P973/P7482 URL claims). Check all three:

1. **Full-text/insource search** for the ID: `Special:Search insource:"<id>"` or
   the Action API `list=search` with `srsearch="<id>"` on commons.wikimedia.org.
2. **Wikitext scan** of the candidate files: `prop=revisions&rvprop=content`
   (50 titles per request), regex for `flickr\.com/.../(\d{5,})`.
3. **SDC scan**: `action=wbgetentities&sites=commonswiki&titles=...` and read
   P973/P7482 URL claims for `flickr.com`.

Aggregate into `commons_flickr_ids.txt` (one ID per line). The rescue run found
**399** already-present IDs this way. Use the User-Agent/rate-limit rules from
[wikimedia-api-access](../wikimedia-api-access/SKILL.md) — this is a Wikimedia API.

---

## SOP: 3 — Scrape metadata from archived photo pages

### The `modelExport` JSON blob

An archived Flickr photo page embeds a serialized JSON blob inside a
`<script class="modelExport">` tag. The real blob is the **first** occurrence of
`modelExport:` **after that script tag** (the token also appears in JS
comments). Flickr uses a "cyclical JSON" format: `data["main"]` contains
`photo-models`, `person-models`, `photo-stats-models`, `photo-head-meta-models`,
and strings like `"~3"` reference `data["legend"]` entries. Resolve the `~N`
references before reading fields.

```python
def extract_model(html):
    idx = html.find('<script class="modelExport"')
    if idx == -1:
        return None
    m = re.search(r"modelExport:\s*(\{)", html[idx:])
    if not m:
        return None
    start = m.start(1)
    depth = 0
    in_str = esc = False
    for i in range(start, len(html[idx:])):
        c = html[idx:][i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(html[idx:][start:i + 1])
    return None
```

`assets/inspect_model.py` implements the full extraction + `~N` resolution; the
`fetch-photo-metadata.py` script uses it.

### Fields to pull (photo-models[0] + stats + head-meta + person-models)

| Field | Where | Notes |
|---|---|---|
| title | `photo-models[0].title` | percent-encoded, latin-1 bytes — decode |
| description | `photo-models[0].description` | same decoding |
| license | `photo-models[0].license` | Flickr license **id** (2=NC, 4=CC-BY-2.0, 5=CC-BY-SA-2.0) |
| dateTaken | `photo-stats-models[0].dateTaken` | string; fall back to `datePosted` |
| tags | `photo-head-meta-models[0].keywords` | comma-separated, same decoding |
| owner | `person-models[0]` | nsid, pathAlias, username, realname |
| sizes | `photo-models[0].sizes` | dict of size key → `{url, ...}` |

### The percent-encoding quirk (mojibake)

Flickr percent-encodes metadata with **latin-1 bytes** (`%E4` = `ä`), so decode
with `urllib.parse.unquote_to_bytes(s).decode("latin-1")`, **not** the default
UTF-8. Archives also store pre-encoded mojibake (`ã¶` for `ö`) in some places —
normalize with `unicodedata.normalize("NFKC", ...)` where you see it.

Some captures are photo-page shells with **no photo model** (the page was
archived but the content blob wasn't), and some photo IDs have **no capture at
all**. Record both cases (`error: "no model"` / `error: "no capture"`) and carry
on — they are excluded from the manifest, not fatal.

---

## SOP: 4 — Download the images

Try, in order:

1. **The archived original size**: from `sizes["o"]` (fall back `k, h, l, c, z`),
   rewrite the URL as `https://web.archive.org/web/<page_ts>id_/<original_url>`
   and fetch. The `id_` modifier returns the **raw bytes**, not an HTML wrapper.
2. **The archived staticflickr URL**: many captures point at
   `c1.staticflickr.com/.../<id>_<secret>[_o].jpg`; fetch those directly through
   `/web/<ts>id_/...`.
3. **Sizes in the page itself**: some archived pages embed `//web.archive.org/
   web/<ts>/<img-url>` URLs in `sizes` — parse and fetch the largest suffix.

Validate every download with magic bytes — Wayback sometimes returns an HTML
error page with HTTP 200:

```python
def looks_like_image(blob):
    for magic, ext in [(b"\xff\xd8\xff", "jpg"), (b"\x89PNG\r\n\x1a\n", "png"),
                       (b"GIF87a", "gif"), (b"GIF89a", "gif")]:
        if blob.startswith(magic):
            return ext
    return None
```

Save as `images/<id>.<ext>`, record byte counts and the URL in an `images.json`
state file so a rerun skips what already downloaded. Throttle (~1 s), retry with
backoff on 429/503/timeout, and re-check files whose size on disk differs from
the recorded byte count.

---

## SOP: 5 — Build the pattypan manifest

The manifest is the 13-column CSV that
[pattypan](../pattypan/SKILL.md)'s `build_pattypan_spreadsheet.py` turns into
the `.xls`:

```
path,name,description,date,source,archive_ts,photo_id,author,photographer,categories,license,title,other_fields
```

`path` is the **absolute** local path to `images/<id>.<ext>` (keep the `.xls`
next to the images so the paths resolve). The template's 13 variables map 1:1
onto these columns.

### Filenames — the Flickr ID is sacred

`<normalized title> - <Event> (<flickr id>).jpg`. Normalize the Flickr title:
strip event-year abbreviations (`IDD12-`, `IDD13-`), drop redundant trailing
event words, and append a `- <Event> <year>` disambiguator when the bare title
doesn't identify the event. **The `(<flickr id>)` suffix is what Commons
search/category work uses later — never lose it.**

### Camera-garbage titles

Titles that are just camera filenames (`IMG_2184`, `ind12_.SE_9888`,
`11042013-dsc_3685`, `_W6A8157.jpg`) carry no information. Replace them with a
**sequential per-year counter** after the account name, one counter per year:

`Swedish Internet Foundation 2012 (001)` … — and keep the numbering **contiguous
across the rows that actually survive pruning** (see the exclusion list below).

### Descriptions

- Wrap the Flickr description in its detected language:
  `{{sv|1=...}}` / `{{en|1=...}}`. Strip embedded credit lines
  (`Fotograf:` / `Photo:` / `CC-BY ...`) — the credit belongs in the author field.
- **Never use the Flickr title as the description.**
- Add a one-line language-tagged **event placeholder** in the same style
  (`{{sv|1=Internetdagarna. Årlig konferens ...}}`). Omit it when the real
  description is already in that language (never two blocks in one language).
- Drop descriptions that only repeat the event name (`Webbstjärnan 2018`).
- Short tag-like fragments (`Arthackday 2013, sponsor .SE`) → move to the Flickr
  tags (`other_fields`) and fall back to the placeholder; the event they name
  still drives the categories.

### Categories

The template always adds the account category
`[[Category:Photographs by the Swedish Internet Foundation]]`. Add per photo:
event category (`Internetdagarna 2012`), year category, **person categories for
the photographed people/speakers — not the photographers** (red/nonexistent
person categories are acceptable and get created by a bot later). Photographer
categories (`Photographs by <Photographer>`) come from the photographer column,
separately.

### License

Keep the Flickr license **id** in the manifest; the template translates it:
`4 → {{cc-by-2.0}}`, `5 → {{cc-by-sa-2.0}}`. **Skip license `2` (CC BY-NC-2.0)**
— not acceptable on Commons. Do not invent a license.

### Author / credit

Credit the **account**. If the Flickr people page is not archived (common — the
404 hit it too), a link to `flickr.com/people/<nsid>/` is dead: use the plain
username `Stiftelsen` instead of `[https://www.flickr.com/people/<nsid>/ ...]`.
Keep `{{Flickrreview}}` below the license template.

### Tags → `other_fields`

`{{Information field|name=Flickr tags|value=se, hack, musik, ...}}` (repair the
latin-1 mojibake first).

### Exclusion list for pruned photos

Keep a `skip_photos.txt` (one Flickr ID per line) for photos the user has
decided to drop (irrelevant, derivative work, duplicate). The build **skips any
ID in that list even if a local file or archived URL exists** — a plain "no file
on disk" check is not enough, because the archived URL would silently keep the
row in the manifest.

---

## SOP: 6 — Validate and upload with pattypan

Run the validation from `scripts/validate-manifest.py` and the pattypan build:

```bash
python3 .claude/skills/pattypan/scripts/build_pattypan_spreadsheet.py \
    --manifest manifest.csv --template template.wikitext --output pattypan-upload.xls
```

Non-negotiable checks (0 errors, warnings advisory):

- filename illegal characters (`#<>[]|{}/`) and trailing dots/whitespace;
- filename byte-length ≤ 240 (MediaWiki hard limit);
- no empty `description`, `date`, or `archive_ts`;
- no `path` that still points at a URL (every row must have a local file);
- every `path` file exists and is a valid image;
- no row references a `skip_photos.txt` ID.

Then open the `.xls` in pattypan, confirm "**N files loaded, 0 errors**",
spot-check a few rendered descriptions, and upload.

---

## Guardrails

1. **Match by Flickr ID everywhere** — Commons filenames, titles, and SDC claims
   are renamed by uploaders; the `(<id>)` in the title and the ID in `source`/SDC
   are the only reliable join keys.
2. **Query both CDX URL forms** (NSID + alias) and make the photo-ID regex
   tolerate the missing trailing slash, or you silently drop IDs.
3. **Skip CC BY-NC (license 2)**; never fake a license. Only the free set
   (4, 5, 7, 8, 9, 10, 11, 12) can go to Commons.
4. **A missing local file is not "excluded"** if `images.json` still holds an
   archived URL — the URL keeps the row alive. Use an explicit `skip_photos.txt`.
5. **Wayback returns HTML error pages with HTTP 200** — always validate image
   downloads by magic bytes, never trust status code or extension.
6. **Throttle and resume**: sleep ~1 s between Wayback/Commons calls, retry with
   backoff, and make every stage resumable from its on-disk state
   (`metadata.json`, `images.json`, cached `pages/`).
7. **Never use the Flickr title as a description**; strip credits; one language
   block per language.
8. **Person categories describe the photographed people, not the photographers.**
   Red/nonexistent person categories are fine — they get created on upload.
9. **No dead people-page links** — if `flickr.com/people/<nsid>/` isn't
   archived, credit the account by plain username.
10. **Commons API calls need a proper User-Agent** and polite rate limits
    (see [wikimedia-api-access](../wikimedia-api-access/SKILL.md)).

## Tooling

- `scripts/cdx-photo-ids.py` — CDX enumeration (both URL forms, dedupe, save `wayback_full.json` + `wayback_photo_ids.txt`).
- `scripts/check-commons.py` — find which Flickr IDs already exist on Commons (title + wikitext + SDC) → `commons_flickr_ids.txt`.
- `scripts/fetch-photo-metadata.py` — fetch archived photo pages, parse the `modelExport` blob → `rescue_out/metadata.json` (+ cached pages).
- `scripts/download-images.py` — download the best archived image per photo → `images/<id>.<ext>` + `images.json`.
- `scripts/build-manifest.py` — build the 13-column manifest from metadata + images + `skip_photos.txt` → `manifest.csv`.
- `scripts/validate-manifest.py` — the non-negotiable checks above.
- `assets/inspect_model.py` — `modelExport` extractor + `~N` resolver (imported by fetch/download scripts).
- `references/wayback-cdx-notes.md` — CDX parameter reference and pitfalls.
- `references/internetstiftelsen-case-study.md` — the production run: numbers, failures, lessons.
