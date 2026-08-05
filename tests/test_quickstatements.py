"""Tests for the quickstatements skill: SKILL.md / reference content and the
qs_batch.py V1 validator, person-batch builder, and URL encoder."""

import sys

import pytest

from conftest import SKILLS_DIR, read_skill  # noqa: E402

SCRIPT_DIR = SKILLS_DIR / "quickstatements" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import qs_batch as qs  # noqa: E402


def _errors(text):
    return [m for _, sev, m in qs.validate(text) if sev == "error"]


def _warnings(text):
    return [m for _, sev, m in qs.validate(text) if sev == "warning"]


# ---------------------------------------------------------------------------
# SKILL.md content
# ---------------------------------------------------------------------------

class TestSkillDocs:
    def test_frontmatter(self):
        text = read_skill("quickstatements")
        assert "name: quickstatements" in text
        assert "description:" in text
        assert "depends_on:" in text
        assert "skill_discovery_hints:" in text
        assert "last_verified:" in text

    def test_both_versions_covered(self):
        text = read_skill("quickstatements")
        assert "quickstatements3.toolforge.org" in text  # QS 3.0
        assert "quickstatements.toolforge.org" in text   # QS 2.0

    def test_multilingual_commands(self):
        text = read_skill("quickstatements")
        assert "Lmul" in text
        assert "Amul" in text
        assert "Den" in text

    def test_new_q5_referenced(self):
        text = read_skill("quickstatements")
        assert "New-Q5" in text

    def test_script_referenced(self):
        text = read_skill("quickstatements")
        assert "qs_batch.py" in text
        assert "--file" in text

    def test_guardrails(self):
        text = read_skill("quickstatements").lower()
        assert "autoconfirmed" in text
        assert "duplicate" in text

    def test_mojibake_free(self):
        text = read_skill("quickstatements")
        assert not any(0x80 <= ord(ch) <= 0x9F for ch in text)
        assert not any(0x400 <= ord(ch) <= 0x4FF for ch in text)


# ---------------------------------------------------------------------------
# Reference doc content
# ---------------------------------------------------------------------------

class TestReferenceDoc:
    def test_anchors(self):
        path = SKILLS_DIR / "quickstatements" / "references" / "quickstatements-syntax.md"
        text = path.read_text("utf-8")
        assert "Help:QuickStatements" in text
        assert "QuickStatements 3.0" in text
        assert "quickstatements-syntax.md" not in text  # no self-reference loop

    def test_value_formats(self):
        text = (SKILLS_DIR / "quickstatements" / "references" / "quickstatements-syntax.md").read_text("utf-8")
        for needle in ("@43.26193/10.92708", "2994U11573", "pl:\"Krzyżacy\"",
                       "+1839-00-00T00:00:00Z/9", "somevalue", "novalue"):
            assert needle in text

    def test_ranks(self):
        text = (SKILLS_DIR / "quickstatements" / "references" / "quickstatements-syntax.md").read_text("utf-8")
        assert "Rpreferred" in text and "Rdeprecated" in text and "R+" in text

    def test_limitations(self):
        text = (SKILLS_DIR / "quickstatements" / "references" / "quickstatements-syntax.md").read_text("utf-8")
        assert "M IDs" in text
        assert "REST API" in text
        assert "maxlag" in text

    def test_url_and_api(self):
        text = (SKILLS_DIR / "quickstatements" / "references" / "quickstatements-syntax.md").read_text("utf-8")
        assert "#/v1=" in text
        assert "batch/new?v1=" in text
        assert "api.php" in text

    def test_mojibake_free(self):
        text = (SKILLS_DIR / "quickstatements" / "references" / "quickstatements-syntax.md").read_text("utf-8")
        assert not any(0x80 <= ord(ch) <= 0x9F for ch in text)
        assert not any(0x400 <= ord(ch) <= 0x4FF for ch in text)


# ---------------------------------------------------------------------------
# format_time / quote_string
# ---------------------------------------------------------------------------

