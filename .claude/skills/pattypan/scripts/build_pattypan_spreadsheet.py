#!/usr/bin/env python3
"""Build and validate pattypan upload spreadsheets (.xls).

Pattypan (https://github.com/yarl/pattypan) is a Wikimedia Commons batch
uploader that reads file descriptions from an Excel 97-2003 (.xls) workbook:

  * Sheet 0 "Data"     - row 0 holds column headers (path, name, plus one
                         column per template variable), rows 1..N hold one
                         file per row.
  * Sheet 1 "Template" - cell A1 holds the wikitext template with ${var}
                         placeholders, prefixed with a leading apostrophe.
                         The template is rendered with FreeMarker 2.3.23, so
                         directives like <#if>/<#list> and built-ins such as
                         ?split(";") / ?trim / ?has_content work.
  * Extra trailing sheets (e.g. a human-review "Overview") are ignored —
    pattypan reads getSheet(0) and getSheet(1) only.

This script writes that workbook with `xlwt` and validates the input using
the same rules pattypan enforces in Util.java and LoadPane.java
(filename characters, camera prefixes, allowed extensions, template-variable
coverage) plus Commons-level filename checks (no ':') and FreeMarker
directive-awareness for optional columns.

See SKILL.md for the full format contract and guardrails.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

# --- pattypan Util.java constants -------------------------------------------

ALLOWED_EXTENSIONS = {
    "djvu", "flac", "gif", "jpg", "jpeg", "mid", "mkv", "oga", "ogg",
    "ogv", "opus", "pdf", "png", "svg", "tiff", "tif", "wav", "webm",
    "webp", "xcf", "mp3", "stl",
}

# https://commons.wikimedia.org/wiki/MediaWiki:Filename-prefix-blacklist
BAD_FILENAME_PREFIXES = (
    "CIMG", "DSC_", "DSCF", "DSCN", "DUW", "GEDC", "IMG", "JD", "MGP",
    "PICT", "Imagen", "FOTO", "DSC", "SANY", "SAM",
)

# https://www.mediawiki.org/wiki/Manual:Page_title
INVALID_FILENAME_CHARS = set("#<>[]|{}")

VARIABLE_RE = re.compile(r"\$\{([^}]+)\}")

FORMULA_RISK_PREFIXES = ("=", "+", "-", "@")


# --- template helpers --------------------------------------------------------

def template_variables(template_text: str) -> list[str]:
    r"""Return the ${var} names referenced by the template, in order.

    Matches pattypan's own `Template.getComputedVariablesFromString` regex
    `\$\{(.*?)\}`, so built-in chains (e.g. `${category?trim}`) are included
    verbatim. Use `template_column_variables` when you need Data-column names.
    """
    return VARIABLE_RE.findall(template_text or "")


# FreeMarker directives may reference a data-model key without `${...}`:
#   <#if categories ? has_content> / <#list categories ? split(";") as category>
# pattypan renders the template with FreeMarker 2.3.23, so these are legal.
_DIRECTIVE_RE = re.compile(r"<#(?:if|elseif|list)\s+([A-Za-z_][A-Za-z0-9_]*)")

# <#list <expr> as <loopvar>> defines `loopvar` (a template-local name, not a
# Data column). The `<expr>` part may be anything (e.g. `categories ? split(";")`).
_LOOP_VAR_RE = re.compile(r"<#list\s+[^>]*?\bas\s+([A-Za-z_][A-Za-z0-9_]*)")


def template_column_variables(template_text: str) -> list[str]:
    """${var} names that map to Data columns, in order.

    Strips FreeMarker built-in chains (`${category?trim}` -> `category`) and
    drops template-local loop variables defined by `<#list ... as X>`.
    """
    loop_vars = set(_LOOP_VAR_RE.findall(template_text or ""))
    columns: list[str] = []
    for raw in template_variables(template_text):
        base = raw.split("?", 1)[0].strip()
        if not base or base in loop_vars:
            continue
        columns.append(base)
    return columns

# ':' is legal for pattypan but invalid in Commons filenames (namespace
# separator) — the upload fails later. Flag it as a warning.
COLON_IN_FILENAME_HINT = ":"

# Commons:File_naming hard limit. Bytes, not characters: non-ASCII characters
# take up to 4 bytes each. pattypan does not enforce this; the upload does.
COMMONS_MAX_FILENAME_BYTES = 240


def template_directive_variables(template_text: str) -> list[str]:
    """Return data-model keys referenced only in FreeMarker directives."""
    return _DIRECTIVE_RE.findall(template_text or "")


# --- manifest readers --------------------------------------------------------

def _read_delimited(path: Path, delimiter: str, encoding: str) -> tuple[list[str], list[list[str]]]:
    with path.open("r", encoding=encoding, newline="") as fh:
        reader = csv.reader(fh, delimiter=delimiter)
        rows = [row for row in reader]
    if not rows:
        return [], []
    rows = [[(cell or "").strip() for cell in row] for row in rows]
    headers = [h.strip() for h in rows[0]]
    return headers, rows[1:]


def _read_json(path: Path) -> tuple[list[str], list[list[str]]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list) or not data:
        return [], []
    if not all(isinstance(item, dict) for item in data):
        raise ValueError("JSON manifest must be a list of objects")
    headers: list[str] = []
    for item in data:
        for key in item:
            if key not in headers:
                headers.append(key)
    rows = [[str(item.get(h, "") or "").strip() for h in headers] for item in data]
    return headers, rows


def read_manifest(path: Path) -> tuple[list[str], list[list[str]]]:
    """Read a CSV/TSV/JSON manifest into (headers, rows)."""
    ext = path.suffix.lower()
    if ext == ".json":
        return _read_json(path)
    if ext == ".tsv":
        return _read_delimited(path, "\t", "utf-8")
    return _read_delimited(path, ",", "utf-8-sig")


def rows_from_directory(directory: Path, constants: dict, categories: str,
                        template_text: str,
                        name_pattern: str) -> tuple[list[str], list[list[str]], list[str]]:
    """Synthesize (headers, rows, warnings) for a directory of local files."""
    files = sorted(
        p for p in directory.iterdir()
        if p.is_file() and p.suffix.lower().lstrip(".") in ALLOWED_EXTENSIONS
    )
    headers = ["path", "name"]
    warnings: list[str] = []
    constants = constants or {}
    for var in template_column_variables(template_text):
        if var in ("path", "name"):
            continue
        if var == "categories":
            if "categories" not in headers:
                headers.append("categories")
        else:
            if var not in constants:
                warnings.append(
                    f"template variable '${var}' has no column and no --constants value; "
                    f"leaving it empty"
                )
            headers.append(var)

    rows = []
    for f in files:
        ext = f.suffix.lower().lstrip(".")
        name = name_pattern.format(
            name=f.stem, stem=f.stem, ext=ext, suffix=ext, path=str(f),
        )
        row: list[str] = [str(f.resolve()), name]
        for var in headers[2:]:
            if var == "categories":
                row.append(categories or "")
            elif var in constants:
                row.append(constants.get(var, ""))
            else:
                row.append("")
        rows.append(row)

    if not files:
        warnings.append("no files with allowed extensions found in directory")
    return headers, rows, warnings


# --- validation (mirrors pattypan Util.java / LoadPane.java) -----------------

def _is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _extension(value: str) -> str:
    name = Path(value).name
    if "." in name:
        return name.rsplit(".", 1)[1].lower()
    return ""


def validate(headers: list[str], rows: list[list[str]], template_text: str,
             check_paths: bool = True) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors must be fixed; warnings are advisory."""
    errors: list[str] = []
    warnings: list[str] = []

    if not headers:
        errors.append("manifest has no header row")
        return errors, warnings

    missing = [h for h in ("path", "name") if h not in headers]
    if missing:
        errors.append(f"headers must include 'path' and 'name' (missing: {', '.join(missing)})")

    # every ${var} in the template must have a column (pattypan fails otherwise).
    # Loop variables from <#list ... as X> and built-in chains (?trim etc.) are
    # template-local, so they are not required as columns.
    template_vars = template_column_variables(template_text)
    uncovered = [v for v in template_vars if v not in headers]
    if uncovered:
        errors.append(
            "template variables without matching columns: "
            + ", ".join(uncovered)
        )

    # FreeMarker directive references are optional: `?has_content` guards them,
    # so pattypan renders a `<#else>` fallback instead of failing the load.
    known = set(headers) | set(template_vars)
    for var in template_directive_variables(template_text):
        if var not in known and var not in ("category", "file", "item"):
            warnings.append(
                f"template references '{var}' in a FreeMarker directive but no column "
                f"exists — pattypan will take the <#else> fallback (add a '{var}' "
                f"column to populate it)"
            )

    for idx, row in enumerate(rows, start=2):  # row 1 is the header
        if not any(row):
            warnings.append(f"row {idx}: blank row skipped by pattypan")
            continue
        data = dict(zip(headers, row))
        path = data.get("path", "")
        name = data.get("name", "")

        if not path:
            errors.append(f"row {idx}: empty path")
        if not name:
            errors.append(f"row {idx}: empty name")
            continue

        for ch in name:
            if ch in INVALID_FILENAME_CHARS:
                errors.append(
                    f"row {idx}: '{name}' contains invalid filename character '{ch}' "
                    f"(# < > [ ] | {{ }})"
                )
                break

        if COLON_IN_FILENAME_HINT in name:
            warnings.append(
                f"row {idx}: '{name}' contains ':' — pattypan accepts it but Commons "
                f"filenames cannot contain ':' (replace with '-')"
            )

        name_bytes = len(name.encode("utf-8"))
        if name_bytes > COMMONS_MAX_FILENAME_BYTES:
            warnings.append(
                f"row {idx}: '{name}' is {name_bytes} bytes — Commons filenames are "
                f"limited to 240 bytes (non-ASCII up to 4 bytes per character)"
            )

        for prefix in BAD_FILENAME_PREFIXES:
            if name.startswith(prefix):
                warnings.append(
                    f"row {idx}: '{name}' starts with camera-name prefix '{prefix}' — "
                    f"rename to something descriptive"
                )
                break

        if _is_url(path):
            if not name.lower().endswith(tuple("." + e for e in ALLOWED_EXTENSIONS)):
                errors.append(
                    f"row {idx}: URL path requires '{name}' to include a valid file extension"
                )
        elif check_paths:
            if not Path(path).is_file():
                errors.append(f"row {idx}: file not found: {path}")

        # extension mismatch: pattypan appends the path extension to the name
        if not _is_url(path):
            path_ext = _extension(path)
            name_ext = _extension(name)
            if name_ext and path_ext and name_ext != path_ext:
                warnings.append(
                    f"row {idx}: name extension '{name_ext}' differs from file extension "
                    f"'{path_ext}' — pattypan will rename it to '{name}.{path_ext}'"
                )

        for var in ("description", "source", "author", "date", "categories"):
            if var in data and not data.get(var, ""):
                warnings.append(f"row {idx}: empty value for '{var}'")

        for value in row:
            if value and value[0] in FORMULA_RISK_PREFIXES:
                warnings.append(
                    f"row {idx}: value starting with '{value[0]}' may be read as a formula "
                    f"by Excel; quote it if intended"
                )

    return errors, warnings


