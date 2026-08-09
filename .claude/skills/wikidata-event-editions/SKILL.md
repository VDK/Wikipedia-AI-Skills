---
name: wikidata-event-editions
description: Create and enrich Wikidata edition items for recurring events (conferences, film festivals) — P31/P179/P393/P585, P155/P156 sequence chains, official website URLs with language qualifiers, references, and SPARQL chain verification
license: MIT
compatibility: opencode
depends_on: [wikidata, pywikibot, wikimedia-api-access, wikimedia-api-strategy]
skill_discovery_hints:
  - keywords: ["event edition", "edition item", "film festival edition", "conference edition", "edition number"]
  - keywords: ["P393", "P155", "P156", "follows", "followed by", "P179 part of series"]
  - keywords: ["Internetdagarna", "IFFR", "Rotterdam film festival", "conference series editions", "create edition item"]
last_verified: 2026-06-24
---

# Wikidata event editions

Create and enrich **edition items** for recurring events (conferences, film festivals):
one item per occurrence, chained chronologically and linked to the series item. Applies
to work such as the Internetdagarna (`Q10536300`) and International Film Festival
Rotterdam (`Q1666554`) edition sets.

## Edition item template

Give every edition item this claim set:

| property | value |
|---|---|
| `P31` instance of | edition class (`Q108095628` conference edition / `Q27787439` film festival edition) |
| `P179` part of | the series QID (`Q10536300`, `Q1666554`, ...) |
| `P393` edition number | official number (datatype **string**; see numbering pitfall) |
| `P585` point in time | the year, precision `year`, with reference |
| `P276` location / `P17` country | venue city (`Q1754` Stockholm, `Q34370` Rotterdam) / country |
| `P155` follows / `P156` followed by | previous / next edition QID (build the full chain) |
| `P856` official website | edition page URL, qualifiers `P407` English (`Q1860`) + `P813` retrieved |
| `P973` described at URL | the same canonical URL when `P856` is not used |
| `P373` Commons category | matching category name, only when it exists |

Add labels, aliases and descriptions following the series convention (e.g.
`Internetdagarna 2013`, `43rd International Film Festival Rotterdam`, alias `IFFR 2014`).
Reuse the series item's existing conventions (`P31` class, `P276`, `P17`, `P373`).

## Reference patterns

- When the live page is gone (404), cite a **Wayback Machine snapshot** of the official
  edition page as the `P585`/`P856` reference; confirm the snapshot actually loads.
- For general event data cite the Wikipedia article with the
  **imported-from-Wikimedia-project** pattern: `P143` = the language Wikipedia
  (e.g. `Q169514` Swedish Wikipedia), `P813` = retrieved, `P4656` = the article
  **oldid permalink** (e.g. `...title=Internetdagarna&oldid=46115337`) — as used on the
  series item `Q10536300`.

## Verify the chain

After editing, re-verify with **SPARQL**: list all editions ordered by `P393` and confirm
each item's `P155` equals its predecessor's `P156`, with no gaps and no
"no sequence claims" errors. Idempotency matters: add only missing claims and run scripts
in a dry-run/simulate mode before the real edit.

## Pitfalls

- `P155` = *follows* (previous); `P156` = *followed by* (next). Reversing them silently
  breaks the chain; verify both directions.
- `P393` numbering does **not** equal `year - start_year + 1` — Internetdagarna 2012 is
  the *13th* edition. Derive numbering from official/archived sources.
- After writing a sequence link on one item, re-check that both neighbours agree
  (`A.P156` must equal `B.P155`).
- Probe candidate edition URLs (HTTP status 200) before recording them; festival sites
  restructure URLs frequently.

## References

- **`references/event-editions-workflow.md`** — the detailed step-by-step API strategy
  (SPARQL → `wbgetentities` → URL probes → Wayback → Pywikibot → SPARQL), the full
  edition template, reference patterns and the lessons learned.
