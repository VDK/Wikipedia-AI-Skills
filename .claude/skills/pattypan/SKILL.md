---
name: pattypan
description: Build valid pattypan upload spreadsheets (.xls) for batch Wikimedia Commons uploads — two-sheet format, template variables, filename validation, and the bundled generator script
license: MIT
compatibility: opencode
depends_on: [wikimedia-commons]
skill_discovery_hints:
  - keywords: ["pattypan", "batch upload", "bulk upload", "spreadsheet", "xls", "Excel 97-2003"]
  - keywords: ["GLAM", "upload template", "Information template", "Commons upload"]
  - keywords: ["upload metadata", "file descriptions", "wikitext template"]
last_verified: 2026-08-05
---

> ⚠️ **This skill is derived from the pattypan source code and verified against its actual libraries (jxl + FreeMarker).** If you have the source checkout, trust this skill over online tutorials: the format contract below is exactly what `pattypan/src/pattypan/panes/{LoadPane,CreateFilePane}.java`, `Util.java`, and `Template.java` implement.

Pattypan is a desktop batch uploader for Wikimedia Commons. It reads file descriptions from an **`.xls` spreadsheet** (Excel 97-2003 binary format) and renders a **MediaWiki wikitext template** per file by substituting `${variable}` placeholders with per-file values. Your job as the agent: produce that `.xls` so pattypan can load it without errors.

## The spreadsheet contract (memorize this)

A pattypan spreadsheet is **at least two sheets in one `.xls` file** — pattypan reads `getSheet(0)` and `getSheet(1)` only, so extra trailing sheets (e.g. a human-review `Overview`) are ignored:

| Sheet | Purpose |
|-------|---------|
| **Sheet 1 — `Data`** | Row 0 = column headers; rows 1..N = one file per row |
| **Sheet 2 — `Template`** | Cell A1 = wikitext template with `${var}` placeholders, prefixed with a single `'` apostrophe |

### `Data` sheet

- **Row 0 must contain `path` and `name` columns.** pattypan throws `"Header error: ... 'path' and/or 'name' headers are missing"` if either is absent.
- **`path`** — absolute local file path **or** an `http://`/`https://` URL.
- **`name`** — the target Commons filename. For local paths, pattypan appends the extension from `path` automatically when the name lacks one. For URLs, `name` must already include a valid extension.
- **Other columns** — one per template variable you want to fill per-file, plus `categories`. Column header names must **exactly match** the `${var}` names used in the Template sheet (case-sensitive).
- A `date` column, if present, should hold values in `YYYY-MM-DD` or `YYYY-MM-DD HH:mm`. Text cells pass through verbatim (trimmed); Excel DATE cells are reformatted to `yyyy-MM-dd[ HH:mm]` **in UTC** (pattypan applies `SimpleDateFormat` in the UTC zone) — so write dates as text to avoid timezone/locale surprises.

### `Template` sheet

- Cell A1 holds the wikitext, e.g. `'{{Information\n|description={{en|1=${description}}}\n|date=${date}\n|source=${source}\n|author=${author}\n}}`. The whole upload page (Information block, license section, categories) lives in this one cell.
- The **leading apostrophe is required** — it stops Excel from treating the cell as a formula. pattypan strips it on load.
- **Every `${var}` referenced in the template MUST have a matching column in the Data sheet.** If any variable is missing, FreeMarker raises `InvalidReferenceException` and pattypan reports `"variables mismatch. Column headers variables must match wikitemplate variables."` Extra Data columns not referenced by the template are harmless (FreeMarker ignores them).
- **Constants live in the template; the Data sheet holds only variables.** Anything identical for every file — a photographer's NSID/username inside a source or author URL, the license, `Permission` — is written **directly into the template text** (replace `${var}` with the literal value), not repeated in cells or left as empty columns. Empty values produce warnings and, if a description field ends up empty, a bad upload.
- **Columns and template variables are yours to choose** — the sample template is illustrative, not a contract. Pick the smallest set of per-file variables (`id`, `title`, `description`, `date`, `categories`, …) and build everything else in the template. With the account NSID hardcoded, a source URL becomes `[https://www.flickr.com/photos/<nsid>/${id}/ ${title}]` instead of a repeated per-row URL column.
- **Optional per-file overrides**: guard with `<#if var ? has_content>${var}<#else>…default…</#if>` so most rows leave the column empty and only exceptions fill it (e.g. a row whose title is meaningless gets an explicit source URL). `?has_content` on a missing column is safe.

#### FreeMarker directives (verified: FreeMarker 2.3.23, DEBUG_HANDLER)