class TestFormatTime:
    def test_year_month_day(self):
        assert qs.format_time(1967) == "+1967-00-00T00:00:00Z/9"
        assert qs.format_time(1967, 1) == "+1967-01-00T00:00:00Z/10"
        assert qs.format_time(1967, 1, 17) == "+1967-01-17T00:00:00Z/11"

    def test_explicit_precision(self):
        assert qs.format_time(1600, 1, 1, precision=7) == "+1600-01-01T00:00:00Z/7"

    def test_bce(self):
        assert qs.format_time(384, era="-") == "-0384-00-00T00:00:00Z/9"

    def test_bad_precision(self):
        with pytest.raises(ValueError):
            qs.format_time(1967, precision=12)


class TestQuoteString:
    def test_escapes_quotes(self):
        assert qs.quote_string('Toys "R" Us') == '"Toys \\"R\\" Us"'

    def test_plain(self):
        assert qs.quote_string("Jane Doe") == '"Jane Doe"'


# ---------------------------------------------------------------------------
# Validation: QS 2.0 shared syntax
# ---------------------------------------------------------------------------

class TestValidateBasic:
    def test_simple_statement(self):
        assert _errors("Q42|P31|Q5") == []

    def test_entity_value(self):
        assert _errors("Q42|P19|Q350") == []

    def test_string_value(self):
        assert _errors('Q41576278|P373|"Antoni Ignacy Mietelski"') == []

    def test_monolingual(self):
        assert _errors('Q1214098|P1476|pl:"Krzyżacy"') == []

    def test_time_value(self):
        assert _errors("Q41576483|P569|+1839-00-00T00:00:00Z/9") == []

    def test_time_bce(self):
        assert _errors("Q868|P569|-0384-00-00T00:00:00Z/9") == []

    def test_coordinate(self):
        assert _errors("Q3669835|P625|@43.26193/10.92708") == []

    def test_quantity(self):
        assert _errors("Q3450504|P1098|1") == []
        assert _errors("Q739484|P2044|2994U11573") == []
        assert _errors("Q97|P2046|106460000~10000U712226") == []
        assert _errors("Q97|P2046|106460000[106450000,106470000]U712226") == []

    def test_special_values(self):
        assert _errors("Q331226|P156|novalue") == []
        assert _errors("Q35811|P569|somevalue") == []

    def test_qualifiers(self):
        assert _errors(
            "Q40269|P1082|1360590|P585|+2000-08-01T00:00:00Z/11|P459|Q39825") == []

    def test_sources(self):
        assert _errors(
            'Q22124656|P21|Q6581097|S143|Q24731821|S813|+2017-10-04T00:00:00Z/11') == []

    def test_multiple_reference_groups(self):
        assert _errors(
            'Q143|P220|"epo"|S248|Q14790|S813|+2014-10-31T00:00:00Z/11'
            '|!S248|Q75488338|S854|"https://op.europa.eu/"') == []

    def test_label_description_alias_sitelink(self):
        assert _errors('Q340122|Lpl|"Cyprian Kamil Norwid"') == []
        assert _errors('Q340122|Dde|"polnischer Dichter"') == []
        assert _errors('Q340122|Aen|"Cyprjan Kamil Norvid"') == []
        assert _errors('Q340122|Senwiki|"Cyprian Norwid"') == []

    def test_mul_commands(self):
        assert _errors('Q340122|Lmul|"Brandname"') == []
        assert _errors('Q340122|Amul|"Brandname Inc."') == []

    def test_removal_by_empty_string(self):
        assert _errors('Q340122|Len|""') == []
        assert _errors('Q340122|Sptwiki|""') == []

    def test_removal_by_prefix(self):
        assert _errors('-Q4115189|P31|Q1') == []
        assert _errors('-Q4115189|P569|+1988-05-11T00:00:00Z/11') == []

    def test_statement_id_removal(self):
        assert _errors(
            "-STATEMENT|Q1$00000000-0000-0000-0000-000000000000") == []

    def test_create_last(self):
        batch = "CREATE\nLAST|Len|\"X\"\nLAST|P31|Q5"
        assert _errors(batch) == []
        assert _warnings(batch) == []

    def test_double_pipe_separators(self):
        assert _errors("Q42|P31|Q5||Q42|P21|Q6581097") == []

    def test_merge(self):
        assert _errors("MERGE|Q1|Q2") == []

    def test_comments(self):
        assert _errors('Q8023|P18|"Nelson Mandela 1994.jpg"|/* Add image */') == []


