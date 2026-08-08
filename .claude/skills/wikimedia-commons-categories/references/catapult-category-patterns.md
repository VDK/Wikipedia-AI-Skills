# Catapult category patterns - deriving Commons categories from Wikidata

> **Source of truth:** this reference distills the production logic of the
> **Catapult** gadget (`github.com/VDK/Catapult`, live as
> `User:1Veertje/Catapult` on Wikidata, by Vera de Kok). Catapult helps create
> and disambiguate Commons categories from a Wikidata item. The rules below are
> exactly what `app.js` implements (see `generateCategoryCandidates`,
> `occupationName`, `countryPhrase`, `makeDisambiguationOptions`, and the
> `mappings.json` tables), and they have been field-tested on thousands of
> person categories. If the live gadget and this document ever disagree, the
> gadget wins; report the drift back here.

## The core pattern

Commons stores *people by profession and nationality* in categories named:

```
Category:<occupation plural> from <country> by name
```

The `by name` suffix is the Commons convention for a category that lists its
members alphabetically by surname. Catapult's job is to figure out which such
category (or categories) a Wikidata person belongs in, using only the item's
claims:

| Wikidata claim | Property | Used for |
|---|---|---|
| occupation | P106 | the `<occupation plural>` part |
| field of work | P101 | an extra occupation-ish part |
| country of citizenship | P27 | the `<country>` part |
| sex or gender | P21 | `male` / `female` modifiers |
| date of birth / death | P569 / P570 | century and life-years modifiers |
| Commons category | P373 (on the *occupation/country item*) | explicit category name override |

## The candidate matrix

For every occupation entry (up to 8) x every country (up to 6), Catapult
proposes a ranked list. Each base name is also proposed with ` by name`
appended, so the real matrix doubles. For occupation `vocalists`, country
`the Netherlands`, gender `female`, century `20th-century`:

| Reason | Example candidate |
|---|---|
| occupation + country | `Vocalists from the Netherlands` |
| occupation + country + by name | `Vocalists from the Netherlands by name` |
| gendered occupation + country | `Female vocalists from the Netherlands` |
| gendered occupation + country + by name | `Female vocalists from the Netherlands by name` |
| gender + occupation + country | `female vocalists from the Netherlands` |
| gender + occupation + country + by name | `female vocalists from the Netherlands by name` |
| century + occupation + country | `20th-century vocalists from the Netherlands` |
| century + occupation + country + by name | `20th-century vocalists from the Netherlands by name` |
| century + gendered occupation + country | `20th-century female vocalists from the Netherlands` |
| century + gender + occupation + country | `20th-century female vocalists from the Netherlands` |
| occupation (bare, last) | `vocalists` |
| employer faculty | e.g. `Radboud University Nijmegen faculty` |

Notes:

- `gendered occupation` is only emitted when a gendered form exists: Catapult
  knows exactly one, `businesspeople` -> `businessmen`/`businesswomen`.
  Otherwise the `gender + occupation` form is used.
- The bare `occupation` candidate is *last* and deliberately scores lowest:
  generic occupation categories such as `Vocalists` are usually wrong targets
  for a person (they should live in the country-scoped category instead).
- Faculty categories come from the employer claim (P108) resolved via an
  employer->category table; they are proposed but never the top pick.

**Casing:** candidate *names* are stored lowercase internally (`occupationName`
applies `lcfirst`), and the final category title is capitalized with `ucfirst`
at creation time (`normalizeCategoryTitle`). So the internal candidate
`vocalists from the Netherlands` becomes the category `Category:Vocalists from
the Netherlands`. The tables above show the final (capitalized) form; the
script prints the final form too.

## Occupation name resolution (P106 value -> category fragment)

For each P106 item QID, Catapult derives a category fragment:

1. **Explicit mapping** `occupationCategoryByQid[QID]` wins. e.g.
   `Q177220 -> "vocalists"`, `Q2526255 -> "directors"`.
2. Otherwise the occupation item's own **Commons category** claim (P373).
3. Otherwise the item's **English label**.
4. Otherwise the bare QID (last resort).

Then, in order:

- strip a leading `Category:` prefix, trim, collapse whitespace;
- **pluralize** (rule below);
- apply `occupationCategoryReplacements` (e.g. `Singers -> vocalists`,
  `Businesspersons -> businesspeople`);
