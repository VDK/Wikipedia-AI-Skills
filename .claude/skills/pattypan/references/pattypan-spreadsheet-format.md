# Pattypan Spreadsheet Format — Reference

Field-by-field specification for the `.xls` spreadsheet pattypan consumes,
derived from the pattypan source (`src/pattypan/panes/LoadPane.java`,
`CreateFilePane.java`, `Template.java`, `UploadElement.java`, `Util.java`,
`Session.java`) and verified against its runtime libraries (`jxl.jar`,
`freemarker.jar`).

## 1. File container

- **Format:** BIFF8 — "Excel 97-2003" `.xls`. The reader is the legacy
  `jxl` library (`Workbook.getWorkbook(file, settings)`), which cannot read
  `.xlsx`. The file chooser filters `*.xls`.
- **Encoding:** the reader constructs strings from the workbook bytes; UTF-16
  shared strings are decoded correctly, so non-ASCII text (accented Latin,
  Cyrillic, CJK) works. Reading is configured with
  `WorkbookSettings.setEncoding("Cp1252")`, which only affects 8-bit
  (compressed) strings; modern writers store strings as UTF-16.
- **Sheets:** `getSheet(0)` = Data, `getSheet(1)` = Template. Extra trailing
  sheets (e.g. a human-review "Overview") are ignored because pattypan never
  looks past index 1. A missing second sheet raises
  `"Error: your spreadsheet should have minimum two tabs."`

## 2. Data sheet (sheet index 0)

### 2.1 Header row (row 0)

Each cell is a column header — a variable name. pattypan reads every column
to row 0 and builds per-row maps keyed by header:

```java
String label = sheet.getCell(column, 0).getContents().trim();
```

Required headers (pattypan fails without them):

```
"Header error: columns not found!"                                    (no cells)
"Header error: found N headers but 'path' and/or 'name' headers are missing"
```

- `path` — absolute local file path, or an `http://` / `https://` URL.
- `name` — target Commons filename (see §4 for the rules pattypan applies).

Optional/recommended headers, matching template variables:

- One column per template variable you want to vary per file.
- `categories` — categories applied to each file (pattypan adds this column
  automatically when it generates a spreadsheet).
- `date` — capture date; pattypan can auto-fill it from EXIF.

### 2.2 Data rows (row 1..N)

- One file per row.
- A row where **both** `path` and `name` are empty is silently skipped
  (`if (description.get("path").isEmpty() && description.get("name").isEmpty()) continue;`).
