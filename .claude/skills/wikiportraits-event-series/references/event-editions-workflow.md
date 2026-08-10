# Worked example: creating event edition items on Wikidata

Recurring events (conferences, film festivals) are modelled as one **series item** plus one
**edition item** per occurrence. This worked example shows the API strategy for building or
enriching such a set, learned from the **Internetdagarna** (`Q10536300`) and
**International Film Festival Rotterdam** (`Q1666554`) series.

## Step-by-step API strategy

| Step | Task | Best method | Why |
|---|---|---|---|
| 1 | Find existing editions and gaps | **SPARQL** (`P179`, `P393`, `P155`/`P156`) | One graph query replaces dozens of entity lookups; lists the whole chain with numbers |
| 2 | Inspect a few known items | **Action API** `wbgetentities` (batch of 50) | ~200 ms per batch vs 1–30 s for SPARQL; no auth needed |
| 3 | Probe the candidate edition URL | plain **HTTP GET** (check status 200) | Festival sites restructure URLs; never record a URL pattern blindly |
| 4 | Find archived snapshots for references | **Wayback Machine CDX/Availability** API | Older editions' live pages are usually 404; cite a snapshot that actually loads |
| 5 | Verify the Commons category exists | **Action API** `prop=pageprops` / `list=categorymembers` (ns 14) | Cheap existence probe before linking `P373` or creating the category |
| 6 | Create/update items | **Pywikibot** (or `wbcreateclaim`/`wbeditentity`) | For 20–30 items: built-in throttling, conflict detection, edit summaries |
| 7 | Re-verify the whole chain | **SPARQL** ordered by `P393` | Confirms no gaps and that `P155`↔`P156` agree in both directions |

## Edition item template

| property | value | notes |
|---|---|---|
| `P31` instance of | `Q108095628` conference edition / `Q27787439` film festival edition | use the edition class matching the event type |
| `P179` part of the series | the series QID (`Q10536300`, `Q1666554`) | |
| `P393` edition number | `1`, `14`, `43`, ... | datatype is **string**; verify official numbering |
| `P585` point in time | the year, precision `year` | carry a reference |
| `P276` location | venue city (`Q1754` Stockholm, `Q34370` Rotterdam) | |
| `P17` country | `Q34` Sweden, `Q55` Netherlands | |
| `P155` follows / `P156` followed by | previous / next edition QID | build the full chain |
| `P856` official website | `https://iffr.com/en/film?edition=iffr-{year}` | qualifiers `P407 = Q1860` (English), `P813` (retrieved) |
| `P973` described at URL | same canonical URL when `P856` is not used | same `P407` qualifier pattern |
| `P373` Commons category | e.g. `Internetdagarna 2013` | only when the category exists |

Labels/aliases/descriptions follow the series convention (e.g. `Internetdagarna 2013`,
`43rd International Film Festival Rotterdam`, alias `IFFR 2014`).

## Reference patterns

- **Dead official page** → cite a Wayback Machine snapshot as the `P585`/`P856`
  reference; confirm the snapshot loads.
- **Wikipedia article data** → imported-from-Wikimedia-project pattern:
  `P143` = the language Wikipedia (e.g. `Q169514` Swedish Wikipedia),
  `P813` = retrieved, `P4656` = the article oldid permalink
  (e.g. `https://sv.wikipedia.org/w/index.php?title=Internetdagarna&oldid=46115337`),
  as used on `Q10536300`.

## Pitfalls and lessons learned

1. **P155/P156 direction** — `P155` = *follows* (previous), `P156` = *followed by* (next).
   Reversing breaks the chain; verify both directions.
2. **P393 is a string, numbering ≠ year arithmetic** — Internetdagarna 2012 is the *13th*
   edition. Derive numbering from official sources, never from `year - start_year + 1`.
3. **Sequence-link integrity** — after writing `P155`/`P156` on one item, re-check the
   neighbours agree (`A.P156` must equal `B.P155`).
4. **Verify with SPARQL** — query editions ordered by `P393`; look for gaps and
   "no sequence claims" errors.
5. **Idempotency** — add only missing claims; run scripts in simulate/dry-run mode first;
   prefer add-if-missing over remove-and-replace.
6. **Retries** — wrap edits with retry-on-`maxlag`/transient-failure logic, small delay
   between edits.
7. **Don't trust live sites blindly** — probe candidate URLs (status 200) before recording.
