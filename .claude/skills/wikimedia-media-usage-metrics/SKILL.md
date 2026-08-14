---
name: wikimedia-media-usage-metrics
description: Measure and count the use of Wikimedia media files — transfers (mediacounts/mediarequests), embeds (GlobalUsage), reach (pageviews/CIM), external reuse — with verified gotchas, a decision tree, and a live report pipeline
license: MIT
compatibility: opencode
depends_on: [wikimedia-api-access, wikimedia-database, wikimedia-pageviews, wikimedia-commons, wikimedia-commons-sparql]
skill_discovery_hints:
  - keywords: ["media usage", "file usage", "image usage", "media reach", "file reach", "media metrics", "usage analytics"]
  - keywords: ["mediacounts", "mediarequests", "GlobalUsage", "globalimagelinks", "imagelinks", "file transfer counts", "image serve counts"]
  - keywords: ["how many times was image served", "where is file used", "pageviews of articles using image", "GLAM impact", "GLAM metrics"]
  - keywords: ["BaGLAMa", "GLAMorgan", "GLAMorous", "external reuse", "hotlink", "referer", "media transfer counts"]
last_verified: 2026-08-14
---

# Media Usage Metrics — Measuring Use of Wikimedia Files

> ⚠️ **User-Agent required** on every HTTP call below. See **[wikimedia-api-access](../wikimedia-api-access/SKILL.md)**.
> A layperson-facing version of this material lives at `references/layperson-guide.md` (send to non-Wikimedia audiences).

## 1. The four meanings of "use" (read this first)

People mean four different things by "use of a media file". Mixing them is the #1 source of wrong numbers.

| Axis | Question | Primary signal | Key caveat |
|---|---|---|---|
| **Transfers** | How many times were the file's bytes *served*? | `mediacounts` / `mediarequests` | Counts requests, not humans; thumbnails count |
| **Usage (embeds)** | *Where* is the file transcluded? | `GlobalUsage` / `imagelinks` | Tells *where*, never *how often* |
| **Reach** | How many people *viewed pages* containing it? | pageviews / CIM | Page loads ≠ image loads |
| **External reuse** | Is it hotlinked *off-Wikimedia*? | `mediacounts` referer fields | The **only** source that sees off-wiki use |

## 2. Master index

| # | Method | Measures | Pre-computed / on-demand | Access |
|---|---|---|---|---|
| 1 | Mediacounts (dumps + Hive `wmf.mediacounts`) | Transfers, bytes, referer split | Pre (daily) | Public dumps / cluster |
| 2 | Mediarequests AQS | Transfers per-file/top | On-demand API (pre-aggregated) | Public REST |
| 3 | Raw `webrequest` (Data Lake) | Anything, custom | On-demand compute | WMF cluster creds |
| 4 | GlobalUsage (API + `globalimagelinks`) | Cross-wiki embeds | Maintained table, on-demand query | Public API / SQL |
| 5 | `imagelinks` (SQL) | Local embeds per wiki | On-demand SQL | Toolforge replicas |
| 6 | `imageusage` (Action API) | Local embeds | On-demand API | Public |
| 7 | GLAMorous / PetScan | Embeds by category, filtered | On-demand tools | Public web tools |
| 8 | Pageviews API | Reach (File page + embeds) | On-demand API (pre-aggregated) | Public REST |
| 9 | Commons Impact Metrics / AQS | Reach, leverage, edits (GLAM) | Pre (monthly) | Public API + dumps |
| 10 | BaGLAMa 2 / GLAMorgan | Legacy GLAM reach | Pre (cron) / on-demand | Public tools |
| 11 | Mediacounts referer fields | External/off-wiki reuse | Pre | Dumps / cluster |
| 12 | SDC SPARQL (WCQS/QLever) | Discovery (depicts, etc.) | On-demand | Public / OAuth |
| 13 | EventStreams | Real-time usage *changes* | Real-time push | Public SSE |

## 3. Method deep-dive (endpoints + gotchas)

### 3.1 Mediacounts — dumps + Hive `wmf.mediacounts`
Daily TSV, one row per file. Columns: `total`, `original`, `transcoded_image` (width buckets 0-199 … 1000+), `transcoded_audio`, `transcoded_movie` (height buckets), `total_response_size`, `referer_internal/external/unknown`.
- **Caveats:** HTTP 304s NOT counted; MediaViewer prefetch inflates image counts up to ~50%; stream "jump back to start" double-counts; no bot filtering (status-code based only); not per-wiki.
- **Access:** `https://dumps.wikimedia.org/other/mediacounts/daily/` (TSV); Hive table `wmf.mediacounts` (hourly Parquet) for cluster users.
- **Ideal:** bulk/historical GLAM reporting, bandwidth/byte-volume analysis, offline batch, referer attribution.

