"""Tests for the pattypan skill: SKILL.md content and the spreadsheet builder script."""

import os
import re
import sys
from pathlib import Path

import pytest

from conftest import SKILLS_DIR, read_skill  # noqa: E402

SCRIPT_DIR = SKILLS_DIR / "pattypan" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import build_pattypan_spreadsheet as pp  # noqa: E402

TEMPLATE = (
    "{{Information\n"
    "|description={{en|1=${description}}}\n"
    "|date=${date}\n"
    "|source=${source}\n"
    "|author=${author}\n"
    "}}\n"
    "[[Category:${categories}]]"
)

GOOD_HEADERS = ["path", "name", "description", "date", "author", "source", "categories"]
GOOD_ROWS = [
    ["/tmp/a.jpg", "Eiffel Tower", "View of the tower", "1889-03-31", "Jane Doe", "{{own}}", "Monuments of Paris"],
    ["/tmp/b.jpg", "Louvre", "Courtyard", "2024-05-02", "John Smith", "{{own}}", "Musee du Louvre"],
]


class TestSkillContent:
    """Key assertions about the pattypan SKILL.md (mirrors test_markdown_sops style)."""

    def test_two_sheet_contract_documented(self):
        text = read_skill("pattypan")
        assert "Data" in text and "Template" in text
        assert "at least two sheets" in text

    def test_xls_not_xlsx_guardrail(self):
        text = read_skill("pattypan")
        assert "Excel 97-2003" in text
        assert "xlsx" in text  # must explicitly warn against .xlsx
        assert "CSV" in text

    def test_path_and_name_headers(self):
        text = read_skill("pattypan")
        assert "`path` and `name`" in text

    def test_apostrophe_template(self):
        text = read_skill("pattypan")
        assert "apostrophe" in text.lower()

    def test_variables_mismatch_error(self):
        text = read_skill("pattypan")
        assert "variables mismatch" in text

    def test_reference_doc_and_script_mentioned(self):
        text = read_skill("pattypan")
        assert "build_pattypan_spreadsheet.py" in text
        assert "pattypan-spreadsheet-format.md" in text

    def test_depends_on_commons(self):
        text = read_skill("pattypan")
        assert "wikimedia-commons" in text


class TestTemplateHelpers:
    def test_template_variables_in_order(self):
        assert pp.template_variables(TEMPLATE) == [
            "description", "date", "source", "author", "categories",
        ]

    def test_template_variables_empty(self):
        assert pp.template_variables("") == []
        assert pp.template_variables("no placeholders here") == []

    def test_template_variables_dedups_nothing(self):
        assert pp.template_variables("${a} ${a}") == ["a", "a"]

    def test_directive_variables_extracted(self):
        tpl = "<#if categories ? has_content>\n<#list categories ? split(';') as c>\n</#if>\n"
        assert pp.template_directive_variables(tpl) == ["categories", "categories"]

    def test_directive_variables_ignore_loop_var(self):
        # the <#list ... as category> loop variable is NOT a data-model key
        tpl = "<#list categories ? split(';') as category>\n</#list>\n"
        assert pp.template_directive_variables(tpl) == ["categories"]

    def test_directive_variables_empty(self):
        assert pp.template_directive_variables("${a} only") == []
        assert pp.template_directive_variables("") == []

    def test_column_variables_strips_builtins_and_loop_vars(self):
        tpl = ("{{Information\n"
               "|description=${description}\n"
               "}}\n"
               "<#list categories ? split(';') as category>\n"
               "[[Category:${category?trim}]]\n"
               "</#list>\n")
        assert pp.template_column_variables(tpl) == ["description"]


