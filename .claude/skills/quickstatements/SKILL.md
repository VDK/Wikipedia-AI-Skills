---
name: quickstatements
description: Build and run QuickStatements (QS) batches for Wikidata and Commons - the V1 command grammar (statements, qualifiers, references, ranks, item creation), value formatting (dates, quantities, coordinates, monolingual text), multilingual labels/descriptions/aliases, the QS 2.0 and QS 3.0 tools and their web UI/URL/API entry points, plus validation and best practices
license: MIT
compatibility: opencode
depends_on: [wikimedia-api-access, wikidata]
skill_discovery_hints:
  - keywords: ["QuickStatements", "QS batch", "batch edit", "wbcreateclaim", "wbsetlabel", "wbsetdescription"]
  - keywords: ["create item", "CREATE", "LAST", "new item Wikidata", "person item", "New-Q5"]
  - keywords: ["rank preferred", "Rpreferred", "deprecated rank", "forced statement", "MERGE", "statement ID"]
  - keywords: ["multilingual label", "Lmul", "Amul", "alias", "sitelink", "label description alias"]
  - keywords: ["Commons structured data", "M ID", "SDC batch", "QuickStatements Commons"]
last_verified: 2026-06-24
---

# QuickStatements

Build and run **QuickStatements** (QS) batches: batch edits to Wikidata items
(and, via QS 2.0, to Commons Structured Data) written as plain text commands.
The full grammar lives in
[references/quickstatements-syntax.md](references/quickstatements-syntax.md);
canonical upstream docs are
[Help:QuickStatements](https://www.wikidata.org/wiki/Help:QuickStatements)
and the [QS 3.0 User guide](https://meta.wikimedia.org/wiki/QuickStatements_3.0/Documentation/User_guide).

## When to use this skill

Use QuickStatements when you need to apply the **same shape of edit to many
entities** (or many statements to one entity): adding a property to a whole
category's worth of items, setting labels/descriptions in several languages,
creating person items in a batch, or removing statements after cleanup.

Prefer the Wikibase **API** (see the `wikidata` skill) when the batch needs
per-item branching logic, or when you need control QS does not offer (ranks
in QS 2.0, calendar, coordinate globe/precision). Prefer **Pywikibot** for
data-driven loops. QuickStatements' strength is the reviewable, plain-text
batch: you can read exactly what will be edited, run it from a URL, and
roll it back as one edit group.

## Pick the version first

| Need | Use |
|---|---|
| New Wikidata statement work | **QS 3.0** (`qs-dev.toolforge.org`) - ranks, forced duplicates, grouped edits |
| Commons Structured Data (M IDs) | **QS 2.0** (`quickstatements.toolforge.org`) - QS 3.0 cannot (REST API limit) |
| `MERGE` items, lexemes | **QS 2.0** |
| Programmatic submission | **QS 2.0** `api.php` token interface |

V1 commands are compatible across versions, so a batch like the New-Q5
person example runs unchanged in both.

## Standard operating procedure

### 1. Decide the edits, not the code

List the entity IDs and the exact property/value pairs. Fetch labels and
QIDs you need (Wikidata search or SPARQL - see the `wikidata` skill).
**Search before `CREATE`**: duplicate items are the most common QS disaster.

### 2. Write V1 commands

One command per line, fields separated by `|`:

```
Q42|P31|Q5
Q42|P21|Q6581097
Q42|P569|+1952-03-11T00:00:00Z/11|S854|"https://example.com/source"|S813|+2026-06-24T00:00:00Z/11
```

- **Strings, URLs, filenames, external IDs must be double-quoted** - `"..."`.
- **Time** values: `+1967-01-17T00:00:00Z/11` (`/9` year, `/10` month,
  `/11` day; `+` CE, `-` BCE; `/J` for Julian).
- **Quantity**: `5.5U11574` or `-80~1.5` (no spaces).
- **Coordinates**: `@43.26193/10.92708`.
- **Monolingual text**: `en:"Some text"`.
- Qualifiers follow the value: `|P1545|"1"`.
- References use `S` properties after the value: `|S854|"url"|S813|+...`;
  a new reference group starts with `!S248`.
- New items: `CREATE` then `LAST|...` for every subsequent command on that
  item.
- QS 3.0 extras: rank tokens `R+`/`R0`/`R-` (or `Rpreferred`/`Rnormal`/
  `Rdeprecated`), `+Qid|...` to force a duplicate, `REMOVE_QUAL`,
  `REMOVE_REF`, `SWITCH_VALUE`, `SWITCH_PROPERTY`.
- Edit summaries: append `/* comment */` to a command.

### 3. Multilingual labels, descriptions, aliases

This is where person and entity batches get their translations:

```
LAST|Lmul|"Jane Doe"                 # label in every language
LAST|Len|"Jane Doe"                  # explicit per-language labels
LAST|Lde|"Jane Doe"
LAST|Lfr|"Jane Doe"
LAST|Lnl|"Jane Doe"
LAST|Den|"person"                    # description is per-language (no Dmul)
LAST|Amul|"Jane D."                  # alias for all languages
```

- Proper nouns (names, brands) are **not translated** - `Lmul` plus explicit
  `Lxx` rows is the New-Q5 pattern.
- Descriptions have no `mul`: write `Den`, `Dnl`, ... individually.
- QS 3.0: multiple aliases per language as separate columns
  `|Aen|"Gandhi"|"Mohandas Gandhi"`; QS 2.0: pipe-separated inside one
  quoted value (and not during item creation).

### 4. Validate before running

```
python .claude/skills/quickstatements/scripts/qs_batch.py --file batch.txt
```

The script checks entity/property shapes, value formats (dates, quantities,
coordinates, quotes), qualifier/source pairs, CREATE/LAST pairing, and the
QS 3.0 commands, and can also build a person batch and produce clickable
URLs:

```
python .claude/skills/quickstatements/scripts/qs_batch.py \
  --person "Jane Doe" --description "person" --dob 1980-01-02 \
  --gender Q6581097 --url --version 3
```

### 5. Run

- **Web UI**: paste into "New batch", preview (QS converts to human-readable
  form), then run. Watch the first few commands; hit STOP on a problem.
- **Background** (QS 2.0 "Run in background"): server-side execution, batch
  URL with DONE/ERROR/INIT/RUN counters, revertible as an edit group. Use
  normal mode for ~10 or fewer statements.
- **By URL**: `https://quickstatements.toolforge.org/#/v1=<encoded>`
  (QS 2) or `https://qs-dev.toolforge.org/batch/new?v1=<encoded>`
  (QS 3).
- **API** (QS 2.0): `POST https://quickstatements.toolforge.org/api.php?action=import`
  with `username`, `token` (from your QS user page), `data`, `submit=1`,
  `openpage=1`, `batchname`, and `site=commons` for SDC. You must have run
  one server-side batch manually before the token works.

### 6. Verify and clean up

- Check the batch status page for ERROR lines; re-run only the failed
  commands (fix the cause first).
- A batch is one **edit group** - roll back the whole thing with
  EditGroups if it was wrong.
- For large or contested runs, follow the Wikidata:Bots approval process.

## Guardrails

- Autoconfirmed account + OAuth login required; QS edits are **public**.
- No duplicate items: always search/resolve QIDs before `CREATE`.
- Reference claims per Help:Sources (identifiers are the exception).
- QS 2.0 does not honor maxlag; large runs are rate-limited by edit limits.
- Never run a batch whose commands you could not read back and explain;
  the whole point of QS is reviewability.

## Related skills

- `wikidata` - data model, SPARQL, and API for gathering IDs and labels.
- `wikimedia-commons-sdc` - QS 2.0 batch mode for Commons M IDs.
- `wikimedia-api-access` - User-Agent and rate-limit conventions.
- `wikimedia-auth-oauth` - OAuth setup for editing tools.
