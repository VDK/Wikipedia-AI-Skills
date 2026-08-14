# Measuring the Use of Media Files on Wikimedia
### A practical guide for people who know metrics and SEO, but not the Wikimedia ecosystem

---

## Who this is for

You understand analytics concepts — page views, impressions, requests, referrer traffic, backlinks, CDN logs — but you've never dug into how Wikimedia (Wikipedia and its sister projects) works under the hood. This guide explains, in plain language, every practical way to answer the question:

> **"How much is our media actually being used?"**

You can share this document as-is; it assumes zero MediaWiki knowledge.

---

## TL;DR

"Use of a media file" is **four different questions**, and each has its own tool:

| You want to know… | The answer lives in | Analog for a marketer |
|---|---|---|
| How many times was the file **served**? | **mediacounts** / **mediarequests** | CDN request/impression counts |
| **Where** is the file embedded? | **GlobalUsage** / **imagelinks** | A link graph / backlink index |
| How many people **viewed pages** that include it? | **pageviews** / **Commons Impact Metrics** | "Views of pages containing our asset" |
| Is it reused **off-site**? | mediacounts **referrer fields** | Referrer / hotlink logs |

The single most common mistake is treating these as interchangeable. A photo can be *served* millions of times a day (as a thumbnail on a popular article) while its own detail page gets a handful of *views* — and neither number tells you where it's used.

---

## Background: why this is genuinely hard

**1. Wikimedia is one shared library, not one website.**
All of Wikipedia's ~330 language editions, plus Wiktionary, Wikidata, and dozens of other projects, draw their images, audio, and video from a single shared media library called **Wikimedia Commons**. So "is this file used?" means "is it used *anywhere across hundreds of independent sites*?"

**2. "A view" doesn't mean what it means on your website.**
When a Wikipedia page loads, the images in it are fetched as separate files. That fetch is a **transfer** (a server request for bytes), not a "page view." Wikimedia logs these two things separately, on different systems.

**3. Wikimedia deliberately doesn't track everything.**
Wikimedia is privacy-first. It does **not** run full web analytics with user-level tracking the way a commercial site does. What exists is either *server-side request logs* (counts of file downloads) or *page-view counts* (aggregated, privacy-safe). This is why some questions only have approximate answers.

**4. The data is split between "pre-computed" and "on-demand."**
Some numbers are pre-aggregated into downloadable datasets (fast, but fixed in shape and often monthly). Others require you to run a query or a small pipeline yourself (flexible, but you assemble the answer).

---

## A plain-English glossary

| Wikimedia term | What it means | Your-world equivalent |
|---|---|---|
| **Wikimedia Commons** | The shared, free media library that feeds all Wikimedia sites | A company-wide Digital Asset Manager (DAM) |
| **A "file"** | One image, audio clip, video, or document | An asset in your DAM |
| **File page** | The asset's own detail/description page | The asset's landing page |
| **Embed / transclude** | When an article *uses* a file by referencing it | An `<img>` tag / hotlink |
| **Transfer / request** | The server actually sending the file's bytes | A CDN request / impression |
| **Page view** | A human (or bot) loading a wiki page | A page view |
| **Reach** | Total page views of every page that embeds the file | "Views of pages containing our asset" |
| **Referrer** | The URL/site that pointed to the file | Referrer in your web logs |
| **GlobalUsage** | A continuously-updated index of every page, on every wiki, that embeds a given file | A live backlink index |
| **GLAM** | Galleries, Libraries, Archives, Museums (the institutions Wikimedia works with) | Institutional partners |

---

## The four meanings of "use," in detail

### Meaning 1 — Transfers: "how many times was it served?"
Counts the number of times the file's bytes were downloaded from Wikimedia's servers. This is the closest thing to "impressions" for a media asset. It includes every thumbnail size and every format conversion.

- **Mediacounts** — the raw daily dataset.
- **Mediarequests API** — the same data, queryable per-file on demand.

### Meaning 2 — Usage/embeds: "where is it used?"
Lists the actual articles/pages, across every wiki, that embed the file. It answers "who uses us," not "how often."

