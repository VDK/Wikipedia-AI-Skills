"""Tests for the flickr skill: SKILL.md content and the manifest fetcher script."""

import sys

from conftest import SKILLS_DIR, read_skill  # noqa: E402

SCRIPT_DIR = SKILLS_DIR / "flickr" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import fetch_flickr as ff  # noqa: E402


class TestSkillContent:
    """Key assertions about the flickr SKILL.md (mirrors test_markdown_sops style)."""

    def test_depends_on_pattypan_and_commons(self):
        text = read_skill("flickr")
        assert "pattypan" in text
        assert "wikimedia-commons" in text

    def test_read_only_no_oauth(self):
        text = read_skill("flickr")
        assert "no OAuth" in text
        assert "read-only" in text

    def test_xls_contract_delegates_to_pattypan(self):
        text = read_skill("flickr")
        # flickr produces manifests, pattypan produces the .xls
        assert "build_pattypan_spreadsheet.py" in text
        assert ".xls" in text

    def test_license_filter_documented(self):
        text = read_skill("flickr")
        assert "4, 5, 7, 8, 9, 10, 11, 12" in text
        assert "Cc-by-2.0" in text

    def test_reference_files_mentioned(self):
        text = read_skill("flickr")
        assert "fetch_flickr.py" in text
        assert "flickr-api.md" in text
        assert "flickr-to-commons.md" in text

    def test_pagination_and_extras_documented(self):
        text = read_skill("flickr")
        assert "per_page" in text
        assert "extras" in text

    def test_photoset_owner_quirk_documented(self):
        text = read_skill("flickr")
        assert "photoset.owner" in text or "owner" in text

    def test_account_category_patterns(self):
        text = read_skill("flickr")
        assert "Flickr user category" in text
        assert "Photographs by Flickr photographer" in text
        assert "Photographs by <account>" in text

    def test_already_transferred_dedupe(self):
        text = read_skill("flickr")
        assert 'insource:"flickr.com/photos/<nsid>"' in text
        assert "already" in text

    def test_sparql_dedupe_query_documented(self):
        text = read_skill("flickr")
        assert "P2093" in text  # author name string qualifier (broader net)
        assert "P3267" in text  # Flickr user ID qualifier (precise subset)
        assert "P170" in text  # creator
        ref = (SKILLS_DIR / "flickr" / "references" / "flickr-to-commons.md").read_text("utf-8")
        assert "SELECT ?file ?url ?image" in ref
        assert "pq:P3267" in ref
        assert "pq:P2093" in ref
        assert "P7482" in ref and "Q74228490" in ref and "Q103204" in ref  # origin=Flickr
        assert "P973" in ref  # described at URL
        assert "broader" in ref  # P2093 is the completeness net

    def test_references_commons_sdc(self):
        text = read_skill("flickr")
        assert "wikimedia-commons-sdc" in text
        ref = (SKILLS_DIR / "flickr" / "references" / "flickr-to-commons.md").read_text("utf-8")
        assert "wikimedia-commons-sdc" in ref

    def test_reference_covers_account_categories_and_dedupe(self):
        ref = (SKILLS_DIR / "flickr" / "references" / "flickr-to-commons.md").read_text("utf-8")
        assert "Account categories on Commons" in ref
        assert "Finding already-transferred files" in ref
        assert "Flickr user category" in ref
        assert "P3267" in ref  # Flickr user ID property on Wikidata


class TestHelpers:
    """Unit tests for the pure functions in fetch_flickr.py (no network)."""

    def test_license_template_map(self):
        assert ff.license_template("4") == "{{Cc-by-2.0}}"
        assert ff.license_template("5") == "{{Cc-by-sa-2.0}}"
        assert ff.license_template("9") == "{{Cc-zero}}"
        assert ff.license_template("12") == "{{Cc-by-sa-4.0}}"
        assert ff.license_template("2") == "{{subst:unc}}"  # NC license -> never mapped
        assert ff.license_template(None) == "{{subst:unc}}"

    def test_strip_html(self):
        assert ff.strip_html("Hello<br/>World") == "Hello World"
        assert ff.strip_html("<p>Para</p>end") == "Para end"
        assert ff.strip_html("a &amp; b &quot;c&quot;") == 'a & b "c"'

    def test_escape_template(self):
        assert ff.escape_template("a|b{c}d") == "a&#124;b&#123;c&#125;d"

    def test_sanitize_filename(self):
        assert ff.sanitize_filename("Re:publica 2026 - Tag 1") == "Re-publica 2026 - Tag 1"
        assert ff.sanitize_filename('a/b\\c:d*e?f"g<h>i|j') == "a-b-c-d-e-f-g-h-i-j"

    def test_best_image_url_priority(self):
        photo = {"url_c": "c", "url_o": "o", "url_m": "m", "url_l": "l"}
        assert ff.best_image_url(photo) == "o"
        assert ff.best_image_url({"url_z": "z"}) == "z"
        assert ff.best_image_url({}) == ""

    def test_taken_date_string_passthrough(self):
        assert ff.taken_date({"datetaken": "2024-05-12 15:07:08"}) == "2024-05-12 15:07:08"

    def test_taken_date_unix_fallback(self):
        assert ff.taken_date({"dateupload": "1700000000"}) == "2023-11-14 22:13:20"

    def test_photo_tags_variants(self):
        assert ff.photo_tags({"tags": "a b c"}) == ["a", "b", "c"]
        assert ff.photo_tags({"tags": {"tag": [{"raw": "日本"}, {"raw": "Tokyo"}]}}) == ["日本", "Tokyo"]
        assert ff.photo_tags({}) == []

    def test_build_rows(self):
        photos = [{
            "id": "12345",
            "title": "Re:publica 2026 - Panel",
            "description": {"_content": "A talk <b>live</b>"},
            "datetaken": "2026-06-05 10:00:00",
            "owner": "36976328@N04",
            "ownername": "re:publica 2026",
            "license": "4",
            "url_o": "https://live.staticflickr.com/1/12345_o.jpg",
        }]
        args = ff.argparse.Namespace(
            tags_fallback=False, lang="en", user="36976328@N04",
        )
        row = ff.build_rows(photos, args)[0]
        assert row[0] == "https://live.staticflickr.com/1/12345_o.jpg"
        assert row[1] == "Re-publica 2026 - Panel (12345).jpg"  # photo id preserved
        assert row[2] == "{{en|1=A talk live}}"
        assert row[3] == "2026-06-05 10:00:00"
        assert row[4] == "[https://www.flickr.com/photos/36976328@N04/ re:publica 2026]"
        assert "12345" in row[5]
        assert row[7] == "{{Cc-by-2.0}}"

    def test_build_rows_tags_fallback(self):
        photos = [{
            "id": "1",
            "title": "Tokyo",
            "description": {"_content": ""},
            "tags": "Japan Tokyo",
            "owner": "u",
            "ownername": "U",
            "license": "9",
        }]
        args = ff.argparse.Namespace(tags_fallback=True, lang="en", user="u")
        row = ff.build_rows(photos, args)[0]
        assert row[2] == "{{en|1=Japan Tokyo}}"