The Template cell is compiled with the real FreeMarker engine, so the template is **not limited to `${var}` substitution**: directives and built-ins work. The most valuable production pattern (used in a 986-file Re:publica 2026 batch and a UX Brighton speaker batch) renders one `;`-separated `categories` column into multiple `[[Category:...]]` lines, with an uncategorized fallback:

```wikitext
<#if categories ? has_content>
<#list categories ? split(";") as category>
[[Category:${category?trim}]]
</#list>
<#else>{{subst:unc}}
</#if>
```

FreeMarker behavior you can rely on:
- `?has_content` on a **missing** column is safe (evaluates to false) — only a bare `${missing}` or an unguarded `<#list missing ...>` aborts the whole load with "variables mismatch" (`InvalidReferenceException`, `DEBUG_HANDLER` rethrows it). Guard optional columns with `<#if x ? has_content>`.
- The bundled script treats directive-only references as warnings (fallback), not errors; it also flags template columns that are empty in every row.
- Full upload templates are normal: `{{int:filedesc}}`, the `{{Information}}` block, `{{int:license-header}}`, the license template (`{{CC-BY-SA-4.0}}`, `{{Cc-by-2.0}}`, ...) plus `{{FlickreviewR}}`/`{{Flickrreview}}`, and the categories block above all go in the single Template cell.

### File format

- **`.xls` (BIFF8, "Excel 97-2003") only.** pattypan's file picker filters `*.xls` and it uses the `jxl` library, which cannot read `.xlsx`. If you hand the user an `.xlsx` or a CSV, pattypan fails with `"file needs to be saved in binnary format. Please save your file in \"Excel 97-2003 format\""`.
- Non-ASCII text (Cyrillic, CJK, accented Latin) **is** supported — write the file with a proper Excel `.xls` writer (see script below). Verified against jxl.

## SOP: Build a pattypan spreadsheet

### 1. Collect the inputs
- List of files (local absolute paths or direct URLs) to upload.
- Per-file metadata: description, date, author/source, categories, etc.
- The wikitext upload template with `${var}` placeholders (typically `{{Information|...}}`).

### 2. Decide the columns
`path`, `name` + one column per `${var}` you want to vary per file + `categories`. If a value is the same for every file, hard-code it into the Template sheet instead of adding a column.

### 3. Generate the file (recommended: bundled script)

Use `scripts/build_pattypan_spreadsheet.py` (requires `xlwt`, `pip install xlwt`). It builds the two-sheet `.xls`, validates headers/template/names, and reports pattypan-compatible warnings and errors:

```bash
# From a CSV/TSV/JSON manifest (first row = headers; must include path & name)
python scripts/build_pattypan_spreadsheet.py \
  --manifest files.csv \
  --template information.wikitext \
  --output pattypan-upload.xls

# From a directory of images (auto path+name rows; fill constant template vars)
python scripts/build_pattypan_spreadsheet.py \
  --dir /path/to/photos \
  --template information.wikitext \
  --constants '{"author": "Jane Doe", "source": "{{own}}"}' \
  --categories "Monuments of Paris" \
  --output pattypan-upload.xls

# Validate without writing
python scripts/build_pattypan_spreadsheet.py --manifest files.csv --template t.txt --check-only
```

Run `--help` for all options (per-file JSON/CSV values, `--date-from-exif`, `--name-pattern`, `--allow-urls`).

### 4. Generate the file without the script (drop-in Python)

If the agent can't run the script, write the `.xls` directly with `xlwt`:

```python
import xlwt

headers = ["path", "name", "description", "date", "author", "categories"]
rows = [
    ["/home/user/Eiffel.jpg", "Eiffel Tower from Trocadero",
     "View of the tower in 1889", "1889-03-31", "Jane Doe", "Monuments of Paris"],
    # ...
]
template = ("{{Information\n|description={{en|1=${description}}}\n|date=${date}\n"
            "|source=${source}\n|author=${author}\n}}\n[[Category:${categories}]]")

wb = xlwt.Workbook()
ws = wb.add_sheet("Data")
for c, h in enumerate(headers):
    ws.write(0, c, h)
for r, row in enumerate(rows, start=1):
    for c, value in enumerate(row):
        ws.write(r, c, value)
ts = wb.add_sheet("Template")
ts.write(0, 0, "'" + template)   # leading apostrophe is REQUIRED
wb.save("pattypan-upload.xls")
```

