# QuickStatements syntax & workflow reference

QuickStatements (QS) turns a plain-text list of commands into batch edits on
Wikidata (and, via QS 2.0 only, on Commons Structured Data). The canonical
documentation is
[Help:QuickStatements](https://www.wikidata.org/wiki/Help:QuickStatements)
(QS 2.0) and the
[QuickStatements 3.0 User guide](https://meta.wikimedia.org/wiki/QuickStatements_3.0/Documentation/User_guide).

## Choosing a version

| | QuickStatements 2.0 | QuickStatements 3.0 |
|---|---|---|
| Maintainer | Magnus Manske | Wikimedia Brasil |
| URL | `https://quickstatements.toolforge.org/` | `https://quickstatements.toolforge.org/` (dev: `https://qs-dev.toolforge.org/`) |
| Syntax | V1 + CSV | V1 + CSV (compatible superset) |
| Ranks (preferred/normal/deprecated) | no | **yes** (`R+` / `R0` / `R-`) |
| Force duplicate statements | no | **yes** (`+` prefix) |
| Remove single qualifier / reference | no | **yes** (`REMOVE_QUAL`, `REMOVE_REF`, `REMOVE_REF_BLOCK`) |
| Switch statement value / property | no | **yes** (`SWITCH_VALUE`, `SWITCH_PROPERTY`, `SWITCH_PROPERTY_AND_VALUE`) |
| Command grouping (one edit per entity run) | no | **yes** (toggle "Do not combine commands") |
| Merge items (`MERGE`) | yes | **no** (use QS 2.0) |
| Commons Structured Data (M IDs) | yes | **no** (Wikibase REST API does not support SDC yet) |
| Lexemes / forms / senses | yes (partial) | **no** |
| Batch results report (CSV) | no | **yes** |
| Batch API (`api.php`) | yes (token) | via the UI / Wikibase REST API |

**Recommendation:** use QS 3.0 for new Wikidata statement work (ranks, forced
duplicates, faster grouped edits). Use QS 2.0 when the batch touches Commons
Structured Data (M IDs), merges items, or edits lexemes, and when submitting
batches programmatically through the `api.php` token interface. New-Q5
generates V1 commands that run unchanged in either version.

Both versions require an **autoconfirmed** account and OAuth login.

## Input format 1: V1 commands

Fields are separated by `|` or `TAB`; commands by a newline or `||`. Values
that contain a literal `|` (e.g. multi-alias rows in QS 2.0) are the only
place where quoting does not help - keep those rows on separate lines.

### Statements

```
Q42|P31|Q5                 # Douglas Adams (Q42) instance of (P31) human (Q5)
Q42|P19|Q350               # entity value: Cambridge (Q350)
Q41576278|P373|"Antoni Ignacy Mietelski"   # string value, double-quoted
Q1214098|P1476|pl:"Krzyżacy"              # monolingual text: lang:"text"
Q41576483|P569|+1839-00-00T00:00:00Z/9    # time value (see below)
Q3669835|P625|@43.26193/10.92708          # coordinates: @LAT/LON
Q3450504|P1098|1                          # quantity
Q739484|P2044|2994U11573                  # quantity with unit (metre)
Q97|P2046|106460000~10000U712226          # quantity with tolerance (QS2/QS3)
Q331226|P156|novalue                      # special values: novalue / somevalue
```

Notes:
- Entities: `Q...` (Wikidata items), `P...` (properties), `M...` (Commons
  media), `L...`, `L...-F..`, `L...-S..` (lexemes/forms/senses).
- **Strings, URLs, filenames, external IDs** must be double-quoted:
  `"..."`. This is the most common mistake.
- **Time** format is `+1967-01-17T00:00:00Z/11` with precision `/N`:
  `/9` year, `/10` month, `/11` day (also `/0`-`/8` for coarser units).
  `+`/empty = CE, `-` = BCE, use at least 4 digits, append `/J` for Julian.
  QS 3.0 makes the leading `+` optional; QS 2.0 requires it.
- **Quantity**: `amount~tolerance` (e.g. `-80~1.5`) or
  `amount[lower,upper]` (e.g. `1.2[-12.5,-7.5]`), optional unit `Uxxxx`.
  No spaces.
- `somevalue`/`novalue` must be unquoted. **They do not work inside
  CREATE/LAST item creation** - use placeholder items
  Q108474139 (novalue) / Q53569537 (somevalue) instead.

### Qualifiers

After the main value, add `property|value` pairs:

```
Q41577083|P570|+1600-00-00T00:00:00Z/7|P1319|+1586-00-00T00:00:00Z/9
```

### References (sources)

Reference properties use `S` instead of `P`. Multiple pairs form one
reference group; prefix the first property of a new group with `!`.

```
Q22124656|P21|Q6581097|S143|Q24731821|S813|+2017-10-04T00:00:00Z/11
Q143|P220|"epo"|S248|Q14790|S813|+2014-10-31T00:00:00Z/11|!S248|Q75488338
```

Typical source properties: `S854` reference URL, `S248` stated in, `S813`
retrieved, `S143` imported from, `S1476` title (qualifier of the URL), `S887`
inferred from, `S1065` archive URL. Statements with an identical
property+value are not added twice, but extra references may be attached.

### Labels, descriptions, aliases, sitelinks

Use the command in place of the property; the value is a double-quoted string.

| Command | Effect | Example |
|---|---|---|
| `Len` | label in language `xx` | `Q340122|Lpl|"Cyprian Kamil Norwid"` |
| `Lmul` | label for **all** languages | `Q340122|Lmul|"Brandname"` |
| `Dfr` | description in language `xx` | `Q340122|Dde|"polnischer Dichter"` |
| `Aen` | alias in language `xx` | `Q340122|Aen|"Cyprjan Kamil Norvid"` |
| `Amul` | alias for all languages | `Q340122|Amul|"Brandname Inc."` |
| `Senwiki` | sitelink to a site | `Q340122|Senwiki|"Cyprian Norwid"` |

- QS 2.0: multiple aliases in one row use a quoted, pipe-separated value:
  `Q340122|Aen|"Cyprian Kamil Norwid|Cypryan Kamil Norvid"`. This does **not**
  work during item creation (QS2 limitation).
- QS 3.0: multiple aliases go in separate columns:
  `Q1001|Aen|"Gandhi"|"Mohandas K Gandhi"|"M. K. Gandhi"`.
- Removal: empty string value - `Q340122|Len|""` (or `-Q340122|Aen|"alias"`
  for aliases).
- Only labels and aliases accept `mul`; descriptions are per-language only.
  `Lmul` sets a default label for every language - ideal for proper nouns
  (names, brands) that are not translated, which is why person-creation
  batches set `Lmul` **and** explicit per-language labels.

### Item creation

```
CREATE
LAST|Lmul|"Jane Doe"
LAST|Len|"Jane Doe"
LAST|Den|"person"
LAST|P31|Q5
```

`LAST` refers to the most recently created item. `CREATE_PROPERTY|string`
creates a property (Wikidata restricts this; mainly for other Wikibase
instances).

### Merging (QS 2.0 only)

```
MERGE|Q1|Q2     # Q2 is redirected into Q1
```

### Removal

- By value: prefix `-` - `-Q4115189|P31|Q1`.
- By statement ID: `-STATEMENT|Q1$00000000-0000-0000-0000-000000000000`.
- Year-precision dates may be stored as `00-00` or `01-01`; try both.
- QS 3.0 removes single qualifiers/references without touching the statement:
  `REMOVE_QUAL|Qid|Pid|value|QalPid|QalValue`,
  `REMOVE_REF|Qid|Pid|value|SPid|SValue`, and `REMOVE_REF_BLOCK` for a whole
  reference group.

### QS 3.0-only commands

```
Q2513|P856|"https://hubblesite.org/"|R+         # rank: R+/Rpreferred, R0/Rnormal, R-/Rdeprecated
Q2513|P10565|"68143"|R-|P2241|Q21441764         # rank + qualifier
+Q6454|P6|Q3160150|P580|+1959-03-15T00:00:00Z/11|P582|+1969-03-15T00:00:00Z/11  # force duplicate
SWITCH_VALUE|Q1774|P2046|2461U712226|950.2U232291
SWITCH_PROPERTY|Q40269|P18|"Aerial view of the point of Porto Alegre.jpg"|P8592
SWITCH_PROPERTY_AND_VALUE|Qid|Pid|value|newPid|newValue
```

### Comments / edit summaries

```
Q8023|P18|"Nelson Mandela 1994.jpg"|/* Add image to Nelson Mandela */
```

## Input format 2: CSV (V2)

A header row plus one row per entity. First column is `qid` (empty = create).
`P1234` starts a statement; `qal1234` adds a qualifier; `S1234` starts a
reference, `s1234` adds to the current reference; `Len`/`Dfr`/`Ade`/`Senwiki`
set label/description/alias/sitelink; `#` sets the edit summary. Prefix a
column with `-` to remove. Strings need double (or triple) quotes; double
quotes inside strings are doubled (`""`).

```
qid,P31,Len,Den,P18,qal373
, Q5, Regina Phalange, fictional character, "Regina.jpg", Q42
Q4115189,Q36180,Douglas Adams,author,"Douglas Adams.jpg",
```

## Running a batch

1. **Web UI.** `quickstatements.toolforge.org` (QS 2) or
   `quickstatements.toolforge.org` (QS 3). Log in with OAuth
   (autoconfirmed account). "New batch" -> paste V1 commands or CSV ->
   preview -> run. QS 3 groups consecutive commands on the same entity into
   one edit; toggle it off with "Do not combine commands".
2. **Background / batch mode (QS 2).** "Run in background" executes from a
   server: you get a unique batch URL with DONE/ERROR/INIT/RUN counters, can
   STOP, and can roll back via EditGroups. Use normal mode for ~10 or fewer
   statements; ~25k simple statements is a rough batch-size ceiling.
3. **By URL.** Encode commands (newline -> `||`, then URL-encode) into:
   - QS 2.0: `https://quickstatements.toolforge.org/#/v1=...`
   - QS 3.0: `https://quickstatements.toolforge.org/#/v1=...`
     (dev: `https://qs-dev.toolforge.org/#/v1=...`)
   Commons templates like {{Creator}} and {{Artwork}} use this trick.
4. **API (QS 2.0).** `POST https://quickstatements.toolforge.org/api.php?action=import`
   with `username`, `token`, `data` (the commands), `format=v1` (or `csv`),
   `submit=1`, `openpage=1`, `batchname`, and `site` (`commons` for SDC).
   Your token is shown on your QS user page; you must have run one
   server-side batch manually before the token works.
   Response JSON contains `batch_id` on success.

## Limitations

- **QS 2.0 cannot**: set ranks, force duplicates, remove a single
  qualifier/reference, switch values, choose a calendar, set coordinate
  precision/globe, edit redirected items, add a second identical
  statement, update badges, create lexemes, or mark edits as bot edits.
  It does not honor maxlag.
- **QS 3.0 cannot** (Wikibase REST API dependency): edit lexemes, edit
  Commons Structured Data, or merge items.

## Best practices & guardrails

- Experiment on the **Wikidata Sandbox (Q4115189)**; use a test.wikidata
  instance where available.
- Search before `CREATE` - duplicate items are the #1 problem.
- Reference every statement per Help:Sources (identifiers are the
  exception).
- Large or controversial runs need the Wikidata:Bots approval process.
- A batch is one edit group: review it, and if it goes wrong, revert the
  whole edit group with EditGroups rather than hand-fixing.
- The tool does not create a useful error message for every failure; after a
  run, inspect ERROR lines, fix only those commands, and re-run the remainder.

## Related tools

- **New-Q5** (`https://new-q5.toolforge.org/`) - generates a V1 batch that
  creates or updates one person item (multilingual labels, P31/P21/P735/P734,
  approximate dates, references). Listed under "Tools that export to
  QuickStatements" in the Wikidata help.
- **Minefield** (`https://hay.toolforge.org/minefield/`) - converts Commons
  file titles to M IDs for QS 2.0 SDC batches.
- **OpenRefine** - exports reconciled data directly to QS format.
- **Zotero (zotkat)** - reference collections exported to QS batches.
- **topictagger** - finds missing main subject (P921) statements.
- See the `wikimedia-commons-sdc` skill for QS 2.0 on Commons M IDs.
