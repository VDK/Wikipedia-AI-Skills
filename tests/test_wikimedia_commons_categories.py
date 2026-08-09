"""Tests for the wikimedia-commons-categories skill: SKILL.md content and
the Catapult-derived category-suggestion script."""

import sys
from unittest.mock import patch

import pytest

from conftest import SKILLS_DIR, read_skill  # noqa: E402

SCRIPT_DIR = SKILLS_DIR / "wikimedia-commons-categories" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import suggest_categories as sc  # noqa: E402

CFG = {
    "properties": {
        "occupation": "P106",
        "fieldOfWork": "P101",
        "countryOfCitizenship": "P27",
        "sexOrGender": "P21",
        "dateOfBirth": "P569",
        "dateOfDeath": "P570",
        "commonsCategory": "P373",
        "shortName": "P1813",
        "subclassOf": "P279",
        "instanceOf": "P31",
    },
    "items": {"male": "Q6581097", "female": "Q6581072"},
    "occupationCategoryByQid": {"Q177220": "vocalists"},
    "occupationCategoryByRelatedQid": {"Q22811707": "decorators"},
    "occupationDisambiguationByQid": {"Q177220": "vocalist"},
    "occupationCategoryReplacements": {"Singers": "vocalists", "Businesspersons": "businesspeople"},
    "countryPhraseByQid": {"Q55": "the Netherlands"},
    "countryNameReplacements": {"Netherlands": "the Netherlands", "Czechia": "the Czech Republic"},
    "categoryBlacklist": ["Positions", "Occupations"],
    "maxOccupationCount": 8,
    "maxCountryCount": 6,
}


def item_claim(qid, rank="normal"):
    return {"mainsnak": {"datavalue": {"value": {"id": qid}}}, "rank": rank, "qualifiers": {}}


def text_claim(value, rank="normal"):
    return {"mainsnak": {"datavalue": {"value": value}}, "rank": rank, "qualifiers": {}}


def entity(claims=None, labels=None):
    return {"claims": claims or {}, "labels": labels or {}}


# ---------------------------------------------------------------------------
# Skill content
# ---------------------------------------------------------------------------

class TestSkillContent:
    """Key assertions about the SKILL.md (mirrors test_markdown_sops style)."""

    def test_core_pattern_documented(self):
        text = read_skill("wikimedia-commons-categories")
        assert "from" in text and "by name" in text
        assert "occupation" in text and "P106" in text

    def test_disambiguation_documented(self):
        text = read_skill("wikimedia-commons-categories")
        assert "disambiguat" in text.lower()
        assert "wikibase_item" in text

    def test_script_referenced(self):
        text = read_skill("wikimedia-commons-categories")
        assert "suggest_categories.py" in text
        assert "--item" in text

    def test_mojibake_free(self):
        text = read_skill("wikimedia-commons-categories")
        assert not any(0x80 <= ord(ch) <= 0x9F for ch in text)
        assert not any(0x400 <= ord(ch) <= 0x4FF for ch in text)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

class TestPluralize:
    @pytest.mark.parametrize("name,expected", [
        ("vocalist", "vocalists"),
        ("director", "directors"),
        ("boxer", "boxers"),
        ("designer", "designers"),
        ("secretary", "secretaries"),
        ("person", "people"),
        ("Person", "People"),
        ("people", "people"),
        ("musicians", "musicians"),
        ("artist", "artists"),
    ])
    def test_pluralize(self, name, expected):
        assert sc.pluralize(name) == expected