- **lowercase the first letter** (`lcfirst`), because these fragments are used
  mid-name ("Vocalists from the Netherlands" keeps a capital only because it is
  the first word of the candidate).

### Parent fallbacks (subclass / instance)

A P106 value often points at a narrow occupation. Catapult also walks:

- `P279` (subclass of) parents of the occupation item, and
- `P31` (instance of) parents,

and adds those category names as **fallback** entries (deduplicated against
the direct name). The fallback entries produce the same candidate matrix but
rank below the direct ones, and are dropped entirely if they resolve to
generic names: `workers`, `professions`, `professionals`,
`people by occupation` are discarded.

### pluralize() rules (exactly as implemented)

| Label | Result |
|---|---|
| ends in `person` | `people` (case-preserving: `Person` -> `People`) |
| already ends in `s` | unchanged |
| ends in `ist` / `ian` / `er` | +`s` (`vocalist` -> `vocalists`) |
| ends in `y` | `ies` (`secretary` -> `secretaries`) |
| anything else | +`s` |

## Country phrase resolution (P27 value -> "<country>" fragment)

For each P27 value QID:

1. **Explicit mapping** `countryPhraseByQid[QID]` wins (e.g.
   `Q55 -> "the Netherlands"`, `Q145 -> "the United Kingdom"`).
2. Otherwise the country item's **P1813 short name** (en monolingual text).
3. Otherwise its **P373 Commons category** name.
4. Otherwise its **English label** (or QID).

Then `normalizeCountryPhrase` applies (replacements table first, then the
definite-article rules):

| Rule | Example |
|---|---|
| `countryNameReplacements` table | `Czechia` -> `the Czech Republic`, `Kingdom of the Netherlands` -> `the Netherlands`, `United States of America` -> `the United States` |
| starts with `United ` | -> `the United States`, `the United Kingdom` |
| `Bahamas`, `Comoros`, `Gambia`, `Maldives`, `Philippines`, `Seychelles` | -> `the Bahamas`, ... |
| `Central African Republic`, `Dominican Republic`, `Czech Republic` | -> `the <...> Republic` |
| `Marshall Islands`, `Solomon Islands` | -> `the <...> Islands` |

The phrase is used *without* `lcfirst` because the country always appears
after "from " in the candidate; Catapult renders it exactly as in the table
("from the Netherlands", "from Germany").

## Modifiers

**Gender** (`P21`): exactly `male` (Q6581097) / `female` (Q6581072) produce the
`genderWord`. Only `businesspeople` gets a gendered occupation form.

**Century** (`P569`/`P570`): computed as `ordinal(ceil(basisYear/100))-century`,
e.g. `20th-century`. `basisYear` = death year if present, else birth year + 60
if the person was born more than 120 years ago (historical figures), else the
current year. Examples: born 1962, died 2024 -> `21st-century`; born 1900,
living -> `20th-century`.

## Ranking the candidates

`bestCategoryCandidate` sorts by (all descending):

1. `depth` - a heuristic: +10 if the name contains `from`, +1 for
   `male`/`female`, +1 for a `Nth-century`, -10 if the candidate is the bare
   occupation.
2. gendered occupation preferred;
3. generic fallback *de*preferred;
4. ` by name` *de*preferred.

So for a living Dutch female vocalist, the top pick is
`Female vocalists from the Netherlands` (not `... by name` - the by-name form
is only used when the plain form already exists, or on explicit choice). The
`by name` variant exists so the person category can be created when the
country-scoped category already has content.

## Probing existence on Commons

Catapult checks every candidate with a batched `action=query`:

```js
const params = {
  action: 'query',
  prop: 'info|pageprops',
  titles: batch.join('|'),   // up to 50 titles per batch
  formatversion: 2,
  format: 'json'
};
```

For each page: `exists` (page not missing), `redirect` (the `redirect` flag),
and `wikibaseItem` from `pageprops.wikibase_item`. Normalized titles are mapped
back so input casing matches.

**Namespace gotcha:** the API resolves a bare title in the *main* namespace
(ns=0). Categories live in ns=14, so every title must be sent as
`Category:<name>` (`normalizeCategoryTitle` prepends the prefix). A probe that
omits the prefix silently reports every candidate as missing - the bundled
script prefixes titles itself, but any hand-written probe must do the same.