### 3.2 Mediarequests AQS — `metrics/mediarequests/*`
Endpoints (all verified 2026-08-14): `aggregate/{referer}/{media_type}/{agent_type}/{granularity}/{start}/{end}`, `top/{referer}/{media_type}/{year}/{month}/{day}`, `per-file/{referer}/{agent_type}/{file_path}/{granularity}/{start}/{end}`.
- `referer` ∈ all-referers/internal/external/unknown; `media_type` ∈ image/audio/video/all-media-types; `agent_type` ∈ user/spider/automated/all-agents; `granularity` ∈ daily/monthly. Data since 2015.
- **GOTCHA (verified):** `per-file` `file_path` MUST be the upload path URL-encoded **with the leading slash** — e.g. `/wikipedia/commons/0/00/Crab_Nebula.jpg` → `%2Fwikipedia%2Fcommons%2F0%2F00%2FCrab_Nebula.jpg`. Omitting the leading slash returns 404.
- Inherits mediacounts caveats; filters self-identified bots but not automated traffic; cannot break down per wiki page.
- **Ideal:** quick per-file request counts, top-media leaderboards.

### 3.3 Raw `webrequest` (Data Lake)
Source of #1/#2. Hive/Spark/Presto over `wmf.webrequest`. Needs WMF analytics cluster + Kerberos. Full control (status, referer, wiki, UA, geo=private, hourly), dedupe prefetch, custom bot filtering.

### 3.4 GlobalUsage — API + `globalimagelinks` table
Definitive cross-wiki "where used".
- **API (verified):** `action=query&prop=globalusage&titles=File:Name.jpg&format=json&guprop=namespace` → `{wiki, title, ns}` per using page. Paginates via `gucontinue` + `gulimit`.
- **GOTCHA (verified):** globalusage is its OWN prop — `prop=globalusage`, NOT `iiprop=globalusage` (returns "Unrecognized value"). `guprop=title` is also unrecognized (title is always returned); use `guprop=namespace` for the ns field.
- **SQL:** `commonswiki_p.globalimagelinks` (`gil_wiki`, `gil_page`, `gil_to`, `gil_page_namespace_id`) — bulk joins/aggregates ("files used in most wikis") in one query.
- **Ideal:** per-file usage maps, cross-wiki reach (distinct wiki/page counts), feeding pageview lookups.

### 3.5 `imagelinks` (per-wiki SQL) + 3.6 `imageusage` (Action API)
- `imagelinks`: `{db}_p.imagelinks` (`il_from`, `il_to`) — local usage incl. non-Commons images. Single-wiki only.
- `imageusage`: `list=imageusage&iutitle=File:…` — on-demand local usage, no SQL needed.

### 3.7 GLAMorous / PetScan
Community tools over GlobalUsage/imagelinks. GLAMorous = global usage per category; PetScan = category × usage × filter intersections. Slow at scale.

### 3.8 Pageviews API — `metrics/pageviews/*`
API reference and media-views (mediarequests) coverage live in the
**[wikimedia-pageviews](../wikimedia-pageviews/SKILL.md)** skill. Unique gotchas
verified for this workflow:
- **GOTCHA (verified):** File-page views ≈ interest in the file itself, NOT media views. Example: `File:Crab_Nebula.jpg` ≈ 4–12 File-page views/day vs **211,688** mediarequests/day (thumbnails embedded in articles).
- **GOTCHA (verified):** `per-article` returns **HTTP 404 for pages with no pageview data** (e.g. low-traffic user/talk pages) — the page still exists, it just has zero records in the window. Treat 404 as 0 views, not an error (the pipeline script does this).

### 3.9 Commons Impact Metrics / Commons Analytics AQS
Official GLAM "impact" product — full endpoint table, allow-list registration, and the
try-CIM-then-fallback pattern live in the **[wikimedia-commons](../wikimedia-commons/SKILL.md)**
skill. Caveats unique to usage-metrics workflows:
- **GOTCHA (verified):** unregistered category → HTTP 404 body "…not loaded yet" = the not-allow-listed signal (not an error).
- **GOTCHA (verified):** `category-metrics-snapshot` has **no pageviews field** — use `pageviews-per-category-monthly`.
- **Caveats:** allow-list only (~1,755 GLAM/campaign categories); monthly; max depth 7; no retroactive backfill; monthly drift (pageviews attributed from 1st even if file added mid-month); pageview-based (not mediarequests); category rename breaks pipeline until allow-list updated.
- **GOTCHA (verified):** unregistered category → HTTP 404 body "…not loaded yet" = the not-allow-listed signal (not an error). `category-metrics-snapshot` has **no pageviews field** — use `pageviews-per-category-monthly`.