# ---------------------------------------------------------------------------
# Validation: errors and warnings
# ---------------------------------------------------------------------------

class TestValidateErrors:
    def test_unquoted_string(self):
        errors = _errors("Q41576278|P373|Antoni")
        assert errors and "not double-quoted" in errors[0]

    def test_unterminated_quote(self):
        assert _errors('Q41576278|P373|"Antoni') != []

    def test_bad_time_precision(self):
        assert _errors("Q41576483|P569|+1839-00-00T00:00:00Z/12") != []

    def test_missing_value(self):
        assert _errors("Q42|P31|") != []

    def test_unknown_command(self):
        assert _errors("Q42|Z99|Q5") != []

    def test_invalid_entity(self):
        assert _errors("XYZ|P31|Q5") != []

    def test_malformed_merge(self):
        assert _errors("MERGE|Q1") != []

    def test_last_without_create_is_warning(self):
        warnings = _warnings("LAST|P31|Q5")
        assert warnings and "CREATE" in warnings[0]
        assert _errors("LAST|P31|Q5") == []

    def test_description_mul_is_warning(self):
        warnings = _warnings('Q340122|Dmul|"desc"')
        assert warnings and "mul" in warnings[0]

    def test_bare_year_is_warning(self):
        warnings = _warnings("Q41576483|P569|1980")
        assert warnings and "year" in warnings[0]

    def test_validate_ok(self):
        assert qs.validate_ok("Q42|P31|Q5")
        assert not qs.validate_ok('Q42|P31|foo')


# ---------------------------------------------------------------------------
# Validation: QS 3.0 syntax
# ---------------------------------------------------------------------------

class TestValidateQs3:
    def test_ranks(self):
        assert _errors('Q2513|P856|"http://hubblesite.org/"|R+') == []
        assert _errors('Q2513|P856|"http://spacetelescope.org/"|R0') == []
        assert _errors('Q2513|P10565|"68143"|R-|P2241|Q21441764') == []
        assert _errors('Q2513|P856|"http://example.org/"|Rpreferred') == []
        assert _errors('Q2513|P856|"http://example.org/"|Rdeprecated') == []

    def test_force_create(self):
        assert _errors(
            "+Q6454|P6|Q3160150|P580|+1959-03-15T00:00:00Z/11"
            "|P582|+1969-03-15T00:00:00Z/11") == []

    def test_remove_qual(self):
        assert _errors(
            'REMOVE_QUAL|Q14560|P225|"Cactaceae"|P405|Q223963') == []

    def test_remove_ref(self):
        assert _errors("REMOVE_REF|Q5598|P27|Q170072|S143|Q328") == []

    def test_switch_value(self):
        assert _errors("SWITCH_VALUE|Q1774|P2046|2461U712226|950.2U232291") == []

    def test_switch_property(self):
        assert _errors(
            'SWITCH_PROPERTY|Q40269|P18|"Aerial view.jpg"|P8592') == []

    def test_switch_both(self):
        assert _errors("SWITCH_PROPERTY_AND_VALUE|Q1|P1|Q2|P2|Q3") == []

    def test_switch_too_short(self):
        assert _errors("SWITCH_VALUE|Q1774|P2046|2461U712226") != []

    def test_full_qs3_batch(self):
        batch = """\
Q2513|P856|"http://hubblesite.org/"|R+
Q2513|P10565|"68143"|R-|P2241|Q21441764
+Q6454|P6|Q3160150|P580|+1959-03-15T00:00:00Z/11|P582|+1969-03-15T00:00:00Z/11
REMOVE_QUAL|Q14560|P225|"Cactaceae"|P405|Q223963
REMOVE_REF|Q5598|P27|Q170072|S143|Q328
SWITCH_VALUE|Q1774|P2046|2461U712226|950.2U232291
SWITCH_PROPERTY|Q40269|P18|"Aerial view.jpg"|P8592
"""
        assert _errors(batch) == []


