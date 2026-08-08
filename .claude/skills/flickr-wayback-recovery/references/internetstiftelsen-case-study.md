# Case study: the Internetstiftelsen rescue (2026)

The worked example this skill is derived from. A deleted institutional Flickr
account was recovered end-to-end; the numbers below are the real production
figures and the failures are the ones the guardrails exist for.

## Context

- **Account**: Internetstiftelsen (Swedish Internet Foundation) — NSID
  `44783532@N07`, alias `stiftelsen`. Used for event photography
  (Internetdagarna, Goto 10, Webbstjärnan, Arthackday, …).
- **Failure**: the account was deleted; `flickr.com/photos/stiftelsen` and the
  people page 404, and the live Flickr API has no data.
- **Target**: re-upload every photo that was **not** already on Commons, via
  pattypan, matched by Flickr ID.

## The numbers

| Step | Count |
|---|---|
| CDX rows (NSID form) | 954 |
| CDX rows (alias form) | 932 |
| Union of distinct photo IDs | 1,130 |
| Flickr IDs already on Commons (title + wikitext + SDC) | 399 |
| Upload scope (not on Commons) | 736 |
| Photos with metadata + a downloaded image | 733 |
| CC BY-NC-2.0 (skipped) | 1 |
| No archived photo page / no photo model | 3 + 1 |
| Uploaded after the initial Commons scan | 2 |
| Pruned by the user as irrelevant / derivative work | 56 |
| **Manifest rows uploaded** | **675** |

## What actually went wrong (and the fix)

1. **Trailing-slash regex dropped 209 IDs.** The first CDX parser required a
   trailing slash in `/photos/<nsid>/<id>/`; captures without it were missed.
   Fix: optional slash + `in/...` suffix in the regex, then re-union both URL
   forms.
2. **Some pages archived without content.** 3 IDs had no photo page capture and
   1 had a page with no `modelExport` blob. Recorded as `error:` records and
   excluded — not fatal.
3. **Mojibake in metadata.** Flickr stores percent-encoded latin-1 bytes; naive
   UTF-8 decoding produced `ã¶` for `ö`. Fix: decode with
   `unquote_to_bytes(...).decode("latin-1")` + NFKC normalization.
4. **Wayback returns HTML error pages with HTTP 200.** A "downloaded" file was
   sometimes an HTML error page. Fix: magic-byte validation on every download.
5. **Camera-garbage titles.** ~56 titles were camera filenames (`IMG_2184`,
   `ind12_.SE_9888`, `_W6A8157.jpg`). Fix: sequential per-year naming
   `Swedish Internet Foundation <year> (NNN)`, contiguous across pruned rows.
6. **Pruned photos crept back in.** The user deleted files to drop
   irrelevant/derivative photos, but `images.json` still held archived URLs, so
   the manifest kept those rows. Fix: an explicit `skip_photos.txt` that the
   build honours even when a file/URL exists.
7. **Dead people-page link.** `flickr.com/people/<nsid>/` was never archived;
   linking it in `|Author=` produced a 404. Fix: credit the plain account name
   (`Stiftelsen`).

## Manifest decisions worth copying

- **Filename**: `<normalized title> - <Event> (<flickr id>).jpg` — the ID in
  parentheses is the durable join key for Commons search/category work.
- **Description**: language-tagged real description + event placeholder, never
  two blocks in the same language; the Flickr title is never used as a
  description; tag-like fragments move to the tag list.
- **Categories**: account category + event category + year category + **person
  categories for the photographed speakers** (red categories acceptable, bot
  creates them later); photographer categories are applied separately from the
  credit in the description.
- **License**: raw Flickr license id travels in the manifest; the template maps
  `4 → {{cc-by-2.0}}`, `5 → {{cc-by-sa-2.0}}`; license 2 (NC) skipped.
- **Tags**: `{{Information field|name=Flickr tags|value=...}}` in `other_fields`.
- **Validation**: 675 rows, 0 errors, 0 warnings before upload.

## Re-running it for another account

1. `cdx-photo-ids.py <nsid> <alias>` → photo ID list.
2. `check-commons.py` → already-present IDs.
3. `fetch-photo-metadata.py` → `rescue_out/metadata.json`.
4. `download-images.py` → `images/` + `images.json`.
5. `build-manifest.py` → `manifest.csv`.
6. `validate-manifest.py` + `pattypan/scripts/build_pattypan_spreadsheet.py` → `.xls`.
7. Pattypan: confirm "N files loaded, 0 errors", upload.