class TestValidate:
    def test_good_manifest_no_errors(self):
        errors, warnings = pp.validate(GOOD_HEADERS, GOOD_ROWS, TEMPLATE, check_paths=False)
        assert errors == []
        assert warnings == []

    def test_missing_path_or_name_headers(self):
        errors, _ = pp.validate(["name", "description"], GOOD_ROWS, TEMPLATE, check_paths=False)
        assert any("'path' and 'name'" in e for e in errors)

    def test_uncovered_template_variable_is_error(self):
        # template references ${artist} but headers have no artist column
        tpl = TEMPLATE + "|artist=${artist}\n"
        errors, _ = pp.validate(GOOD_HEADERS, GOOD_ROWS, tpl, check_paths=False)
        assert any("artist" in e for e in errors)

    def test_extra_column_is_allowed(self):
        headers = GOOD_HEADERS + ["location"]
        rows = [row + ["Paris"] for row in GOOD_ROWS]
        errors, _ = pp.validate(headers, rows, TEMPLATE, check_paths=False)
        assert errors == []

    def test_invalid_filename_characters(self):
        rows = [["/tmp/a.jpg", "Bad [name].jpg", "x", "2024-01-01", "a", "b", "c"]]
        errors, _ = pp.validate(GOOD_HEADERS, rows, TEMPLATE, check_paths=False)
        assert any("invalid filename character" in e for e in errors)

    def test_camera_prefix_is_warning(self):
        rows = [["/tmp/a.jpg", "IMG_1234.jpg", "x", "2024-01-01", "a", "b", "c"]]
        _, warnings = pp.validate(GOOD_HEADERS, rows, TEMPLATE, check_paths=False)
        assert any("camera-name prefix" in w for w in warnings)

    def test_missing_local_file_is_error(self, tmp_path):
        rows = [[str(tmp_path / "nope.jpg"), "File one", "x", "2024-01-01", "a", "b", "c"]]
        errors, _ = pp.validate(GOOD_HEADERS, rows, TEMPLATE, check_paths=True)
        assert any("file not found" in e for e in errors)

    def test_url_requires_extension_in_name(self):
        rows = [["https://example.com/img.jpg", "No extension", "x", "2024-01-01", "a", "b", "c"]]
        errors, _ = pp.validate(GOOD_HEADERS, rows, TEMPLATE, check_paths=False)
        assert any("valid file extension" in e for e in errors)

    def test_url_with_extension_ok(self):
        rows = [["https://example.com/img.jpg", "Has extension.jpg", "x", "2024-01-01", "a", "b", "c"]]
        errors, _ = pp.validate(GOOD_HEADERS, rows, TEMPLATE, check_paths=False)
        assert errors == []

    def test_blank_row_warns(self):
        rows = [["", "", "", "", "", "", ""]]
        _, warnings = pp.validate(GOOD_HEADERS, rows, TEMPLATE, check_paths=False)
        assert any("blank row" in w for w in warnings)

    def test_colon_in_filename_warns(self):
        rows = [["/tmp/a.jpg", "Re:publica photo.jpg", "x", "2024-01-01", "a", "b", "c"]]
        errors, warnings = pp.validate(GOOD_HEADERS, rows, TEMPLATE, check_paths=False)
        assert errors == []
        assert any("Commons" in w and "':'" in w for w in warnings)

    def test_filename_at_240_bytes_ok(self):
        rows = [["/tmp/a.jpg", "A" * 240, "x", "2024-01-01", "a", "b", "c"]]
        errors, warnings = pp.validate(GOOD_HEADERS, rows, TEMPLATE, check_paths=False)
        assert errors == []
        assert not any("240 bytes" in w for w in warnings)

    def test_filename_over_240_bytes_warns(self):
        rows = [["/tmp/a.jpg", "A" * 241, "x", "2024-01-01", "a", "b", "c"]]
        _, warnings = pp.validate(GOOD_HEADERS, rows, TEMPLATE, check_paths=False)
        assert any("240 bytes" in w for w in warnings)

    def test_byte_limit_counts_utf8_not_characters(self):
        # "é" is 2 UTF-8 bytes: 121 chars = 242 bytes > 240, even though it is < 240 characters
        rows = [["/tmp/a.jpg", "é" * 121, "x", "2024-01-01", "a", "b", "c"]]
        errors, warnings = pp.validate(GOOD_HEADERS, rows, TEMPLATE, check_paths=False)
        assert errors == []
        assert any("242 bytes" in w for w in warnings)

    def test_short_non_ascii_name_ok(self):
        # 60 x "é" = 120 bytes, well under the limit
        rows = [["/tmp/a.jpg", "é" * 60, "x", "2024-01-01", "a", "b", "c"]]
        _, warnings = pp.validate(GOOD_HEADERS, rows, TEMPLATE, check_paths=False)
        assert not any("240 bytes" in w for w in warnings)

    def test_directive_reference_without_column_warns_not_errors(self):
        # FreeMarker guards optional columns with ?has_content, so a directive-only
        # reference to a missing column must be a warning, not an error
        tpl = ("{{Information\n"
               "|description=${description}\n"
               "}}\n"
               "<#if extra ? has_content>has extra metadata</#if>\n")
        headers = ["path", "name", "description"]
        rows = [["/tmp/a.jpg", "A photo", "desc"]]
        errors, warnings = pp.validate(headers, rows, tpl, check_paths=False)
        assert errors == []
        assert any("'extra' in a FreeMarker directive" in w for w in warnings)

    def test_loop_variable_and_builtin_are_not_columns(self):
        # `${category?trim}` inside a <#list ... as category> block refers to the
        # loop variable, not a Data column - so it must not be reported as missing
        tpl = ("{{Information\n"
               "|description=${description}\n"
               "}}\n"
               "<#list categories ? split(';') as category>\n"
               "[[Category:${category?trim}]]\n"
               "</#list>\n")
        headers = ["path", "name", "description", "categories"]
        rows = [["/tmp/a.jpg", "A photo", "desc", "Paris;France"]]
        errors, warnings = pp.validate(headers, rows, tpl, check_paths=False)
        assert errors == []
        assert not any("without matching columns" in e for e in errors)

    def test_directive_reference_with_column_ok(self):
        tpl = ("{{Information\n|description=${description}\n}}\n"
               "<#if categories ? has_content>\n"
               "<#list categories ? split(';') as category>\n"
               "[[Category:${category?trim}]]\n"
               "</#list>\n"
               "<#else>{{subst:unc}}\n"
               "</#if>\n")
        headers = ["path", "name", "description", "categories"]
        rows = [["/tmp/a.jpg", "A photo", "desc", "Paris;France"]]
        errors, warnings = pp.validate(headers, rows, tpl, check_paths=False)
        assert errors == []
        assert not any("FreeMarker directive" in w for w in warnings)