# --- writer ------------------------------------------------------------------

def build_xls(headers: list[str], rows: list[list[str]], template_text: str,
              output_path: Path) -> None:
    """Write the two-sheet .xls workbook pattypan expects."""
    try:
        import xlwt
    except ImportError as exc:  # deferred import: --help must work without xlwt
        raise SystemExit(
            "error: xlwt is required to write .xls files. Install it with:\n"
            "    pip install xlwt"
        ) from exc

    workbook = xlwt.Workbook(encoding="utf-8")

    data_sheet = workbook.add_sheet("Data")
    for col, header in enumerate(headers):
        data_sheet.write(0, col, header)
    for r, row in enumerate(rows, start=1):
        for col, value in enumerate(row):
            if col < len(headers):
                data_sheet.write(r, col, value)

    template_sheet = workbook.add_sheet("Template")
    # leading apostrophe prevents Excel treating the wikitext as a formula;
    # pattypan strips it on load.
    template_sheet.write(0, 0, "'" + template_text)

    workbook.save(str(output_path))


# --- CLI ---------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_pattypan_spreadsheet.py",
        description=(
            "Build a pattypan-valid Excel 97-2003 (.xls) upload spreadsheet "
            "with a Data sheet and a Template sheet."
        ),
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--manifest", type=Path, metavar="FILE",
        help="CSV/TSV/JSON manifest. First row/CSV = headers "
             "(must include path and name); JSON = list of objects.",
    )
    source.add_argument(
        "--dir", type=Path, metavar="DIR",
        help="Directory of local files to upload (allowed extensions only).",
    )
    parser.add_argument(
        "--template", type=Path, metavar="FILE", required=True,
        help="Wikitext template file with ${var} placeholders.",
    )
    parser.add_argument(
        "--output", type=Path, metavar="OUT.xls",
        help="Output .xls path (required unless --check-only).",
    )
    parser.add_argument(
        "--constants", type=str, metavar="JSON|FILE",
        help="JSON mapping of template variable -> constant value applied to "
             "every row (used with --dir; also fills empty columns). Pass "
             "inline JSON, e.g. --constants '{\"author\":\"Jane\"}', or a "
             "path to a .json file to avoid shell-quoting problems.",
    )
    parser.add_argument(
        "--categories", type=str, default="", metavar="CATS",
        help="Default categories for the categories column (pipe-separated).",
    )
    parser.add_argument(
        "--name-pattern", type=str, default="{name}", metavar="PATTERN",
        help="Commons filename pattern for --dir mode. Tokens: {name} (source "
             "basename), {ext}, {path}. Default: '{name}'.",
    )
    parser.add_argument(
        "--date-from-exif", action="store_true",
        help="Fill empty date cells from EXIF DateTimeOriginal "
             "(requires Pillow; ignored when unavailable).",
    )
    parser.add_argument(
        "--no-check-paths", action="store_true",
        help="Do not require local path values to exist on disk.",
    )
    parser.add_argument(
        "--check-only", action="store_true",
        help="Validate the manifest/template only; do not write the .xls.",
    )
    return parser