- **GlobalUsage** — the cross-site index.
- **imagelinks / imageusage** — the same idea, scoped to a single wiki.

### Meaning 3 — Reach: "how many people saw it in context?"
The sum of page views of every page that embeds the file. This is the headline "impact" number for most institutional reporting.

- **Pageviews API** — build this yourself from a GlobalUsage list.
- **Commons Impact Metrics** — pre-computed for approved GLAM collections.

### Meaning 4 — External reuse: "is it used off Wikimedia?"
Whether the file is hotlinked/embedded by non-Wikimedia sites (news outlets, blogs, apps). Only one source sees this.

- **Mediacounts referrer fields.**

---

## The full toolbox

| Tool | What it measures | Pre-computed or on-demand? | How you access it |
|---|---|---|---|
| **Mediacounts** | Transfers, bytes, referrer split | Pre-computed (daily) | Downloadable datasets |
| **Mediarequests API** | Transfers per file / top files | On-demand API | Free public REST API |
| **Raw request logs (Data Lake)** | Anything, custom | On-demand compute | Internal staff only |
| **GlobalUsage** | Cross-wiki embeds | Live index, queried on demand | Free public API |
| **imagelinks** | Embeds on one wiki | On-demand query | Technical (database) |
| **imageusage** | Embeds on one wiki | On-demand API | Free public API |
| **GLAMorous / PetScan** | Embeds by collection, filtered | On-demand web tools | Free web tools |
| **Pageviews API** | Reach (page views) | On-demand API | Free public REST API |
| **Commons Impact Metrics** | Reach, embeds, editor activity | Pre-computed (monthly) | Free API + datasets |
| **BaGLAMa 2 / GLAMorgan** | Legacy "reach" reporting | Pre-computed / on-demand | Free web tools |
| **Mediacounts referrer fields** | Off-site reuse | Pre-computed | Downloadable datasets |
| **Structured-data search (SPARQL)** | Discovery ("find our files") | On-demand | Free / login |
| **EventStreams** | Real-time usage *changes* | Real-time stream | Free |

---

## Each tool, in plain English

### 1. Mediacounts (the raw daily dataset)
Every day, Wikimedia publishes a file that lists, for **every single media file**, how many times it was served. Crucially, it breaks this down: the original full-size file vs. thumbnails (in several size bands) vs. audio/video conversions, plus total bytes sent, plus a **referrer split** (came from a Wikimedia site, an external site, or unknown).

- ✅ **Pros:** Complete history back to 2015; whole dataset downloadable; the only source with byte-volume and referrer data; no rate limits.
- ❌ **Cons:** Huge files (you download and process them yourself); no built-in "just give me one file" interface.
- ⚠️ **Caveats:** It counts *requests*, not *people* — some browsers/media players cause over-counting (see "Caveats that matter" below).
- 🎯 **Best for:** Bulk or historical reporting across a whole collection; bandwidth analysis; measuring off-site reuse.

### 2. Mediarequests API (transfers, on demand)
The same underlying data as Mediacounts, but exposed as a simple web API. Ask for one file, or a leaderboard of the most-requested files, filtered by image/audio/video and by referrer type.

- ✅ **Pros:** Free, no login, instant per-file answers, top-N leaderboards.
- ❌ **Cons:** Same over-counting caveats as Mediacounts; can't tell you *which article* the request came from.
- 🎯 **Best for:** "How many times was this specific file served last month?" or "What are our most-downloaded files?"

### 3. Raw request logs (Data Lake)
The underlying log table everything above is built from. Full control — filter by referrer, wiki, user-agent, even (internally) geography.

- ✅ **Pros:** Maximum flexibility; you can build a *better* metric, dedupe over-counting, apply your own bot-filtering.
- ❌ **Cons:** Internal-only; requires engineering access.
- 🎯 **Best for:** Bespoke research, or prototyping an improved measurement methodology.