### 5. Verify
- Load the spreadsheet into pattypan (Start → Load file) and check the summary: `N files loaded successfully`, `0 errors`, warnings are advisory.
- Ideally preview the rendered wikitext via `Special:ExpandTemplates` on the wiki.
- After any bulk metadata edit (e.g. correcting dates across many rows), **rebuild and re-verify** with `--check-only`, then confirm the Template sheet's cell A1 still holds the constant author/license text and spot-check the resulting column values in the `Data` sheet (e.g. the year-month distribution of the `date` column).
- **Year-month text dates** (`2011-08`) pass through verbatim and are the right precision when only the edition year plus a recurring month (e.g. a yearly festival held every August) is reliably known — never invent a day.

## Filename validation rules (pattypan `Util.java`)

Apply these before writing `name` values — pattypan rejects or warns on violations:

- **Allowed file extensions** (checked for URL paths): `djvu flac gif jpg jpeg mid mkv oga ogg ogv opus pdf png svg tiff tif wav webm webp xcf mp3 stl`
- **Invalid characters — hard error** (pattypan rejects the row): `# < > [ ] | { }`
- **Camera-name prefixes — warning** (bad filenames): `CIMG DSC_ DSCF DSCN DUW GEDC IMG JD MGP PICT Imagen FOTO DSC SANY SAM`
- **Colon `:` — warning (Commons-level)**: pattypan accepts `:` in `name`, but Commons filenames cannot contain it (namespace separator). Replace with `-` (e.g. `Re:publica` → `Re-publica`). In production, also append the source photo ID in parens for uniqueness and traceability: `Re-publica 2026 - Tag 1 (55277934544).jpg`.
- **Length — warning (Commons-level)**: filenames are limited to **240 bytes** (Commons:File_naming; a byte limit, not characters— non-ASCII characters take up to 4 bytes each, so 240 bytes can be far fewer than 240 characters). pattypan does not enforce this; Commons rejects new uploads over the limit and old-version uploads break when the date gets prefixed to the name.
- **Local `path` must exist**; **URL `path` must be a valid URL** and `name` must carry a valid extension.
- **Date text cells pass through verbatim** (trimmed), so `YYYY-MM-DD HH:mm:ss` with seconds is fine; Excel DATE cells are reformatted to `YYYY-MM-DD[ HH:mm]` in UTC.

## Guardrails

1. **Never produce `.xlsx`, CSV, or ODS.** The file must be `.xls` (Excel 97-2003). This is the #1 failure mode for agents asked to "make a spreadsheet for pattypan".
2. **Data first, Template second**; extra trailing sheets (e.g. a review `Overview`) are ignored. pattypan reads `workbook.getSheet(0)` and `getSheet(1)` only; a missing second sheet triggers `"your spreadsheet should have minimum two tabs"`.
3. **Prefix the Template cell with `'`.** Without it, Excel may rewrite the cell or pattypan's round-trip breaks.
4. **Every `${var}` in the template needs a Data column.** Missing ones fail the whole load with "variables mismatch". Reconcile the template and headers before writing.
5. **Header names must match `${var}` names exactly** (e.g. `${description}` ↔ column `description`). No whitespace, no renames.
6. **One file per row.** Blank `path`/`name` rows are skipped silently by pattypan; partially blank rows fail.
7. **Keep template values per-file; constants go in the template.** Empty description/source/author fields will be flagged and can produce unusable uploads.
8. **Respect Commons naming and licensing** — see the **[wikimedia-commons](../wikimedia-commons/SKILL.md)** skill for naming conventions, allowed formats, and the license/permission (VRT) requirements. `name` values should be unique, descriptive, and free of camera prefixes.
9. **Do not fabricate metadata.** If you don't know the author, source, or date, leave it blank or flag it to the user — never invent plausible values.

## References and assets

| File | What it is |
|------|-----------|
| `references/pattypan-spreadsheet-format.md` | Deep reference: field-by-field format spec, column↔template matching rules, date/EXIF handling, and the exact error strings pattypan emits |
| `scripts/build_pattypan_spreadsheet.py` | The generator/validator script (importable + CLI, `xlwt` required) |
| `assets/sample-manifest.csv` | Example CSV manifest to adapt |
| `assets/sample-template.wikitext` | Example `{{Information}}` template with `${var}` placeholders |

## Scripts

### `scripts/build_pattypan_spreadsheet.py`

Builds and validates pattypan `.xls` spreadsheets from a CSV/TSV/JSON manifest or a directory of files.

```bash
python scripts/build_pattypan_spreadsheet.py --manifest files.csv --template t.wikitext --output out.xls
python scripts/build_pattypan_spreadsheet.py --dir ./photos --template t.wikitext --constants '{"author":"Jane"}' --output out.xls
python scripts/build_pattypan_spreadsheet.py --manifest files.csv --template t.wikitext --check-only
```