class TestValidateNewChecks:
    """New batch-level and value-safety checks (2026-08 audit additions)."""

    def test_dollar_brace_in_value_is_error(self):
        # A literal ${...} in a cell value is interpolated by FreeMarker at
        # render time; a reference to a missing column aborts the whole load.
        rows = [["/tmp/a.jpg", "A photo", "Price was ${100} dollars",
                 "2024-01-01", "Jane", "{{own}}", "Paris"]]
        errors, _ = pp.validate(GOOD_HEADERS, rows, TEMPLATE, check_paths=False)
        assert any("interpolate" in e and "row 2" in e for e in errors)

    def test_pipe_in_description_warns(self):
        rows = [["/tmp/a.jpg", "A photo", "a | b description",
                 "2024-01-01", "Jane", "{{own}}", "Paris"]]
        _, warnings = pp.validate(GOOD_HEADERS, rows, TEMPLATE, check_paths=False)
        assert any("HTML-entity-escaped" in w for w in warnings)

    def test_pipe_in_author_warns(self):
        rows = [["/tmp/a.jpg", "A photo", "desc",
                 "2024-01-01", "Jane | Smith", "{{own}}", "Paris"]]
        _, warnings = pp.validate(GOOD_HEADERS, rows, TEMPLATE, check_paths=False)
        assert any("author" in w and "|" in w for w in warnings)

    def test_pipe_categories_warns(self):
        # pattypan's templates split categories on ';'; a '|' becomes a sortkey
        rows = [["/tmp/a.jpg", "A photo", "desc", "2024-01-01", "Jane", "{{own}}",
                 "Monuments of Paris|Eiffel Tower"]]
        _, warnings = pp.validate(GOOD_HEADERS, rows, TEMPLATE, check_paths=False)
        assert any("sortkey" in w for w in warnings)

    def test_duplicate_name_warns(self):
        rows = [
            ["/tmp/a.jpg", "Same name.jpg", "d1", "2024-01-01", "a", "{{own}}", "X"],
            ["/tmp/b.jpg", "Same name.jpg", "d2", "2024-01-01", "b", "{{own}}", "Y"],
        ]
        _, warnings = pp.validate(GOOD_HEADERS, rows, TEMPLATE, check_paths=False)
        assert any("duplicate name" in w and "row 3" in w for w in warnings)

    def test_duplicate_path_warns(self):
        rows = [
            ["/tmp/a.jpg", "One.jpg", "d1", "2024-01-01", "a", "{{own}}", "X"],
            ["/tmp/a.jpg", "Two.jpg", "d2", "2024-01-01", "b", "{{own}}", "Y"],
        ]
        _, warnings = pp.validate(GOOD_HEADERS, rows, TEMPLATE, check_paths=False)
        assert any("duplicate path" in w and "row 3" in w for w in warnings)

    def test_row_limit_warns(self):
        rows = [
            [f"/tmp/f{i}.jpg", f"File {i}", "d", "2024-01-01", "a", "{{own}}", "X"]
            for i in range(65500)
        ]
        _, warnings = pp.validate(GOOD_HEADERS, rows, TEMPLATE, check_paths=False)
        assert any("65,536" in w for w in warnings)

    def test_all_empty_template_column_warns(self):
        # description column referenced by the template but empty in every row
        rows = [["/tmp/a.jpg", "A photo", "", "2024-01-01", "Jane", "{{own}}", "Paris"]]
        _, warnings = pp.validate(GOOD_HEADERS, rows, TEMPLATE, check_paths=False)
        assert any("column 'description' is empty in every row" in w for w in warnings)

    def test_good_rows_still_clean(self):
        errors, warnings = pp.validate(GOOD_HEADERS, GOOD_ROWS, TEMPLATE, check_paths=False)
        assert errors == []
        assert warnings == []