### 3.10 BaGLAMa 2 / GLAMorgan / GLAM Wiki Dashboard
Legacy community GLAM tools (Magnus Manske) that CIM was built to replace. Prone to outages/inconsistency. `https://glamtools.toolforge.org/baglama2/`, `…/glamorgan.html`.

### 3.11 Mediacounts referer fields — the ONLY external-reuse signal
`referer_external` = transfers with a non-WMF referer (hotlinking/embedding on external sites, apps, AI crawlers). No other method sees off-wiki use.

### 3.12 SDC SPARQL (WCQS / QLever)
Discovery only, not counting — find files by `depicts`/license/camera, then feed into #2/#4/#8. WCQS (`commons-query.wikimedia.org`, OAuth) or QLever (`qlever.dev/wikimedia-commons`, no auth). See **[wikimedia-commons-sparql](../wikimedia-commons-sparql/SKILL.md)**.

### 3.13 EventStreams
Real-time file *usage changes* (page adds/removes file) via `stream.wikimedia.org`, not view counts.

## 4. Decision tree

```
Want "how many times was the file served?"
  → quick single file: mediarequests per-file
  → bulk/historical: mediacounts dumps
  → custom/bespoke: raw webrequest (cluster)
Want "where is it used, on which wikis?"
  → GlobalUsage API (single file) / globalimagelinks SQL (bulk)
Want "how many people saw it in articles?"
  → GlobalUsage → pageviews (arbitrary files)
  → CIM/Commons Analytics (GLAM + allow-listed categories)
Want "is it reused off-wiki?"
  → mediacounts referer_external
Want "GLAM institutional impact dashboard"
  → CIM / Commons Analytics API
Want "real-time usage changes"
  → EventStreams
```

## 5. The live-computation pipeline (arbitrary, non-allow-listed files)

Works for ANY file today, no allow-list. Implemented in `scripts/media_usage_report.py`.

1. **Resolve title → upload path** — `prop=imageinfo&iiprop=url` (Action API). ⚠️ GOTCHA (verified 2026-08-14): the returned `url` carries tracking params (`?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original`). **Strip everything from `?` onward** before using it as a storage path, or `mediarequests`/`mediacounts` lookups return 404 (the script does this).
2. **Where used** — `prop=globalusage` (paginate) → `[{wiki,title}]`; count distinct wikis/pages.
3. **Transfers** — `mediarequests/per-file` (encode path WITH leading slash).
4. **Reach** — batch `pageviews/per-article` over using pages; sum. Cap with `--max-pages` (default 50) and flag truncation. ⚠️ This is a *lower-bound sample* (first N using pages, not the most-viewed); exact reach needs pageviews for ALL using pages, or CIM when the file is allow-listed.
5. **File-page interest** — `pageviews/per-article` for the `File:` title.
6. Combine into one report.

## 6. Verification log (2026-08-14, all live-tested)

- mediarequests `top` + `aggregate` + `per-file` all return data; `per-file` leading-slash encoding confirmed.
- GlobalUsage via `prop=globalusage` confirmed; `iiprop=globalusage` and `guprop=title` both rejected.
- Commons Analytics `category-metrics-snapshot` returns real data (`Smithsonian_American_Art_Museum`: 10,614 files deep, 1,549 used, 176 wikis, 3,809 pages); `media-file-metrics-snapshot` on a non-allow-listed file → 404.
- Pageviews `per-article` on `File:Crab_Nebula.jpg` returns File-page views.
- `imageinfo&iiprop=url` appends `?utm_source=…&utm_campaign=imageinfo&utm_content=original` tracking params to the URL (verified) — must be stripped before reuse.
- Reach sample-bias magnitude (verified): same `--max-pages` cap → `File:Earth.jpg` reach **7,279** vs `File:Crab_Nebula.jpg` reach **279**, because Earth's first-50 using-pages are high-traffic articles while Crab Nebula's are low-traffic featured-picture galleries. Don't trust the DIY reach number without this context.

## 7. Cross-references

| Skill | Why |
|---|---|
| **[wikimedia-api-access](../wikimedia-api-access/SKILL.md)** | UA format, rate limits, endpoints |
| **[wikimedia-database](../wikimedia-database/SKILL.md)** | `globalimagelinks`/`imagelinks` SQL via Toolforge |
| **[wikimedia-pageviews](../wikimedia-pageviews/SKILL.md)** | pageviews API + `pageview_daily_average` sorting |
| **[wikimedia-commons](../wikimedia-commons/SKILL.md)** | Commons Analytics endpoint table + CIM allow-list process |
| **[wikimedia-commons-sparql](../wikimedia-commons-sparql/SKILL.md)** | SDC/SPARQL discovery (WCQS/QLever) |