# ---------------------------------------------------------------------------
# Person batch builder (New-Q5 pattern)
# ---------------------------------------------------------------------------

class TestBuildPersonBatch:
    def test_structure(self):
        batch = qs.build_person_batch(
            "Jane Doe", description="fictional person",
            gender_qid="Q6581097", gender_inferred_from="Q69652498",
            given_name_qids=("Q123", "Q124"), family_name_qid="Q999",
            dob=(1980, 1, 2), dod="2020-03-04",
            ref_url="https://example.com/obit",
            ref_retrieved="2026-06-24")
        text = "\n".join(batch)
        assert batch[0] == "CREATE"
        assert 'LAST|Lmul|"Jane Doe"' in text
        for lang in ("en", "de", "fr", "nl"):
            assert f'LAST|L{lang}|"Jane Doe"' in text
        assert 'LAST|Den|"fictional person"' in text
        assert "LAST|P31|Q5" in text
        assert "LAST|P21|Q6581097|S887|Q69652498" in text
        assert 'LAST|P735|Q123|P1545|"1"' in text
        assert 'LAST|P735|Q124|P1545|"2"' in text
        assert "LAST|P734|Q999" in text
        assert "LAST|P569|+1980-01-02T00:00:00Z/11|S854|" in text
        assert "LAST|P570|+2020-03-04T00:00:00Z/11|S854|" in text
        assert '|S813|+2026-06-24T00:00:00Z/11' in text
        # the generated batch itself validates cleanly
        assert _errors(text) == []

    def test_approximate_dob(self):
        batch = qs.build_person_batch(
            "Jane Doe", dob_approx_range=((1979, 3), (1980, 3)),
            ref_url="https://example.com/source")
        text = "\n".join(batch)
        assert "|P1480|Q5727902" in text
        assert "|P1319|+1979-03-00T00:00:00Z/10" in text
        assert "|P1326|+1980-03-00T00:00:00Z/10" in text
        assert _errors(text) == []

    def test_no_mul_label(self):
        batch = qs.build_person_batch("Jane Doe", add_mul_label=False)
        assert not any("Lmul" in line for line in batch)

    def test_escapes_quotes(self):
        batch = qs.build_person_batch('Jane "JD" Doe')
        assert any('"Jane \\"JD\\" Doe"' in line for line in batch)

    def test_requires_name(self):
        with pytest.raises(ValueError):
            qs.build_person_batch("")


# ---------------------------------------------------------------------------
# URL encoding
# ---------------------------------------------------------------------------

class TestToV1Url:
    def test_version_2(self):
        url = qs.to_v1_url(["CREATE", 'LAST|Lmul|"Jane Doe"'])
        assert url.startswith("https://quickstatements.toolforge.org/#/v1=")
        assert "%7C" in url and "%22" in url and "CREATE" in url

    def test_version_3(self):
        url = qs.to_v1_url(["Q42|P31|Q5"], version=3)
        assert url.startswith("https://quickstatements3.toolforge.org/batch/new?v1=")
        assert "%7C" in url

    def test_version_3_dev_note(self):
        # dev instance is documented in the skill; builder points at production
        assert qs.to_v1_url(["Q42|P31|Q5"], version=3).startswith(
            "https://quickstatements3.toolforge.org/")

    def test_bad_version(self):
        with pytest.raises(ValueError):
            qs.to_v1_url(["Q42|P31|Q5"], version=1)