- `getCellValue` trims string cells and renders Excel DATE cells as
  `yyyy-MM-dd` or `yyyy-MM-dd HH:mm` (UTC, the exact format depends on whether
  the cell's text contains a colon).

### 2.3 Column ↔ template matching

When pattypan renders each row it runs the Template sheet wikitext through
FreeMarker with the row's column map as the data model:

- Every `${var}` in the wikitext **must** be present as a column; otherwise
  FreeMarker raises `InvalidReferenceException` and pattypan reports:
  ```
  "File error: variables mismatch. Column headers variables must match wikitemplate variables."
  ```
- Extra columns not referenced by the template are ignored (FreeMarker allows
  surplus data-model keys), but pattypan warns about all-empty columns.
- Matching is exact and case-sensitive.

## 3. Template sheet (sheet index 1)

- Cell `(0,0)` (A1) contains the wikitext template.
- The **leading apostrophe is part of the written value**:
  `templateSheet.addCell(new Label(0, 0, "'" + Session.WIKICODE))`. It
  prevents Excel from treating the cell content as a formula. On load:
  ```java
  if (String.valueOf(wikicode.charAt(0)).equals("'")) {
      wikicode = wikicode.substring(1);
  }
  ```
- If the cell is missing/empty:
  `"Error: template in spreadsheet looks empty. Check if wikitemplate is present in second tab of your spreadsheet (first row and first column)."`
- If the template renders to an empty string for a row, the row fails with
  `"Error: empty template!"`.
- **FreeMarker 2.3.23.** `readTemplate` compiles the cell with the real
  FreeMarker engine (`new Template("wikitemplate", new StringReader(text),
  cfg)`, `TemplateExceptionHandler.DEBUG_HANDLER`, default encoding UTF-8).
  Directives and built-ins work: `<#if>`, `<#list>`, `<#elseif>`, `?split`,
  `?trim`, `?has_content`, and more. `DEBUG_HANDLER` rethrows every
  `TemplateException`, so an unguarded `${missing}` or `<#list missing ...>`
  aborts the **whole** load with the "variables mismatch" message, while
  `?has_content` on a missing key safely evaluates to false (enables the
  `<#else>{{subst:unc}}</#if>` fallback pattern).
- pattypan automatically appends `[[Category:Uploaded with pattypan]]` to the
  final wikitext of every upload (in `UploadElement.getWikicode()`), so you do
  not need to add it yourself.

## 4. Filename validation (Util.java)

Applied to the `name` value on load; violations either reject the row or emit
a warning.

| Rule | Behavior |
|------|----------|
| Extension auto-append | For local (non-URL) paths, whenever the name's extension differs from the file's extension, pattypan appends the file extension: `name = name + "." + pathExt`. So `name` with no extension becomes `name.jpg`; `name` with a *different* extension becomes `name.png.jpg` (a warning in practice) |
| Allowed extensions | `djvu flac gif jpg jpeg mid mkv oga ogg ogv opus pdf png svg tiff tif wav webm webp xcf mp3 stl` — for URL paths the `name` **must** already carry one (`"filename does not include a valid file extension"`) |
| Invalid characters | `# < > [ ] | { }` — hard error: `"filename shouldn't contain invalid characters (#, ], {, etc)"` |
| Camera-name prefixes | `CIMG DSC_ DSCF DSCN DUW GEDC IMG JD MGP PICT Imagen FOTO DSC SANY SAM` — warning only |
| `path` existence | Local paths must resolve to a real file (`"file not found"`); URLs must be valid (`"invalid URL"`) |
| Empty `path` / `name` | Hard error: `"empty path"` / `"empty name"` |
| Empty other values | Warning listing the empty columns |
| Whitespace normalization | At check/upload time `name` is trimmed and internal runs of spaces collapsed (`Util.getNormalizedName`: `name.trim().replaceAll(" +", " ")`) |
| Colon in `name` | `:` is **not** rejected by pattypan but is invalid in a Commons filename (namespace separator) — replace with `-`; the Commons upload would fail otherwise |
| Filename length | `name` must be **<= 240 bytes** (a byte limit— non-ASCII characters take up to 4 bytes each). pattypan does not check it, but MediaWiki's upload code does: `UploadBase.php` fails with `filename-too-long` when `strlen($mFilteredName) > 240` (PHP `strlen` counts bytes). Reason, from the code comment: the `oi_archive_name` column maxes at 255 bytes and holds filename + timestamp + `!`, so the bare filename is capped at 240 bytes. Commons:File_naming states the same 240-byte hard limit |

## 5. EXIF date auto-fill (CreateFilePane)

When the `date` variable is selected and the EXIF option is enabled, pattypan
fills the `date` column from each image's EXIF `DateTimeOriginal`, formatted
`yyyy-MM-dd HH:mm` (local timezone). An empty string is written when no EXIF
date exists. A manually authored `date` column should use `yyyy-MM-dd` or
`yyyy-MM-dd HH:mm`.

## 6. Round-trip behavior verified against pattypan's libraries

- A workbook written with `xlwt` (encoding `utf-8`, two sheets, apostrophe
  template) is read back by `jxl` with all UTF-16 strings intact — including
  Cyrillic and accented Latin.
- FreeMarker processes `${description}` / `${categories}` etc. correctly and
  raises `InvalidReferenceException` for a missing column, exactly matching
  pattypan's "variables mismatch" error path.

## 6.5 Production-verified patterns (Re:publica 2026, UX Brighton)

Two real, uploaded batches confirm the format and add field-tested patterns.
Both were built from Flickr metadata and loaded into pattypan without errors
(986 files in the Re:publica batch).

Data sheet headers actually used (all columns beyond `path`/`name` are plain
template variables; `license` and `naam/event` were extra, harmless columns):

```
path, name, description, date, source, author, permission, categories, license, naam/event
```

A real Template cell (single cell, leading apostrophe, trailing newline):

```wikitext
'=={{int:filedesc}}==
{{Information
 |description = ${description}
 |date = ${date}
 |source = ${source}
 |author = ${author}
 |permission = ${permission}
 |other versions = 
}}

=={{int:license-header}}==
${license}{{Flickrreview}}

<#if categories ? has_content>
<#list categories ? split(";") as category>
[[Category:${category?trim}]]
</#list>
<#else>{{subst:unc}}
</#if>
```

Patterns that kept the batch clean:
- **Filenames:** `Re:publica` became `Re-publica`; the Flickr photo ID was
  appended in parens (`Re-publica 2026 - Tag 1 (55277934544)`), making names
  unique and traceable to the source photo.
- **`description`:** values embedded as `{{en|1=...}}` (or `{{de|...}}`), with
  `|`, `{`, `}` in the source text HTML-entity-escaped as `&#124;`,
  `&#123;`, `&#125;` so they survive FreeMarker and are decoded by the
  MediaWiki parser inside the template argument.
- **`author`:** `{{label| QID }} / [https://www.flickr.com/photos/<id>/ re:publica]`
  renders the photographer's name from a Wikidata QID plus a credit link to
  the source account.
- **`source`:** wikilink to the Flickr photo page using the photo title as the
  label: `[https://www.flickr.com/photos/<id>/<photoid> <title>]`.
- **`date`:** written as text (`2026-05-18 10:07:49`, with seconds) passes
  through verbatim.
- **`categories`:** `;`-separated list in one column, expanded to one
  `[[Category:...]]` line per value by the `<#list categories ? split(";")>`
  block above; empty column renders `{{subst:unc}}`.
- **Workflow:** build a metadata workbook first (no `path`), download the
  files, then add the `path` column pointing at the local copies.

## 7. Common error strings (for debugging user reports)

| pattypan message | Meaning |
|------------------|---------|
| `File error: file needs to be saved in binnary format. Please save your file in "Excel 97-2003 format"` | File is not a valid `.xls` (e.g. `.xlsx`, CSV, or a corrupted file) |
| `Error: your spreadsheet should have minimum two tabs.` | Second (Template) sheet missing |
| `File error: variables mismatch. Column headers variables must match wikitemplate variables.` | A `${var}` in the Template sheet has no matching Data column |
| `Error: template in spreadsheet looks empty. Check if wikitemplate is present in second tab of your spreadsheet (first row and first column).` | Cell A1 of the Template sheet is empty |
| `Header error: columns not found!` / `Header error: found N headers but 'path' and/or 'name' headers are missing` | Data sheet empty or lacks the required `path`/`name` columns |
| `filename shouldn't contain invalid characters (#, ], {, etc)` | `name` contains `# < > [ ] | { }` |
| `filename does not include a valid file extension` | URL upload where `name` lacks an allowed extension |
| `invalid URL` | `path` is not a valid `http(s)://` URL |
| `empty path` / `empty name` | Row missing a required value |