Categories that exist but carry no
`wikibase_item` are resolved through a second `wbgetentities` call keyed on the
Commons sitelink (`sites: commonswiki`, `redirects: yes`) - needed because a
pageprops probe does not follow category redirects to their item.

**What the flags mean in practice:**

| State | Meaning |
|---|---|
| exists, no wikibase_item | existing category not linked to Wikidata - safe to reuse / link |
| exists, wikibase_item = subject item | the category already *is* this person's - done |
| exists, wikibase_item = other item | **name collision** - do not touch; disambiguate instead |
| redirect | the category is a redirect - resolve the target before deciding |
| missing | free to create |

## Disambiguation

When the desired category name already exists but is tied to a *different*
Wikidata item (a homonym), Catapult offers parenthesized disambiguation
categories:

- `Category:<name> (<occupation>)` - e.g. `Category:John Smith (vocalist)`,
  one option per P106 value, most-specific label first (sorted by word count,
  then length, then alphabetically). `university teacher` is skipped as too
  generic.
- `Category:<name> (<birth>-<death>)` - e.g. `Category:John Smith (1940-1999)`,
  used when the person has no usable occupation.
- `Category:<name> (born <year>)` - when only a birth year is known.

If the base category *itself* is already a disambiguation category (it links to
a `Category:... (disambiguation)` page, or has suffixed subcategories like
`Category:Smith (vocalist)`), Catapult proposes reusing/creating the matching
suffixed category instead of creating a new bare one. It finds those via
`list=search`, `srnamespace=14`, `srsearch=intitle:"<base> ("`.

## Mapping tables (mappings.json)

All hand-tuned data lives in one JSON file, loaded at runtime
(`CONFIG.mappingPage`). The keys are exactly:

| Key | Type | Purpose |
|---|---|---|
| `occupationCategoryByQid` | object | QID -> plural category fragment (overrides label/P373) |
| `occupationCategoryByRelatedQid` | object | QID -> category fragment for P279/P31 parents and P101 |
| `occupationDisambiguationByQid` | object | QID -> singular disambiguation label (`Q177220` -> `vocalist`) |
| `occupationCategoryReplacements` | object | normalize label -> canonical plural (`Singers` -> `vocalists`) |
| `countryPhraseByQid` | object | QID -> country phrase incl. definite article |
| `countryNameReplacements` | object | canonicalize country names (`Netherlands` -> `the Netherlands`) |
| `categoryBlacklist` | array | names that must never be proposed (e.g. `Positions`, `Occupations`) |

**Gotcha (production):** `applyMappings` merges config with
`$.extend({}, CONFIG[key], mappings[key])`, which silently turns an *array*
into an object (`{'0': 'Positions', '1': 'Occupations'}`). `categoryBlacklist`
is an array, so it must be copied with `slice()` and checked with
`Array.isArray`; if it ever becomes an object, `isBlacklistedCategoryName`
throws (`.some` on an object) and the whole panel hangs on the loading message.

## Production lessons (field-tested)

- **Always check `wikibase_item` before proposing to reuse an existing
  category.** A category that exists but belongs to a *different* item is a
  collision; creating "this person's" category under that name would conflate
  two subjects.
- **Prefer the country-scoped category over the bare occupation category.**
  Commons categorizes people primarily by
  `<occupation> from <country>`; the bare `occupation` candidate is a fallback,
  and generic containers (`Occupations`, `Positions`) are blacklisted outright.
- **The `by name` suffix is a *person* convention.** It signals an alphabetic
  surname index. Never append it to non-person categories.
- **Definite articles matter and are inconsistent.** It is `the Netherlands`,
  `the United States`, `the Bahamas` but plain `Germany`, `France`, `India`.
  Maintain the `countryPhraseByQid`/`countryNameReplacements` tables rather
  than guessing; a wrongly-articled name creates a near-duplicate category.
- **Pluralization is a category-naming skill.** `vocalist -> vocalists` but
  `secretary -> secretaries`, `person -> people`. Wrong plurals create orphan
  categories that a later cleanup has to merge.
- **Batch the API probes (50 titles/call) and map normalized titles back.**
  Probing one title at a time is slow and the API's normalization will break
  exact-match lookups unless you track `normalized[to] = from`.
- **Deprecated claims and emoji-flag claims (P3831 = Q28840786) are filtered
  out** before any P106/P27 value is used; preferred-rank claims win over
  normal ones.