class TestRowsFromDirectory:
    def test_builds_rows_with_constants(self, tmp_path):
        (tmp_path / "a.jpg").write_bytes(b"x")
        (tmp_path / "b.png").write_bytes(b"x")
        headers, rows, warnings = pp.rows_from_directory(
            tmp_path, {"author": "Jane", "source": "{{own}}"}, "Paris", TEMPLATE, "{name}",
        )
        assert headers == ["path", "name", "description", "date", "source", "author", "categories"]
        assert len(rows) == 2
        for row in rows:
            data = dict(zip(headers, row))
            assert data["author"] == "Jane"
            assert data["source"] == "{{own}}"
            assert data["categories"] == "Paris"

    def test_empty_directory_warns(self, tmp_path):
        headers, rows, warnings = pp.rows_from_directory(tmp_path, {}, "", TEMPLATE, "{name}")
        assert rows == []
        assert any("no files" in w for w in warnings)

    def test_ignores_disallowed_extensions(self, tmp_path):
        (tmp_path / "a.jpg").write_bytes(b"x")
        (tmp_path / "b.txt").write_bytes(b"x")  # not in ALLOWED_EXTENSIONS
        _, rows, _ = pp.rows_from_directory(tmp_path, {}, "", TEMPLATE, "{name}")
        assert len(rows) == 1