class TestOrdinal:
    @pytest.mark.parametrize("n,expected", [
        (1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"),
        (11, "11th"), (12, "12th"), (13, "13th"),
        (21, "21st"), (22, "22nd"), (23, "23rd"),
        (20, "20th"), (100, "100th"),
    ])
    def test_ordinal(self, n, expected):
        assert sc.ordinal(n) == expected


class TestCountryRules:
    def test_definite_article_rules(self):
        rep = CFG["countryNameReplacements"]
        assert sc.normalize_country_phrase("United States", rep) == "the United States"
        assert sc.normalize_country_phrase("United Kingdom", rep) == "the United Kingdom"
        assert sc.normalize_country_phrase("Bahamas", rep) == "the Bahamas"
        assert sc.normalize_country_phrase("Czech Republic", rep) == "the Czech Republic"
        assert sc.normalize_country_phrase("Marshall Islands", rep) == "the Marshall Islands"
        assert sc.normalize_country_phrase("Germany", rep) == "Germany"
        assert sc.normalize_country_phrase("France", rep) == "France"

    def test_replacements_table(self):
        rep = CFG["countryNameReplacements"]
        assert sc.normalize_country_phrase("Netherlands", rep) == "the Netherlands"
        assert sc.normalize_country_phrase("Czechia", rep) == "the Czech Republic"

    def test_add_definite_article_idempotent(self):
        assert sc.add_definite_article("the Netherlands") == "the Netherlands"
        assert sc.add_definite_article("Germany") == "the Germany"


class TestCountryPhrase:
    def test_explicit_mapping(self):
        assert sc.country_phrase("Q55", {}, CFG) == "the Netherlands"

    def test_label_fallback_with_article_rule(self):
        related = {"Q30": entity(labels={"en": {"value": "United States"}})}
        assert sc.country_phrase("Q30", related, CFG) == "the United States"

    def test_plain_label(self):
        related = {"Q183": entity(labels={"en": {"value": "Germany"}})}
        assert sc.country_phrase("Q183", related, CFG) == "Germany"

    def test_short_name_preferred_over_label(self):
        # Q56 is not in countryPhraseByQid, so the P1813 short name wins
        related = {"Q56": entity(
            labels={"en": {"value": "Kingdom of the Netherlands"}},
            claims={"P1813": [text_claim({"language": "en", "text": "the Netherlands"})]},
        )}
        assert sc.country_phrase("Q56", related, CFG) == "the Netherlands"


# ---------------------------------------------------------------------------
# Occupation resolution
# ---------------------------------------------------------------------------

class TestOccupationName:
    def test_explicit_mapping(self):
        assert sc.occupation_name("Q177220", {}, CFG) == "vocalists"

    def test_commons_category_claim(self):
        related = {"Q123": entity(claims={"P373": [text_claim("Sopranos")]})}
        assert sc.occupation_name("Q123", related, CFG) == "sopranos"

    def test_english_label_pluralized_lcfirst(self):
        related = {"Q123": entity(labels={"en": {"value": "singer"}})}
        assert sc.occupation_name("Q123", related, CFG) == "singers"

    def test_replacement_applied(self):
        related = {"Q123": entity(labels={"en": {"value": "Singers"}})}
        assert sc.occupation_name("Q123", related, CFG) == "vocalists"


class TestOccupationNameEntries:
    def test_direct_plus_parent_fallback(self):
        related = {"Q22811707": entity(labels={"en": {"value": "decorator"}})}
        occ = entity(claims={"P279": [item_claim("Q22811707")]})
        entries = sc.occupation_name_entries("Q177220", {"Q177220": occ, **related}, CFG)
        names = [(e["name"], e["isFallback"]) for e in entries]
        assert names == [("vocalists", False), ("decorators", True)]

    def test_dedup(self):
        related = {"Q22811707": entity(labels={"en": {"value": "vocalist"}})}
        occ = entity(claims={"P279": [item_claim("Q22811707")]})
        entries = sc.occupation_name_entries("Q177220", {"Q177220": occ, **related}, CFG)
        names = [e["name"] for e in entries]
        assert names.count("vocalists") == 1


# ---------------------------------------------------------------------------
# Claim filtering, gender, century
# ---------------------------------------------------------------------------

class TestClaimValueIds:
    def test_deprecated_dropped(self):
        e = entity(claims={"P106": [item_claim("Q5"), item_claim("Q6", rank="deprecated")]})
        assert sc.claim_value_ids(e, "P106") == ["Q5"]

    def test_preferred_wins(self):
        e = entity(claims={"P106": [
            item_claim("Q5", rank="preferred"), item_claim("Q6"),
        ]})
        assert sc.claim_value_ids(e, "P106") == ["Q5"]

    def test_emoji_flag_dropped(self):
        flag = {"P3831": [{"datavalue": {"value": {"id": "Q28840786"}}}]}
        e = entity(claims={"P106": [item_claim("Q5", rank="normal"), {
            "mainsnak": {"datavalue": {"value": {"id": "Q6"}}},
            "rank": "normal", "qualifiers": flag,
        }]})
        assert sc.claim_value_ids(e, "P106") == ["Q5"]


class TestGender:
    def test_male_female_words(self):
        assert sc.gender_word(["Q6581097"], CFG) == "male"
        assert sc.gender_word(["Q6581072"], CFG) == "female"
        assert sc.gender_word([], CFG) == ""

    def test_gendered_occupation(self):
        assert sc.gendered_occupation_category("businesspeople", "male") == "businessmen"
        assert sc.gendered_occupation_category("businesspeople", "female") == "businesswomen"
        assert sc.gendered_occupation_category("businesspeople", "") == ""
        assert sc.gendered_occupation_category("vocalists", "female") == ""


class TestActiveCentury:
    def test_death_year_wins(self):
        assert sc.active_century(1962, 2024) == "21st-century"

    def test_historical_birth_year(self):
        assert sc.active_century(1900, None, current_year=2026) == "20th-century"

    def test_recent_person_current_century(self):
        assert sc.active_century(1990, None, current_year=2026) == "21st-century"

    def test_no_dates(self):
        assert sc.active_century(None, None) == ""


# ---------------------------------------------------------------------------
# Candidate generation and ranking
# ---------------------------------------------------------------------------

class TestCandidateGeneration:
    CONTEXT = {
        "occupationEntries": [
            {"name": "vocalists", "sourceOccupation": "vocalists", "isFallback": False},
        ],
        "countries": ["the Netherlands"],
        "gender": "female",
        "century": "20th-century",
        "facultyCategoryNames": [],
    }

    def test_matrix_order_and_by_name(self):
        # 'vocalists' has no gendered form, so for a female it yields:
        # occupation+country, gender+occupation+country, century+occupation+country,
        # century+gender+occupation+country - each with a 'by name' twin.
        cands = sc.generate_category_candidates(self.CONTEXT, CFG)
        names = [c["name"] for c in cands]
        expected = [
            "vocalists from the Netherlands",
            "vocalists from the Netherlands by name",
            "female vocalists from the Netherlands",
            "female vocalists from the Netherlands by name",
            "20th-century vocalists from the Netherlands",
            "20th-century vocalists from the Netherlands by name",
            "20th-century female vocalists from the Netherlands",
            "20th-century female vocalists from the Netherlands by name",
            "vocalists",
        ]
        assert names == expected

    def test_reasons(self):
        cands = sc.generate_category_candidates(self.CONTEXT, CFG)
        reasons = {c["name"]: c["reason"] for c in cands}
        assert reasons["vocalists from the Netherlands"] == "occupation + country"
        assert reasons["vocalists from the Netherlands by name"] == "occupation + country + by name"
        assert reasons["vocalists"] == "occupation"

    def test_by_name_flag(self):
        cands = sc.generate_category_candidates(self.CONTEXT, CFG)
        by_names = [c for c in cands if c["isByName"]]
        assert len(by_names) == 4
        assert all(c["name"].endswith("by name") for c in by_names)

    def test_blacklist_drops_generic_names(self):
        ctx = {"occupationEntries": [
            {"name": "Positions", "sourceOccupation": "Positions", "isFallback": False},
            {"name": "vocalists", "sourceOccupation": "vocalists", "isFallback": False},
        ], "countries": [], "gender": "", "century": "", "facultyCategoryNames": []}
        cands = sc.generate_category_candidates(ctx, CFG)
        names = [c["name"] for c in cands]
        assert "Positions" not in names
        assert "vocalists" in names

    def test_no_gender_no_century(self):
        ctx = {"occupationEntries": [
            {"name": "vocalists", "sourceOccupation": "vocalists", "isFallback": False},
        ], "countries": ["Germany"], "gender": "", "century": "", "facultyCategoryNames": []}
        names = [c["name"] for c in sc.generate_category_candidates(ctx, CFG)]
        assert names == ["vocalists from Germany", "vocalists from Germany by name", "vocalists"]

    def test_gendered_occupation_for_businesspeople(self):
        ctx = {"occupationEntries": [
            {"name": "businesspeople", "sourceOccupation": "businesspeople", "isFallback": False},
        ], "countries": ["Belgium"], "gender": "male", "century": "", "facultyCategoryNames": []}
        names = [c["name"] for c in sc.generate_category_candidates(ctx, CFG)]
        assert "businessmen from Belgium" in names
        assert "male businesspeople from Belgium" not in names

    def test_generic_fallback_discarded(self):
        ctx = {"occupationEntries": [
            {"name": "people by occupation", "sourceOccupation": "x", "isFallback": True},
        ], "countries": ["Germany"], "gender": "", "century": "", "facultyCategoryNames": []}
        assert sc.generate_category_candidates(ctx, CFG) == []


class TestRanking:
    def test_country_scoped_beats_bare(self):
        cands = sc.generate_category_candidates(
            {"occupationEntries": [
                {"name": "vocalists", "sourceOccupation": "vocalists", "isFallback": False},
            ], "countries": ["the Netherlands"], "gender": "",
             "century": "", "facultyCategoryNames": []}, CFG)
        best = sc.best_category_candidate(cands)
        assert best["name"] == "vocalists from the Netherlands"

    def test_by_name_deprioritized_when_both_exist(self):
        cands = sc.generate_category_candidates(
            {"occupationEntries": [
                {"name": "vocalists", "sourceOccupation": "vocalists", "isFallback": False},
            ], "countries": ["the Netherlands"], "gender": "",
             "century": "", "facultyCategoryNames": []}, CFG)
        by_name = next(c for c in cands if c["name"].endswith("by name"))
        plain = next(c for c in cands if c["name"] == "vocalists from the Netherlands")
        by_name["exists"] = True
        plain["exists"] = True
        assert sc.best_category_candidate(cands)["name"] == "vocalists from the Netherlands"

    def test_first_existing_skips_direct_occupation_cover(self):
        cands = sc.generate_category_candidates(
            {"occupationEntries": [
                {"name": "vocalists", "sourceOccupation": "vocalists", "isFallback": True},
            ], "countries": ["the Netherlands"], "gender": "",
             "century": "", "facultyCategoryNames": []}, CFG)
        for c in cands:
            c["exists"] = True
        best = sc.first_existing_candidate(cands)
        assert best["name"] == "vocalists from the Netherlands"


# ---------------------------------------------------------------------------
# Disambiguation
# ---------------------------------------------------------------------------

class TestDisambiguation:
    def test_occupation_suffix(self):
        opts = sc.make_disambiguation_options("John Smith", None, None,
                                              ["Q177220"], {}, CFG)
        assert opts == [{"title": "Category:John Smith (vocalist)",
                         "label": "vocalist", "source": "occupation"}]

    def test_life_years_fallback(self):
        opts = sc.make_disambiguation_options("John Smith", 1940, 1999,
                                              [], {}, CFG)
        assert opts[0]["title"] == "Category:John Smith (1940-1999)"
        assert opts[0]["source"] == "life-years"

    def test_born_year_fallback(self):
        opts = sc.make_disambiguation_options("John Smith", 1940, None,
                                              [], {}, CFG)
        assert opts[0]["title"] == "Category:John Smith (born 1940)"

    def test_year_suffix(self):
        assert sc.disambiguation_year_suffix(1940, 1999) == "1940-1999"
        assert sc.disambiguation_year_suffix(1940, None) == "born 1940"
        assert sc.disambiguation_year_suffix(None, None) == ""

    def test_sort_most_specific_first(self):
        related = {
            "Q1": entity(labels={"en": {"value": "association football manager"}}),
            "Q2": entity(labels={"en": {"value": "footballer"}}),
        }
        opts = sc.make_disambiguation_options("John Smith", None, None,
                                              ["Q1", "Q2"], related, CFG)
        assert opts[0]["label"] == "association football manager"
        assert opts[1]["label"] == "footballer"

    def test_university_teacher_skipped(self):
        related = {"Q1": entity(labels={"en": {"value": "university teacher"}})}
        opts = sc.make_disambiguation_options("John Smith", 1940, 1999,
                                              ["Q1"], related, CFG)
        # occupation label too generic -> falls back to life years
        assert opts[0]["title"] == "Category:John Smith (1940-1999)"


# ---------------------------------------------------------------------------
# Commons existence probing (mocked - no network)
# ---------------------------------------------------------------------------

MOCK_PROBE_RESPONSE = {
    "query": {
        "normalized": [
            {"from": "Category:actors from Austria",
             "to": "Category:Actors from Austria"},
            {"from": "Category:does-not-exist-xyz-12345",
             "to": "Category:Does-not-exist-xyz-12345"},
        ],
        "pages": [
            {"title": "Category:Does-not-exist-xyz-12345", "ns": 14, "missing": True},
            {"title": "Category:Vocalists from the Netherlands", "ns": 14,
             "pageprops": {"wikibase_item": "Q6470027"}},
            {"title": "Category:Actors from Austria", "ns": 14,
             "pageprops": {"wikibase_item": "Q9806113"}},
        ],
    }
}


class TestProbeCommons:
    def test_exists_and_normalization(self):
        with patch("suggest_categories.api_get", return_value=MOCK_PROBE_RESPONSE) as mock:
            res = sc.probe_commons([
                "actors from Austria", "Vocalists from the Netherlands",
                "does-not-exist-xyz-12345",
            ])
        assert res["actors from Austria"]["exists"] is True
        assert res["actors from Austria"]["wikibaseItem"] == "Q9806113"
        assert res["Vocalists from the Netherlands"]["exists"] is True
        assert res["Vocalists from the Netherlands"]["wikibaseItem"] == "Q6470027"
        assert res["does-not-exist-xyz-12345"]["exists"] is False

    def test_category_namespace_prefix(self):
        with patch("suggest_categories.api_get", return_value=MOCK_PROBE_RESPONSE) as mock:
            sc.probe_commons(["actors from Austria"])
        params = mock.call_args[0][1]
        assert params["titles"] == "Category:actors from Austria"
        assert params["prop"] == "info|pageprops"
        assert params["formatversion"] == 2


# ---------------------------------------------------------------------------
# Context building
# ---------------------------------------------------------------------------

class TestBuildContext:
    def test_full_context(self):
        e = entity(claims={
            "P106": [item_claim("Q177220")],
            "P27": [item_claim("Q55")],
            "P21": [item_claim("Q6581072")],
            "P569": [text_claim("+1962-01-01T00:00:00Z")],
        })
        related = {"Q55": entity(labels={"en": {"value": "Netherlands"}})}
        ctx = sc.build_context(e, related, CFG)
        assert ctx["occupationEntries"][0]["name"] == "vocalists"
        assert ctx["countries"] == ["the Netherlands"]
        assert ctx["gender"] == "female"
        assert ctx["century"] == "21st-century"
