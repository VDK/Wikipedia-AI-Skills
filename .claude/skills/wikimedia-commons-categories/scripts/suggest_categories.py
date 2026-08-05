#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Derive Wikimedia Commons category names from a Wikidata item.

A faithful Python port of the category-building logic of the Catapult gadget
(https://github.com/VDK/Catapult, User:1Veertje/Catapult on Wikidata), which
propels data from Wikidata to Commons by assisting with the creation and
disambiguation of Commons categories.

The core idea: a *person* category on Commons follows the pattern

    Category:<occupation plural> from <country> by name

e.g. "Category:Vocalists from the Netherlands by name". The occupation and
country phrases are derived from Wikidata claims (P106 occupation, P27 country
of citizenship) via a small mapping table plus normalization rules; "by name"
is the Commons convention for categories that index people alphabetically by
surname.

Run `python suggest_categories.py --item Q123 --check` to generate candidates
for a live item and probe which category names already exist on Commons.
"""

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from functools import cmp_to_key

UA = (
    "OpenHands/wikimedia-commons-categories (category suggestion tool; "
    "contact: skill author)"
)
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"


# ---------------------------------------------------------------------------
# Small text helpers (ported from Catapult's Util-style helpers)
# ---------------------------------------------------------------------------

def lcfirst(text):
    if not text:
        return text
    return text[0].lower() + text[1:]


def ucfirst(text):
    if not text:
        return text
    return text[0].upper() + text[1:]


def collapse_ws(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def strip_category_prefix(name):
    return re.sub(r"^Category:", "", str(name or ""), flags=re.I).strip()


def ordinal(number):
    """1 -> '1st', 22 -> '22nd', 13 -> '13th' (matches Catapult's ordinal())."""
    number = int(number)
    suffix = "th"
    if number % 100 < 11 or number % 100 > 13:
        if number % 10 == 1:
            suffix = "st"
        elif number % 10 == 2:
            suffix = "nd"
        elif number % 10 == 3:
            suffix = "rd"
    return "%d%s" % (number, suffix)


def pluralize(name):
    """Pluralize an occupation label the way Commons category names want it.

    Port of Catapult's pluralize(): 'person' -> 'people' (case-preserving),
    labels already ending in 's' stay, '-ist/-ian/-er' take '-s', '-y' -> '-ies'.
    """
    name = str(name or "")
    if re.search(r"person$", name, re.I):
        return re.sub(r"person$",
                      lambda m: "People" if m.group(0)[:1].isupper() else "people",
                      name, flags=re.I)
    if re.search(r"people$", name, re.I):
        return name
    if re.search(r"s$", name, re.I):
        return name
    if re.search(r"(ist|ian|er)$", name, re.I):
        return name + "s"
    if re.search(r"y$", name, re.I):
        return re.sub(r"y$", "ies", name, flags=re.I)
    return name + "s"


def add_definite_article(name):
    name = str(name or "")
    return name if re.match(r"^the\s", name, re.I) else "the " + name


# ---------------------------------------------------------------------------
# Wikidata entity access (wbgetentities-style dicts)
# ---------------------------------------------------------------------------

def claim_value_ids(entity, prop):
    """Item-value ids for a property (P106 -> [Q937857, ...]).

    Deprecated ranks and 'emoji flag' claims (P3831 = Q28840786) are dropped,
    and preferred-rank claims win, exactly like Catapult's bestClaims().
    """
    claims = (entity or {}).get("claims", {}).get(prop) or []
    kept = [c for c in claims
            if c.get("rank") != "deprecated" and not _is_emoji_flag_claim(c)]
    preferred = [c for c in kept if c.get("rank") == "preferred"]
    chosen = preferred or kept
    ids = []
    for c in chosen:
        value = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(value, dict) and value.get("id"):
            ids.append(value["id"])
    return ids


def _is_emoji_flag_claim(claim):
    roles = (claim or {}).get("qualifiers", {}).get("P3831") or []
    for q in roles:
        value = q.get("datavalue", {}).get("value")
        if isinstance(value, dict) and value.get("id") == "Q28840786":
            return True
    return False


def string_claim(entity, prop):
    """First non-deprecated string value of a property (time or text)."""
    claims = (entity or {}).get("claims", {}).get(prop) or []
    for c in claims:
        if c.get("rank") == "deprecated":
            continue
        value = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(value, str):
            return value
    return ""


def english_label(entity, fallback_qid=""):
    if not entity:
        return fallback_qid
    en = (entity.get("labels") or {}).get("en") or {}
    if isinstance(en, dict) and en.get("value"):
        return en["value"]
    return fallback_qid


def short_name_monolingual(entity):
    """First en monolingual text of P1813 (short name), like Catapult."""
    claims = (entity or {}).get("claims", {}).get("P1813") or []
    for c in claims:
        if c.get("rank") == "deprecated":
            continue
        value = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(value, dict) and value.get("language") == "en" and value.get("text"):
            return value["text"]
    return ""


# ---------------------------------------------------------------------------
# Occupation / country phrase derivation (ported from Catapult)
# ---------------------------------------------------------------------------

def normalize_occupation_category(name, replacements=None):
    name = collapse_ws(name)
    return (replacements or {}).get(name, name)


def normalize_country_phrase(name, country_name_replacements=None):
    name = collapse_ws(name)
    if country_name_replacements and name in country_name_replacements:
        return country_name_replacements[name]
    if re.match(r"^United\s", name):
        return add_definite_article(name)
    if re.match(r"^(Bahamas|Comoros|Gambia|Maldives|Philippines|Seychelles)$", name):
        return add_definite_article(name)
    if re.match(r"^(Central African|Dominican|Czech) Republic$", name):
        return add_definite_article(name)
    if re.match(r"^(Marshall|Solomon) Islands$", name):
        return add_definite_article(name)
    return name


def country_phrase(qid, related, cfg):
    """'Germany' -> 'Germany', 'United States' -> 'the United States', etc."""
    entity = related.get(qid) or {}
    override = cfg.get("countryPhraseByQid", {}).get(qid)
    if override:
        return override
    name = (
        short_name_monolingual(entity)
        or string_claim(entity, "P373")
        or english_label(entity, qid)
    )
    return normalize_country_phrase(
        strip_category_prefix(name), cfg.get("countryNameReplacements")
    )


def occupation_name(qid, related, cfg):
    """Pluralized, lowercased occupation category name for a P106 value.

    Resolution order: explicit mapping -> the occupation item's own Commons
    category (P373) -> English label -> QID. Then pluralize + replace.
    """
    entity = related.get(qid) or {}
    name = (
        cfg.get("occupationCategoryByQid", {}).get(qid)
        or string_claim(entity, "P373")
        or english_label(entity, qid)
    )
    name = strip_category_prefix(name)
    name = normalize_occupation_category(
        pluralize(name), cfg.get("occupationCategoryReplacements")
    )
    return lcfirst(name)


def occupation_parent_category_names(qid, prop, related, cfg):
    """Category names from P279/P31 parents of an occupation item."""
    entity = related.get(qid) or {}
    out = []
    for parent_qid in claim_value_ids(entity, prop):
        parent_entity = related.get(parent_qid) or {}
        parent_name = (cfg.get("occupationCategoryByRelatedQid", {}).get(parent_qid)
                       or english_label(parent_entity, ""))
        if parent_name:
            name = normalize_occupation_category(
                pluralize(parent_name), cfg.get("occupationCategoryReplacements")
            )
            if name:
                out.append(name)
    return out


def occupation_name_entries(qid, related, cfg):
    """Direct + fallback (subclass/instance parent) occupation names."""
    entries = []
    direct = occupation_name(qid, related, cfg)
    _add_occupation_entry(entries, direct, direct, False)
    for name in occupation_parent_category_names(qid, "P279", related, cfg):
        _add_occupation_entry(entries, name, direct, True)
    for name in occupation_parent_category_names(qid, "P31", related, cfg):
        _add_occupation_entry(entries, name, direct, True)
    return entries


def _add_occupation_entry(entries, name, source, is_fallback):
    if name and not any(e["name"] == name for e in entries):
        entries.append({
            "name": name,
            "sourceOccupation": source,
            "isFallback": bool(is_fallback),
        })


def field_of_work_category_entries(qid, cfg):
    name = cfg.get("occupationCategoryByRelatedQid", {}).get(qid, "")
    if not name:
        return []
    return [{"name": name, "sourceOccupation": name, "isFallback": False}]


def gender_word(sex_or_gender_ids, cfg):
    if cfg.get("items", {}).get("male") in sex_or_gender_ids:
        return "male"
    if cfg.get("items", {}).get("female") in sex_or_gender_ids:
        return "female"
    return ""


def gendered_occupation_category(occupation, gender):
    """'businesspeople' -> 'businessmen'/'businesswomen' (Catapult's only
    gendered occupation special case)."""
    if re.match(r"^businesspeople$", occupation or "", re.I):
        if gender == "male":
            return "businessmen"
        if gender == "female":
            return "businesswomen"
    return ""


def year_from_time_claim(entity, prop):
    value = string_claim(entity, prop)
    if not value:
        return None
    m = re.match(r"^([+-]\d{4,})", value)
    return abs(int(m.group(1))) if m else None


def active_century(birth_year, death_year, current_year=None):
    """'20th-century' style modifier from P569/P570.

    Uses death year if present; otherwise birth year if the person is clearly
    historical (born > 120 years ago), else the current century.
    """
    if current_year is None:
        current_year = 2026
    basis = None
    if death_year:
        basis = death_year
    elif birth_year:
        basis = birth_year + 60 if current_year - birth_year > 120 else current_year
    if not basis:
        return ""
    return ordinal(int(math.ceil(basis / 100.0))) + "-century"


def disambiguation_year_suffix(birth_year, death_year):
    if birth_year and death_year:
        return "%d-%d" % (birth_year, death_year)
    if birth_year:
        return "born %d" % birth_year
    return ""


# ---------------------------------------------------------------------------
# Candidate generation (ported from Catapult's generateCategoryCandidates)
# ---------------------------------------------------------------------------

def is_blacklisted_category_name(name, blacklist):
    if not isinstance(blacklist, list):
        return False
    normalized = strip_category_prefix(name).lower()
    return any(strip_category_prefix(e).lower() == normalized for e in blacklist)


def is_discarded_generic_occupation_name(name):
    return bool(re.match(
        r"^(?:workers|professions|professionals|people by occupation)$",
        str(name or "").strip(), re.I
    ))


def category_tree_depth(name, reason):
    depth = 0
    if re.search(r"\bfrom\b", name, re.I):
        depth += 10
    if re.search(r"\bmale\b|\bfemale\b", name, re.I):
        depth += 1
    if re.search(r"\d+(?:st|nd|rd|th)-century", name, re.I):
        depth += 1
    if re.search(r"\|occupation$", reason or ""):
        depth -= 10
    return depth


def add_candidate(candidates, name, reason, group_id, metadata=None):
    metadata = metadata or {}
    if not name:
        return
    name = collapse_ws(name)
    blacklist = metadata.get("_blacklist", [])
    if is_blacklisted_category_name(name, blacklist):
        return
    if is_blacklisted_category_name(
            metadata.get("occupation") or metadata.get("sourceOccupation"), blacklist):
        return
    if (metadata.get("isFallback")
            and is_discarded_generic_occupation_name(
                metadata.get("occupation") or name)):
        return
    if any(c["name"] == name for c in candidates):
        return
    candidates.append({
        "name": name,
        "reason": reason,
        "groupId": group_id or name,
        "depth": category_tree_depth(name, reason),
        "stage": _candidate_stage(reason, metadata),
        "occupation": metadata.get("occupation", ""),
        "sourceOccupation": metadata.get("sourceOccupation", ""),
        "isFallback": bool(metadata.get("isFallback")),
        "isGenderedOccupation": bool(metadata.get("isGenderedOccupation")),
        "isByName": bool(metadata.get("isByName")),
        "exists": False,
    })


def _candidate_stage(reason, metadata):
    if metadata.get("isFallback"):
        return "fallback"
    if reason == "employer faculty":
        return "faculty"
    if "+ country" in reason:
        return "country"
    return "occupation"


def add_candidate_with_by_name(candidates, name, reason, group_id, metadata=None):
    add_candidate(candidates, name, reason, group_id, metadata)
    if name:
        meta = dict(metadata or {})
        meta["isByName"] = True
        add_candidate(candidates, name + " by name", reason + " + by name", group_id, meta)


def generate_category_candidates(context, cfg):
    """context: dict with occupationEntries, countries, gender, century,
    facultyCategoryNames. Returns candidates in Catapult's proposal order."""
    candidates = []
    blacklist = cfg.get("categoryBlacklist", [])

    for entry in context.get("occupationEntries", []):
        occupation = entry["name"]
        gendered = gendered_occupation_category(occupation, context.get("gender"))
        source = entry.get("sourceOccupation", occupation)
        base = {"occupation": occupation, "sourceOccupation": source,
                "isFallback": entry.get("isFallback"), "_blacklist": blacklist}

        for country in context.get("countries", []):
            group_id = occupation + "|from|" + country
            add_candidate_with_by_name(
                candidates, occupation + " from " + country,
                "occupation + country", group_id, dict(base))
            if gendered:
                add_candidate_with_by_name(
                    candidates, gendered + " from " + country,
                    "gendered occupation + country", group_id,
                    dict(base, isGenderedOccupation=True))
            if context.get("gender") and not gendered:
                add_candidate_with_by_name(
                    candidates, context["gender"] + " " + occupation + " from " + country,
                    "gender + occupation + country", group_id, dict(base))
            if context.get("century"):
                add_candidate_with_by_name(
                    candidates, context["century"] + " " + occupation + " from " + country,
                    "century + occupation + country", group_id, dict(base))
            if context.get("century") and gendered:
                add_candidate_with_by_name(
                    candidates, context["century"] + " " + gendered + " from " + country,
                    "century + gendered occupation + country", group_id,
                    dict(base, isGenderedOccupation=True))
            if context.get("century") and context.get("gender") and not gendered:
                add_candidate_with_by_name(
                    candidates,
                    context["century"] + " " + context["gender"] + " " + occupation
                    + " from " + country,
                    "century + gender + occupation + country", group_id, dict(base))

        add_candidate(candidates, occupation, "occupation",
                      occupation + "|occupation", dict(base))

    for name in context.get("facultyCategoryNames", []):
        add_candidate(candidates, name, "employer faculty", "faculty|" + name, {
            "occupation": name, "sourceOccupation": name, "isFallback": False,
            "_blacklist": blacklist,
        })

    return candidates


def _is_generic_fallback(candidate):
    return bool(
        candidate.get("isFallback")
        and is_discarded_generic_occupation_name(
            candidate.get("occupation") or candidate.get("name") or "")
    )


def best_category_candidate(candidates):
    """The candidate Catapult prefers to create/link.

    Sort key: deeper category tree first (country-based beats bare occupation),
    gendered occupations first, generic fallbacks and bare 'by name' last.
    """
    ranked = sorted(candidates, key=lambda c: (
        -c["depth"],
        -int(c["isGenderedOccupation"]),
        int(_is_generic_fallback(c)),
        int(c["isByName"]),
    ))
    return ranked[0] if ranked else None


def generic_fallback_covered_by_specific_fallback(candidate, candidates):
    if not _is_generic_fallback(candidate):
        return False
    return any(
        other is not candidate
        and other.get("exists")
        and not _is_generic_fallback(other)
        and "|from|" in other.get("groupId", "")
        for other in candidates
    )


def _candidate_covered_by_direct_occupation(candidate, candidates):
    if candidate.get("isFallback"):
        return False
    occupation = candidate.get("occupation")
    return any(
        other is not candidate
        and other.get("exists")
        and other.get("isFallback")
        and other.get("sourceOccupation") == occupation
        for other in candidates
    )


def first_existing_candidate(candidates):
    existing = [c for c in candidates
                if c.get("exists")
                and not _candidate_covered_by_direct_occupation(c, candidates)
                and not generic_fallback_covered_by_specific_fallback(c, candidates)]
    return best_category_candidate(existing) or (candidates[0] if candidates else None)


# ---------------------------------------------------------------------------
# Disambiguation options (ported from Catapult's makeDisambiguationOptions)
# ---------------------------------------------------------------------------

def occupation_disambiguation_name(qid, related, cfg):
    entity = related.get(qid) or {}
    name = (cfg.get("occupationDisambiguationByQid", {}).get(qid)
            or english_label(entity, qid))
    name = lcfirst(collapse_ws(strip_category_prefix(name)))
    if re.match(r"^university teachers?$", name, re.I):
        return ""
    return name


def _compare_disambiguation_labels(left, right):
    """Most words first, then longest, then alphabetical (Catapult order)."""
    if len(right.split()) != len(left.split()):
        return len(right.split()) - len(left.split())
    if len(right) != len(left):
        return len(right) - len(left)
    return -1 if left < right else (1 if left > right else 0)


def make_disambiguation_options(base_name, birth_year, death_year,
                                occupation_qids, related, cfg):
    """Parenthetical suffixes for a homonymous category.

    'Category:Name (vocalist)' from P106 values (most specific label wins), or
    'Category:Name (birth-death)' / '(born YYYY)' when there is no occupation.
    """
    names = []
    for qid in occupation_qids:
        name = occupation_disambiguation_name(qid, related, cfg)
        if name and name not in names:
            names.append(name)
    names.sort(key=cmp_to_key(_compare_disambiguation_labels))

    options = []
    for occupation in names:
        options.append({
            "title": "Category:" + base_name + " (" + occupation + ")",
            "label": occupation,
            "source": "occupation",
        })
    if not names:
        life_years = disambiguation_year_suffix(birth_year, death_year)
        if life_years:
            options.append({
                "title": "Category:" + base_name + " (" + life_years + ")",
                "label": life_years,
                "source": "life-years",
            })
    return _unique_options(options)


def _unique_options(options):
    seen = set()
    out = []
    for o in options:
        if o["title"] not in seen:
            seen.add(o["title"])
            out.append(o)
    return out


# ---------------------------------------------------------------------------
# Live API probing (only used by the CLI)
# ---------------------------------------------------------------------------

def api_get(endpoint, params, retries=3):
    """GET a MediaWiki API endpoint with a descriptive User-Agent.

    Wikimedia returns HTTP 429 with a `Retry-After` header when a client is
    too chatty; back off and retry a few times instead of crashing.
    """
    url = endpoint + "?" + urllib.parse.urlencode(params)
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < retries:
                retry_after = float(exc.headers.get("Retry-After") or 5)
                time.sleep(min(retry_after + attempt * 2, 30))
                continue
            raise


def fetch_related_entities(entity, cfg):
    """Fetch the entities needed to resolve claims of a subject item."""
    needed = set()
    for prop in ("P106", "P101", "P27"):
        for qid in claim_value_ids(entity, prop):
            needed.add(qid)
    related = _fetch_batches(sorted(needed))
    # one level of P279/P31 parents of the occupation items
    extra = set()
    for qid in list(needed):
        ent = related.get(qid) or {}
        for prop in ("P279", "P31"):
            for pid in claim_value_ids(ent, prop):
                extra.add(pid)
    related.update(_fetch_batches(sorted(extra)))
    return related


def _fetch_batches(ids, props="labels|claims"):
    out = {}
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        data = api_get(WIKIDATA_API, {
            "action": "wbgetentities", "ids": "|".join(batch),
            "props": props, "format": "json",
        })
        out.update(data.get("entities", {}))
    return out


def probe_commons(titles):
    """Check which category titles exist (and their Wikidata item, redirects).

    Titles are bare category names (no prefix); the API needs the full
    ``Category:`` prefix to hit the category namespace (ns=14), exactly like
    Catapult's normalizeCategoryTitle().
    """
    titles = list(dict.fromkeys(t for t in titles if t))
    result = {}
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        prefixed = [t if re.match(r"^Category:", t, re.I) else "Category:" + t
                    for t in batch]
        data = api_get(COMMONS_API, {
            "action": "query", "prop": "info|pageprops",
            "titles": "|".join(prefixed), "formatversion": 2, "format": "json",
        })
        for page in data.get("query", {}).get("pages", []):
            if page.get("missing") is not None:
                continue
            bare_title = re.sub(r"^Category:", "", page["title"], flags=re.I)
            result[bare_title] = {
                "exists": True,
                "redirect": bool(page.get("redirect")),
                "wikibaseItem": (page.get("pageprops") or {}).get("wikibase_item"),
            }
        # map normalized input titles back to their canonical result keys
        for n in data.get("query", {}).get("normalized") or []:
            canonical = re.sub(r"^Category:", "", n["to"], flags=re.I)
            incoming = re.sub(r"^Category:", "", n["from"], flags=re.I)
            if canonical in result:
                result.setdefault(incoming, result[canonical])
    for t in titles:
        result.setdefault(t, {"exists": False, "redirect": False, "wikibaseItem": None})
    return result


def build_context(entity, related, cfg):
    occupation_qids = claim_value_ids(entity, cfg["properties"]["occupation"])[
        :cfg.get("maxOccupationCount", 8)]
    field_qids = claim_value_ids(entity, cfg["properties"]["fieldOfWork"])[
        :cfg.get("maxOccupationCount", 8)]
    country_qids = claim_value_ids(entity, cfg["properties"]["countryOfCitizenship"])[
        :cfg.get("maxCountryCount", 6)]

    entries = []
    for qid in occupation_qids:
        for e in occupation_name_entries(qid, related, cfg):
            if e not in entries:
                entries.append(e)
    for qid in field_qids:
        for e in field_of_work_category_entries(qid, cfg):
            if e not in entries:
                entries.append(e)
    entries = [e for e in entries if e.get("name")]

    countries = [c for c in (country_phrase(q, related, cfg) for q in country_qids)
                 if c]

    gender = gender_word(claim_value_ids(entity, cfg["properties"]["sexOrGender"]), cfg)
    century = active_century(
        year_from_time_claim(entity, cfg["properties"]["dateOfBirth"]),
        year_from_time_claim(entity, cfg["properties"]["dateOfDeath"]),
    )

    return {
        "occupationEntries": entries,
        "countries": countries,
        "gender": gender,
        "century": century,
        "facultyCategoryNames": [],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_item(args, cfg):
    data = api_get(WIKIDATA_API, {
        "action": "wbgetentities", "ids": args.item,
        "props": "labels|claims", "format": "json",
    })
    entity = data.get("entities", {}).get(args.item)
    if not entity:
        print("item not found: %s" % args.item, file=sys.stderr)
        return 1

    related = fetch_related_entities(entity, cfg)
    context = build_context(entity, related, cfg)
    candidates = generate_category_candidates(context, cfg)

    if args.check:
        probe = probe_commons([c["name"] for c in candidates])
        for c in candidates:
            c["exists"] = probe.get(c["name"], {}).get("exists", False)

    print("# %s (%s)" % (english_label(entity, args.item), args.item))
    print("occupations: %s" % ", ".join(e["name"] for e in context["occupationEntries"]))
    print("countries:   %s" % ", ".join(context["countries"]))
    print("gender:      %s" % (context["gender"] or "-"))
    print("century:     %s" % (context["century"] or "-"))
    print()
    for c in candidates:
        mark = "EXISTS" if c.get("exists") else "      "
        print("%s %-72s %s" % (mark, ucfirst(c["name"]), c["reason"]))
    print()
    best = best_category_candidate(candidates)
    existing = first_existing_candidate(candidates)
    print("preferred to create: %s" % (ucfirst(best["name"]) if best else "-"))
    print("preferred existing:  %s" % (ucfirst(existing["name"]) if existing else "-"))
    if args.check:
        print("('EXISTS' marks categories already on Commons; a category tied to a "
              "different Wikidata item needs disambiguation)")
    return 0


DEFAULT_CFG = {
    "properties": {
        "instanceOf": "P31", "sexOrGender": "P21", "dateOfBirth": "P569",
        "dateOfDeath": "P570", "depicts": "P180", "occupation": "P106",
        "employer": "P108", "fieldOfWork": "P101", "countryOfCitizenship": "P27",
        "commonsCategory": "P373", "image": "P18", "shortName": "P1813",
        "subclassOf": "P279", "categoryContains": "P4224",
        "categoryCombinesTopics": "P971",
    },
    "items": {
        "human": "Q5", "male": "Q6581097", "female": "Q6581072",
        "wikimediaCategory": "Q4167836", "categoryDisambiguationPage": "Q15407973",
    },
    "occupationCategoryByQid": {},
    "occupationCategoryByRelatedQid": {},
    "occupationDisambiguationByQid": {},
    "occupationCategoryReplacements": {},
    "countryPhraseByQid": {},
    "countryNameReplacements": {},
    "categoryBlacklist": [],
    "maxOccupationCount": 8,
    "maxCountryCount": 6,
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--item", metavar="QID", help="Wikidata item id to analyze")
    parser.add_argument("--check", action="store_true",
                        help="probe Commons for which candidate categories exist")
    parser.add_argument("--mappings", metavar="JSON",
                        help="mappings file (Catapult mappings.json format); "
                             "defaults to bundled assets/mappings-sample.json")
    args = parser.parse_args(argv)

    cfg = dict(DEFAULT_CFG)
    if args.mappings:
        cfg = _deep_merge(DEFAULT_CFG, load_cfg(args.mappings))
    else:
        sample = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                              "assets", "mappings-sample.json")
        if os.path.exists(sample):
            cfg = _deep_merge(DEFAULT_CFG, load_cfg(sample))

    if not args.item:
        parser.error("--item QID is required")
    return cmd_item(args, cfg)


def load_cfg(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _deep_merge(base, override):
    """Merge mapping tables into the defaults, keeping default items/properties.

    Catapult's applyMappings() deep-merges the mapping page into CONFIG; a
    shallow merge would let a mappings file replace whole nested dicts (e.g.
    'items') and silently lose defaults like the male/female QIDs.
    """
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


if __name__ == "__main__":
    sys.exit(main())