class TestBuildXls:
    @pytest.fixture
    def xlwt(self):
        return pytest.importorskip("xlwt")

    def test_output_has_two_sheets(self, tmp_path, xlwt):
        out = tmp_path / "upload.xls"
        pp.build_xls(GOOD_HEADERS, GOOD_ROWS, TEMPLATE, out)
        assert out.exists()
        xlrd = pytest.importorskip("xlrd")
        wb = xlrd.open_workbook(str(out))
        assert wb.sheet_names() == ["Data", "Template"]
        data = wb.sheet_by_name("Data")
        assert data.ncols == len(GOOD_HEADERS)
        assert data.nrows == 1 + len(GOOD_ROWS)
        assert [data.cell_value(0, c) for c in range(data.ncols)] == GOOD_HEADERS
        assert data.cell_value(1, 1) == "Eiffel Tower"

    def test_template_cell_prefixed_with_apostrophe(self, tmp_path, xlwt):
        out = tmp_path / "upload.xls"
        pp.build_xls(GOOD_HEADERS, GOOD_ROWS, TEMPLATE, out)
        xlrd = pytest.importorskip("xlrd")
        wb = xlrd.open_workbook(str(out))
        tpl = wb.sheet_by_name("Template")
        value = tpl.cell_value(0, 0)
        assert value.startswith("'")
        assert "{{Information" in value
        assert "${description}" in value

    def test_non_ascii_roundtrip(self, tmp_path, xlwt):
        rows = [["/tmp/a.jpg", "Été 2024", "Красивый вид", "2024-01-01", "Иван", "{{own}}", "Категория"]]
        headers = ["path", "name", "description", "date", "author", "source", "categories"]
        out = tmp_path / "upload.xls"
        pp.build_xls(headers, rows, TEMPLATE, out)
        xlrd = pytest.importorskip("xlrd")
        wb = xlrd.open_workbook(str(out))
        data = wb.sheet_by_name("Data")
        assert data.cell_value(1, 1) == "Été 2024"
        assert data.cell_value(1, 2) == "Красивый вид"


class TestCli:
    def test_no_args_exits_1(self):
        # pp.main(None) with no argv is the zero-arg guard path
        old = sys.argv
        sys.argv = ["build_pattypan_spreadsheet.py"]
        try:
            assert pp.main(None) == 1
        finally:
            sys.argv = old

    def test_missing_template_is_usage_error(self):
        # argparse requires --template: SystemExit(2)
        with pytest.raises(SystemExit) as exc:
            pp.main(["--manifest", "x.csv"])
        assert exc.value.code == 2

    def test_missing_output_is_usage_error(self):
        # --output required unless --check-only: SystemExit(2)
        with pytest.raises(SystemExit) as exc:
            pp.main(["--manifest", "x.csv", "--template", "t.txt"])
        assert exc.value.code == 2

    def test_invalid_constants_rejects(self, tmp_path):
        (tmp_path / "t.txt").write_text("${a}", encoding="utf-8")
        (tmp_path / "m.csv").write_text("path,name\n/tmp/a.jpg,Foo\n", encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            pp.main(["--manifest", str(tmp_path / "m.csv"),
                     "--template", str(tmp_path / "t.txt"),
                     "--constants", "{not json", "--check-only"])
        assert "valid inline JSON" in str(exc.value)

    def test_check_only_full_run(self, tmp_path):
        (tmp_path / "t.txt").write_text(TEMPLATE, encoding="utf-8")
        photo = tmp_path / "a.jpg"
        photo.write_bytes(b"x")
        manifest = tmp_path / "m.csv"
        manifest.write_text(
            "path,name,description,date,author,source,categories\n"
            f"{photo},Eiffel Tower,View,1889-03-31,Jane Doe,{{{{own}}}},Paris\n",
            encoding="utf-8",
        )
        assert pp.main(["--manifest", str(manifest),
                        "--template", str(tmp_path / "t.txt"),
                        "--check-only"]) == 0

    def test_check_only_detects_missing_file(self, tmp_path):
        (tmp_path / "t.txt").write_text(TEMPLATE, encoding="utf-8")
        manifest = tmp_path / "m.csv"
        manifest.write_text(
            "path,name,description,date,author,source,categories\n"
            "/definitely/not/here.jpg,Eiffel Tower,View,1889-03-31,Jane Doe,{{own}},Paris\n",
            encoding="utf-8",
        )
        assert pp.main(["--manifest", str(manifest),
                        "--template", str(tmp_path / "t.txt"),
                        "--check-only"]) == 1
