# Flickr account → Commons: deduping already-transferred files

How to find which photos of a Flickr account are already on Commons (so a batch
upload only contains what is missing), and how to keep the back-categorization
of those files into the account's stream category idempotent. Production
pattern from the 2026 flickr_* staging work (see `workspace/backfill_*`,
`workspace/flickr_data_gathering_report.md`).

## The dedupe signal stack (in order of strength)

1. **SPARQL / QLever** — Commons structured data. Strongest signal when the
   creator metadata is set.
   - By author name string (`p:P170/pq:P2093 "re:publica"`) — the completeness
     net; catches uploads where the author is plain wikitext.
   - By Flickr user id (`p:P170/pq:P3267 "<NSID>"`) — the precise subset.
   - Both optionally joined to the origin triple
     (`p:P7482/ps:P7482 wd:Q74228490; pq:P137 wd:Q103204; pq:P973 ?url`) whose
     `?url` is the Flickr photo page.
   - Endpoint: `https://qlever.dev/api/wikimedia-commons`
     (`schema:url ?page` returns `.../Special:FilePath/<title>` — parse that to
     get `File:` titles).
   - **Cannot** be category-filtered inside the query — post-filter results
     against the category's current member list instead.
2. **Account category** — enumerate
   `Category:Files from <account> Flickr stream` (or `Category:Photographs by
   <account>`) via `list=categorymembers`; photo ids are in the filenames
   (`Title (<id>).jpg`).
3. **`insource:` search** — `insource:"flickr.com/photos/<nsid>"` (NSID form
   that new uploads keep) **and** `insource:"flickr.com/<path_alias>/"` (legacy
   alias form, e.g. `insource:"flickr.com/newamerica/"`). Union both.
4. **`-incategory:"..."` exclusion** — negate the stream category to drop files
   already back-categorized, so the search returns exactly "files still needing
   the category":

   ```
   insource:"flickr.com/photos/<nsid>" -incategory:"Files from <account> Flickr stream"
   ```

   - `incategory:` matches **direct members only**; it does **not** recurse
     into subcategories. Use `deepcat:"<Category>"` for a recursive subtree.
   - The Commons search API caps pagination at **10,000 results** (`sroffset`
     past 10000 returns empty). For accounts with more matches, partition the
     search per top-level `deepcat:` subcategory of the subject tree and union,
     plus the plain uncapped query as a catch-all (used for re:publica, 14,653
     matches).
5. **`intitle:"<photo id>"`** — confirm a single specific photo.

## Back-categorize the already-transferred files (don't skip them)

Files already on Commons from an account whose stream category exists should be
added to it (`appendtext` `[[Category:Files from <account> Flickr stream]]`,
bot like `1VeertjeBot`), otherwise the category undercounts the true transfer
(e.g. Collision had 2,465 on-Commons files flagged but the category held only
817).

## Making the back-fill idempotent (re-runs don't double-append)

- **Discovery**: `-incategory:"Files from <account> Flickr stream"` in the
  search term excludes already-categorized files; SPARQL results are
  post-filtered against the category's current member list.
- **Commit**: record every edited title in a JSON checkpoint file
  (`backfill_checkpoint.json`) and skip recorded titles on restart.
- A duplicate category line in the wikitext is harmless (MediaWiki
  deduplicates categories), but the two mechanisms above keep runs clean and
  fast.

## Concrete numbers (2026-06-24 four-account back-fill)

| account | stream-cat files (discovery) | DB on-Commons (old) |
|---|---|---|
| Web Summit Rio | 10,215 | 9,580 |
| Lift Conference | 7,306 | 7,354 |
| NEXT Conference | 6,174 | 1,252 |
| re:publica | 14,762 | 14,452 |

The NEXT Conference DB figure (1,252) was a large undercount — Commons actually
has ~6,174 files referencing the account's NSID URL; the stream category count
is authoritative.

## Example SPARQL (QLever)

```sparql
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX ps: <http://www.wikidata.org/prop/statement/>
PREFIX pq: <http://www.wikidata.org/prop/qualifier/>
PREFIX schema: <http://schema.org/>
SELECT DISTINCT ?page WHERE {
  { ?file p:P7482 [ ps:P7482 wd:Q74228490 ; pq:P137 wd:Q103204 ; pq:P973 ?url ] .
    FILTER(CONTAINS(STR(?url), "flickr.com/photos/<NSID>")) }
  UNION
  { ?file p:P170 [ pq:P2093 "<account name>" ] . }
  ?file schema:url ?page .
}
```
