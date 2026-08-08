# Downloading originals, rate limits & date pitfalls — field notes

Hard-won lessons from a real whole-account transfer (**FESTIVAL-SALON**,
`31980831@N04`, alias `emperi`, 1817 photos → Commons). The two places this
workflow breaks are **downloading the image files** and **trusting the
`date_taken` metadata**. Both have cheap, reliable fixes.

## 1. Downloading originals: the staticflickr rate limiter

The API (api.flickr.com) is generously rate-limited (~3600 req/h), but the
**image CDN (`live.staticflickr.com`) throttles far more aggressively** — the
bottleneck of any full-account transfer is the file download, not the metadata.

Observed behaviour:

- The limiter is **wave-like**. You can fetch ~150–200 originals in a fast
  burst, then every request returns **HTTP 429** for a while, then it recovers
  for another burst.
- Once the 429s start, in-burst retries do **not** help — each retry inside the
  same wave also 429s and can extend the block. Retrying an ID that 429'd in
  the same pass wastes time.
- **After a ~10 minute pause the blocked URLs recover** and download fine. The
  block is per-IP/global, not per-URL.
- Escalating per-request backoff (120s → 240s → 360s …) inside one pass works,
  but it is wasteful: it lets the limiter recover mid-pass at the cost of long
  idle sleeps.

### The resumable, self-pacing pass pattern that works

Run the download as **repeated short passes** over the full file list instead
of one long loop:

1. Read the full URL list (or manifest) once.
2. For each file **not already present on disk**: try once.
3. If it succeeds → save (skip tiny/zero-byte files, e.g. `< 1000 bytes`).
4. If it returns 429 → **record the ID as "deferred"** and move on immediately
   (do not retry it this pass).
5. If it fails otherwise → record as failed for manual review.
6. At the end, stop. The next pass retries only what's still missing (deferred
   IDs are picked up automatically because they're simply still missing).

```bash
python download_all.py --max 250   # pass 1
python download_all.py --max 250   # pass 2 (resumes: skips existing)
python count_jpg.py                # how many are left
```

Properties:

- **Resumable**: existing files are skipped, so an interrupted pass loses
  nothing. Ctrl-C at any point is safe.
- **Self-pacing**: the pass itself naturally slows down under 429s; with the
  *defer-429* rule it never burns time on futile in-pass retries.
- **Deterministic**: running N passes is idempotent; the working set shrinks
  monotonically.
- Typical yield: 100–200 files per pass, rate-limited. A 1800-file account
  takes several passes — start each from a fresh shell (or your own terminal)
  rather than letting an agent hold one process open.

## 2. `date_taken` is often just the upload date — verify, don't trust

**Pitfall**: when an uploaded file has **no EXIF capture date**, Flickr sets
`date_taken` to the upload/processing time. An account holder uploading their
2007 festival photos in 2009 therefore produces photos with `date_taken=2009`
and a perfectly good `2007` tag. If you take `date_taken` at face value, every
one of those photos gets a wrong date in the manifest.

Real numbers (Festival Salon): **289 of 1817** photos were affected — the
`datetaken` said `2009`/`2010` while the tags said `emperi2006`/`emperi2007`/
`emperi2008`/`emperi 2011`. The year mismatch broke down as
`2006: 41, 2007: 105, 2008: 44, 2011: 99`.

### How to detect it (cheap, per-photo)

`flickr.photos.getInfo` returns a `dates` object with `taken`, `posted` and
`takengranularity`. Two cheap checks, then EXIF on the downloaded file:

1. **`taken` vs `posted`** — if they differ, `taken` came from somewhere
   (EXIF or manual). If they are equal, `taken` is an upload-time artifact.
2. **EXIF on the downloaded original** — open the file and look for
   `DateTimeOriginal` / `DateTimeDigitized` (the capture tags):
   - **Present** → that is the real capture date; compare it to `taken`.
   - **Absent** → the file has no trustworthy capture date at all. A generic
     `DateTime` tag alone (no `DateTimeOriginal`) is *not* a reliable capture
     stamp — it tracks file-modification time and often matches the (wrong)
     `taken` value.

Festival Salon's 289 resolved exactly this way: the 2006/2007/2008 files had
**no EXIF date at all** (14/48/1 sampled — 0 with any EXIF date), while the
2011 files carried only a generic `DateTime = 2010-08-xx` (no
`DateTimeOriginal`) that matched `taken`. Either way: no trustworthy capture
date existed.

### The fix: tags/albums are the source of truth for the year

- Check the **tags** (`flickr.photos.getInfo` → `photo.tags.tag[]`) and the
  **albums** (`flickr.photos.getAllContexts` → `sets[]` — 1 cheap request per
  photo, no need to enumerate whole photosets). The account owner's own
  `emperi2007` tag or an album title is the authoritative classification.
- Re-derive the date from the **edition/event year** in the tag/album, at the
  precision you actually know. For a yearly festival held every August, the
  project convention was `YYYY-08` (year + month, text) — never invent a day.
- Cross-check afterwards: confirm every corrected photo has a tag/album naming
  the year you used, and no photo carries **conflicting year tags**
  (e.g. both `emperi2006` and `emperi2009`). 289/289 checked out clean.
- Prefer a conservative render when the month is also uncertain:
  `{{Information|date=YYYY}}` (year only) is always defensible; full blanking
  throws away the one fact you do know (the year), so it's the last resort.

## 3. Categories and dedupe reminders (from the same transfer)

- Keep the **photo id in the Commons filename** — `Title (12345678901).jpg` —
  it is the only stable Flickr↔Commons key.
- Base account category: `Photographs by Festival Salon` (via
  `{{Flickr user category |id=31980831@N04|cat=p}}`).
- **Per-person tag → per-person category**: photos tagged `tavernier` got
  `Photographs by Nicolas Tavernier` added alongside the account category.
  A person-name tag is a legitimate trigger for a person category.
- Dedupe against files already on Commons: SPARQL by author-name-string
  (P2093) ∪ Flickr-user-id (P3267), plus the account category listing. The
  Wikidata item for the account (e.g. Q3070609) carries the `Flickr user ID`
  property — that's what ties the category → Wikidata → SPARQL chain together.