### 4. GlobalUsage (where it's used, everywhere)
A live index maintained by Wikimedia that records, for every file, every page on every wiki that embeds it. Ask it "where is File X used?" and get back a list of wikis and article titles.

- ✅ **Pros:** The definitive "where used" answer; always current; fast; free.
- ❌ **Cons:** Tells you *where* — never *how often* viewed.
- 🎯 **Best for:** Cross-site usage maps; counting how many distinct wikis/pages use a file (a "reach" metric in its own right); the first step of a reach calculation.

### 5. imagelinks / 6. imageusage (where it's used, one site)
The same "where is it used" idea, but scoped to a single wiki (e.g., only English Wikipedia). `imagelinks` is the database table; `imageusage` is the simple API.

- 🎯 **Best for:** Single-site analysis, or finding files nobody uses ("orphaned" assets).

### 7. GLAMorous / PetScan (usage, by collection)
Free community web tools. GLAMorous: "given a collection (category) of our files, where are they all used?" PetScan: multi-filter searches ("our files used in science articles on German Wikipedia").

- ⚠️ **Caveats:** Community-maintained; can be slow on huge collections.
- 🎯 **Best for:** Ad-hoc "what uses our collection" reports.

### 8. Pageviews API (reach, build it yourself)
Wikimedia's standard page-view service. Two uses for media:
1. Views of the **file's own page** (interest in the asset itself).
2. **Reach** — sum the page views of every page that embeds the file.

- ✅ **Pros:** Free, no login, precise, historical daily data.
- ❌ **Cons:** Reach requires a two-step process (get the usage list from GlobalUsage, then look up views per page).
- ⚠️ **Caveats:** Page views ≠ file transfers. A file's own page can get a handful of views while the file is served millions of times as a thumbnail on a top article.
- 🎯 **Best for:** "How many people actually read articles containing our image?"