def _parse_constants(raw: str | None) -> dict:
    if not raw:
        return {}
    # Accept inline JSON or a path to a JSON file (avoids shell-quoting issues).
    payload = raw
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        candidate = Path(raw)
        if candidate.is_file():
            value = json.loads(candidate.read_text(encoding="utf-8-sig"))
        else:
            raise SystemExit(
                "error: --constants is neither valid inline JSON nor a path to a "
                "JSON file"
            )
    if not isinstance(value, dict):
        raise SystemExit("error: --constants must be a JSON object")
    return {str(k): str(v) for k, v in value.items()}


def _fill_from_exif(headers: list[str], rows: list[list[str]]) -> list[str]:
    if "date" not in headers:
        return []
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS
    except ImportError:
        return ["--date-from-exif ignored: Pillow not installed"]
    warnings = []
    date_col = headers.index("date")
    for idx, row in enumerate(rows):
        if row[date_col]:
            continue
        path = row[headers.index("path")]
        if path.startswith(("http://", "https://")):
            continue
        try:
            exif = Image.open(path).getexif()
            tag = next((k for k, v in TAGS.items() if v == "DateTimeOriginal"), None)
            if tag and exif.get(tag):
                row[date_col] = str(exif.get(tag)).replace(":", "-", 2)[:16]
            else:
                warnings.append(f"row {idx + 2}: no EXIF date for {path}")
        except Exception:
            warnings.append(f"row {idx + 2}: could not read EXIF for {path}")
    return warnings


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    if argv is None and len(sys.argv) == 1:
        parser.print_help()
        return 1
    args = parser.parse_args(argv)

    if args.output is None and not args.check_only:
        parser.error("--output is required unless --check-only is used")

    template_text = args.template.read_text(encoding="utf-8-sig")
    if template_text.startswith("'"):
        template_text = template_text[1:]

    constants = _parse_constants(args.constants)

    if args.manifest is not None:
        headers, rows = read_manifest(args.manifest)
        warnings: list[str] = []
        # fill empty cells for constant values (also in manifest mode)
        for var, value in constants.items():
            if var in headers:
                col = headers.index(var)
                for row in rows:
                    if not row[col]:
                        row[col] = value
    else:
        headers, rows, warnings = rows_from_directory(
            args.dir, constants, args.categories, template_text, args.name_pattern,
        )

    errors, more_warnings = validate(
        headers, rows, template_text, check_paths=not args.no_check_paths
    )
    warnings.extend(more_warnings)

    if args.date_from_exif:
        warnings.extend(_fill_from_exif(headers, rows))

    # report (diagnostics go to stderr; stdout stays clean for piping)
    report = [f"rows: {len(rows)}, columns: {len(headers)}", f"errors: {len(errors)}"]
    report += [f"  ERROR: {e}" for e in errors]
    report += [f"warnings: {len(warnings)}"]
    report += [f"  WARN:  {w}" for w in warnings]
    if errors:
        report.append("validation failed — fix the errors above before uploading")
    elif args.check_only:
        report.append("validation passed (--check-only, no file written)")
    else:
        build_xls(headers, rows, template_text, args.output)
        report.append(f"wrote {args.output}")
    for line in report:
        print(line, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