### 9. Commons Impact Metrics (the official, pre-computed "impact" report)
Wikimedia's official product, purpose-built to answer "what's the impact of our (institution's) media?" It pre-computes, monthly, per-file and per-collection: how many files, how many are actually used, on how many wikis and pages, how many page views they collectively drive, and editor activity.

- ✅ **Pros:** Official, robust, standardized, exact even at massive scale, easy API, per-file and per-collection breakdowns, "shallow vs. deep" collection scoping.
- ❌ **Cons:** **Only covers approved collections** (a curated allow-list of ~1,755 GLAM/campaign categories — you must request to be added); **monthly only**; **no backfill** for newly added collections; a known **"monthly drift"** over-counts page views in the month a file is first added to an article; based on page views (not transfers); renaming a collection breaks it until re-approved.
- 🎯 **Best for:** Institutional dashboards and official GLAM "impact" reporting — when your collection is on the allow-list.

### 10. BaGLAMa 2 / GLAMorgan (legacy)
Older community-built GLAM reporting tools. They pioneered "reach" measurement but became unreliable and inconsistent, which is *why* Wikimedia built Commons Impact Metrics to replace them.

- ⚠️ **Caveats:** Prone to outages and inconsistencies.
- 🎯 **Best for:** Legacy continuity while you migrate to Commons Impact Metrics.

### 11. Mediacounts referrer fields (off-site reuse — the sleeper metric)
This deserves its own entry. Mediacounts records, per file, how many transfers came from **external** (non-Wikimedia) sites vs. **internal** ones. **This is the only signal in the entire ecosystem that captures reuse outside Wikimedia** — a news site hotlinking your photo, a blog embedding it, an app pulling it. Every other tool only sees on-wiki usage.

- 🎯 **Best for:** "Are people using our media beyond Wikipedia?" — a question no other tool can answer.

### 12. Structured-data search / SPARQL
Not a usage counter — a *discovery* tool. Wikimedia's media can be tagged with structured facts (what it depicts, license, camera). SPARQL lets you find files by those tags.

- 🎯 **Best for:** "Find all our files depicting X," then feed that list into the transfer/reach tools above.

### 13. EventStreams
A real-time feed of wiki *events*. For media, it can tell you the moment a page adds or removes a file — but not how many times the file is viewed.

- 🎯 **Best for:** Live dashboards ("who just used our file?").

---

## How to choose (decision tree)

```
How many times was it served?
  ├─ one file, quick answer → Mediarequests API
  ├─ bulk / historical      → Mediacounts datasets
  └─ custom / bespoke       → Raw request logs (internal)

Where is it used?
  ├─ across all sites       → GlobalUsage
  └─ on one site            → imagelinks / imageusage

How many people saw it in context?
  ├─ any file, DIY          → GlobalUsage → Pageviews API
  └─ approved GLAM collection → Commons Impact Metrics

Is it reused off-site?      → Mediacounts referrer fields
Official GLAM dashboard?    → Commons Impact Metrics
Real-time usage changes?    → EventStreams
Find files by subject?      → Structured-data search (SPARQL)
```

---

## The recommended pipeline (for files NOT in the official system)

Most files aren't on the Commons Impact Metrics allow-list, so here's the "DIY" path that works for **any file today**, using only free public APIs:

1. **Resolve the file to its storage path** (its technical address in the library).
2. **Find everywhere it's used** → GlobalUsage. You now have: *number of distinct wikis*, *number of distinct pages*.
3. **Measure transfers** → Mediarequests API. You now have: *how many times served*, per day/month, and how much of that is external (off-site).
4. **Measure reach** → Pageviews API, summing views across the pages from step 2. You now have: *how many people saw it in context*.
5. **Measure interest in the asset itself** → Pageviews API for the file's own page.
6. Combine into one report.

For a whole collection, repeat per file, or first bucket the files by category and aggregate.

---

## Caveats that matter (translated for a metrics person)

1. **Requests ≠ people.** Transfer counts include every thumbnail size and format. Browsers prefetch images (loading them before they're actually shown) and can inflate image counts by up to ~50% in some cases. Treat transfer numbers as "served requests," not "humans who looked at it."
2. **Page views ≠ file transfers.** These are separate systems. A top-article thumbnail can rack up millions of transfers while its file page gets tens of views.
3. **"Used" ≠ "viewed."** GlobalUsage tells you a file is embedded on 200 pages; it doesn't tell you anyone reads them. You must combine it with page views to get reach.
4. **Monthly drift (official system).** Commons Impact Metrics attributes a file's page views starting from the 1st of the month it was added — even if it was added on the 15th — slightly over-counting that first month. Self-corrects in later months.
5. **The official system is opt-in and scoped.** Commons Impact Metrics only covers ~1,755 approved collections, monthly, to a depth limit. For everything else, use the DIY pipeline.
6. **External reuse is only visible in one place.** If you care about off-site hotlinking/embedding, you must use Mediacounts referrer fields.
7. **Renaming a collection breaks official reporting.** If an approved collection is renamed, Commons Impact Metrics silently stops reporting on it until re-approved.
8. **Real-time is only for *changes*, not views.** EventStreams tells you when usage changes, not how often files are viewed.

---

## Sources & further reading

- Mediacounts dataset — https://wikitech.wikimedia.org/wiki/Data_Platform/Data_Lake/Traffic/Mediacounts
- Mediarequests API — https://wikitech.wikimedia.org/wiki/Analytics/AQS/Mediarequests
- Commons Impact Metrics — https://wikitech.wikimedia.org/wiki/Commons_Impact_Metrics
- Commons Analytics API (endpoints) — https://wikimedia.org/api/rest_v1/metrics/commons-analytics/api-spec.json
- GlobalUsage (cross-site usage index) — https://www.mediawiki.org/wiki/Extension:GlobalUsage
- Pageviews API — https://wikitech.wikimedia.org/wiki/Analytics/AQS/Pageviews
- BaGLAMa 2 — https://glamtools.toolforge.org/baglama2/
- GLAMorgan — https://glamtools.toolforge.org/glamorgan.html
- Structured data on Commons (SPARQL) — https://commons-query.wikimedia.org/

*Compiled 2026-08-14. All API behaviors and example numbers in this document were verified against the live Wikimedia systems on that date.*
