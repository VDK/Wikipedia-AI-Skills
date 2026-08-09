#!/usr/bin/env python3
"""Helpers for building and validating QuickStatements (QS) V1 command batches.

Covers the V1 pipe syntax used by the QuickStatements web tool and API:
statements with qualifiers and sources, labels/descriptions/aliases
(including the multilingual `Lmul`/`Amul` commands), item creation via
CREATE/LAST, merging, removal, and the `#/v1=` URL encoding.

Pure functions only; no network access. See
references/quickstatements-syntax.md for the full grammar.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.parse

# ---------------------------------------------------------------------------
# Field shapes
# ---------------------------------------------------------------------------

# Items (Q...), Commons media (M...), lexemes/forms/senses (L..., L...-F.., L...-S..)
ENTITY_RE = re.compile(r"^(?:Q|M)\d+$|^L\d+(-[FS]\d+)?$")
LAST_RE = re.compile(r"^LAST$")
PROPERTY_RE = re.compile(r"^P\d+$")
# label / description / alias commands: Len, Lmul, Dnl, Ade, ...
TEXT_CMD_RE = re.compile(r"^[LAD][a-z]{2,3}$")
# sitelink commands: Senwiki, Scommonswiki, Szhwiki, ...
SITELINK_RE = re.compile(r"^S[a-z]{2,6}wiki(quote|source|news|voyage|books|versity)*$")
# reference properties: S143, !S248 (leading ! starts a new reference group)
SOURCE_RE = re.compile(r"^!?S\d+$")
# date/time: +1967-01-17T00:00:00Z/11  (+ = CE, - = BCE, /N = precision, optional /J)
TIME_RE = re.compile(r"^[+-]\d{4,}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z/\d+(?:J)?$")
# coordinates: @43.26193/10.92708
COORD_RE = re.compile(r"^@-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)?$")
# quantity: 10, +60U11573, 5.5U11574, -80~1.5, 2.2~0.3, V1 range 1.2[-12.5,-7.5]
QUANTITY_RE = re.compile(
    r"^[+-]?\d+(?:\.\d+)?(?:~[+-]?\d+(?:\.\d+)?)?U?\d*$"
    r"|^[+-]?\d+(?:\.\d+)?\[[+-]?\d+(?:\.\d+)?,[+-]?\d+(?:\.\d+)?\]U?\d*$"
)
MONOLINGUAL_RE = re.compile(r"^[a-z]{2,3}:")
QID_RE = re.compile(r"^Q\d+$", re.I)
# QS 3.0 statement-rank tokens (R+ / R0 / R- / long forms)
RANKS = {"R+", "R0", "R-", "Rpreferred", "Rnormal", "Rdeprecated"}
# statement-ID removal: Q1$00000000-0000-0000-0000-000000000000
STATEMENT_ID_RE = re.compile(
    r"^[QM]\d+\$[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I)
# well-known date/time properties, used to nudge on bare-year mistakes
TIME_PROPERTY_HINTS = {"P569", "P570", "P571", "P572", "P575", "P576", "P577",
                       "P580", "P582", "P585", "P813", "P1319", "P1326",
                       "P2960", "P2031", "P2032"}
# QS 3.0-only command lines
QS3_LINE_CMDS = ("REMOVE_QUAL", "REMOVE_REF", "REMOVE_REF_BLOCK",
                 "SWITCH_VALUE", "SWITCH_PROPERTY", "SWITCH_PROPERTY_AND_VALUE")


def format_time(year, month=None, day=None, precision=None, era="+"):
    """Build a QS time value for a (possibly partial) date.

    precision defaults to the finest component given (year=9, month=10,
    day=11). `era` is "+" for CE dates, "-" for BCE.
    """
    if precision is None:
        precision = 11 if day is not None else 10 if month is not None else 9
    mm = "%02d" % month if month is not None else "00"
    dd = "%02d" % day if day is not None else "00"
    if not 0 <= precision <= 11:
        raise ValueError("precision must be between 0 and 11")
    return f"{era}{year:04d}-{mm}-{dd}T00:00:00Z/{precision}"


def quote_string(text):
    """Escape and double-quote a string value."""
    return '"' + str(text).replace('"', '\\"') + '"'


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _check_value(value):
    """Validate one value token. Returns (severity, message); both None if OK.

    severity is 'error' or 'warning'.
    """
    v = value.strip()
    if not v:
        return "error", "missing value"
    if v in ("somevalue", "novalue"):
        return None, None
    if v.startswith('"'):
        if not v.endswith('"'):
            return "error", "unterminated string value (missing closing quote)"
        return None, None
    if MONOLINGUAL_RE.match(v):
        if not (v.endswith('"') and '"' in v[3:]):
            return "error", 'monolingual text must look like en:"Some text"'
        return None, None
    if QID_RE.match(v) or ENTITY_RE.match(v):
        return None, None
    if TIME_RE.match(v):
        precision = int(v.split("Z/")[1].rstrip("J"))
        if not 0 <= precision <= 11:
            return "error", f"date precision /{precision} is out of range (0-11)"
        return None, None
    if COORD_RE.match(v):
        return None, None
    if QUANTITY_RE.match(v):
        return None, None
    if re.match(r"^[A-Za-z]", v):
        return "error", f"'{v}' looks like a string but is not double-quoted"
    return None, None


def _validate_statement(parts, line_no, issues):
    entity = parts[0]
    if entity.startswith("-"):
        if not ENTITY_RE.match(entity[1:]) and not QID_RE.match(entity[1:]):
            issues.append((line_no, "error", f"invalid entity '{entity[1:]}' in removal"))
    elif entity.startswith("+"):
        # QS 3.0: a leading '+' forces creation of a duplicate statement
        if not ENTITY_RE.match(entity[1:]):
            issues.append((line_no, "error", f"invalid entity '{entity[1:]}' in forced statement"))
    elif entity != "LAST" and not ENTITY_RE.match(entity):
        issues.append((line_no, "error", f"invalid entity '{entity}'"))
    if len(parts) < 2:
        issues.append((line_no, "error", "statement is missing a property/command"))
        return

    def _report(cmd_key, value):
        severity, msg = _check_value(value)
        if severity == "error":
            issues.append((line_no, "error", f"{cmd_key}: {msg}"))
        elif severity == "warning":
            issues.append((line_no, "warning", f"{cmd_key}: {msg}"))

    cmd = parts[1]
    if PROPERTY_RE.match(cmd):
        value = parts[2] if len(parts) > 2 else ""
        _report(cmd, value)
        if cmd in TIME_PROPERTY_HINTS and re.match(r"^[+-]?\d{4}$", value.strip()):
            # bare year is the single most common time-format mistake
            issues.append((line_no, "warning",
                           f"{cmd}: '{value.strip()}' looks like a year; "
                           f"use +{value.strip()}-00-00T00:00:00Z/9 for a date"))
    elif TEXT_CMD_RE.match(cmd):
        if cmd[1:] == "mul" and cmd[0] != "L":
            issues.append((line_no, "warning", f"'{cmd}': only labels and aliases support 'mul'"))
        value = parts[2] if len(parts) > 2 else ""
        if value != "" and not (value.startswith('"') and value.endswith('"')):
            issues.append((line_no, "error", f"{cmd}: label/description/alias must be a quoted string"))
    elif SITELINK_RE.match(cmd):
        value = parts[2] if len(parts) > 2 else ""
        if value != "" and not (value.startswith('"') and value.endswith('"')):
            issues.append((line_no, "error", f"{cmd}: sitelink must be a quoted string"))
    elif cmd.startswith("!"):
        issues.append((line_no, "error", f"'!{cmd[1:]}' is only valid as a reference property (after a P statement)"))
    else:
        issues.append((line_no, "error", f"unknown command '{cmd}'"))

    if PROPERTY_RE.match(cmd):
        i = 3
        while i < len(parts):
            key = parts[i]
            if key in RANKS:
                # QS 3.0 rank token is standalone: R+ / R0 / R- / long forms
                i += 1
                continue
            val = parts[i + 1] if i + 1 < len(parts) else ""
            if SOURCE_RE.match(key) or PROPERTY_RE.match(key):
                pass  # source property (S143 / !S248) or qualifier property (P1545)
            else:
                issues.append((line_no, "error", f"invalid qualifier/source property '{key}'"))
            _report(key, val)
            i += 2


def _validate_qs3_line(line, line_no, issues):
    """Light validation for QS 3.0-only line commands (REMOVE_*/SWITCH_*)."""
    parts = line.split("|")
    cmd, rest = parts[0], parts[1:]
    min_fields = {"REMOVE_QUAL": 6, "REMOVE_REF": 6, "REMOVE_REF_BLOCK": 6,
                  "SWITCH_VALUE": 5, "SWITCH_PROPERTY": 5,
                  "SWITCH_PROPERTY_AND_VALUE": 6}[cmd]
    if len(parts) < min_fields:
        issues.append((line_no, "error",
                       f"{cmd} needs at least {min_fields} fields (got {len(parts)})"))
        return
    if not (ENTITY_RE.match(rest[0]) or rest[0] == "LAST"):
        issues.append((line_no, "error", f"{cmd}: invalid entity '{rest[0]}'"))
    if not PROPERTY_RE.match(rest[1]):
        issues.append((line_no, "error", f"{cmd}: invalid property '{rest[1]}'"))
    for token in rest[2:]:
        if PROPERTY_RE.match(token) or SOURCE_RE.match(token):
            continue
        severity, msg = _check_value(token)
        if severity == "error":
            issues.append((line_no, "error", f"{cmd}: {msg}"))


def validate(text):
    """Validate V1 command text.

    Returns a list of (line_no, severity, message) tuples, where severity is
    'error' or 'warning'. Lines may be separated by newlines or '||'.
    """
    raw_lines = [ln.strip() for ln in re.split(r"\n|\|\|", text)]
    issues = []
    create_open = False  # True between CREATE and the first non-LAST statement
    for idx, line in enumerate(raw_lines, start=1):
        # trailing /* ... */ comments become part of the edit summary; the
        # optional '|' before a comment would otherwise leave an empty field
        line = re.sub(r"/\*.*\*/", "", line).strip().rstrip("|")
        if not line:
            continue
        if line == "CREATE":
            create_open = True
            continue
        if line.startswith("CREATE_PROPERTY|"):
            create_open = True
            continue
        if line.startswith("-STATEMENT|"):
            if not STATEMENT_ID_RE.match(line.split("|", 1)[1]):
                issues.append((idx, "error", "invalid statement-ID removal"))
            create_open = False
            continue
        if line.startswith("MERGE|"):
            parts = line.split("|")
            if len(parts) != 3 or not ENTITY_RE.match(parts[1]) or not ENTITY_RE.match(parts[2]):
                issues.append((idx, "error", "MERGE must be MERGE|Q1|Q2"))
            create_open = False
            continue
        if line.split("|", 1)[0] in QS3_LINE_CMDS:
            _validate_qs3_line(line, idx, issues)
            create_open = False
            continue

        parts = line.split("|")
        entity = parts[0]
        if entity == "LAST":
            if not create_open:
                issues.append((idx, "warning", "LAST used without a preceding CREATE"))
        else:
            create_open = False
        _validate_statement(parts, idx, issues)

    return issues


def validate_ok(text):
    """True when the batch has no errors (warnings are allowed)."""
    return not [i for i in validate(text) if i[1] == "error"]


# ---------------------------------------------------------------------------
# Batch generation (New-Q5-style person item)
# ---------------------------------------------------------------------------

def build_person_batch(
    name,
    *,
    description="",
    languages=("en", "de", "fr", "nl"),
    add_mul_label=True,
    aliases=(),
    instance_of=("Q5",),
    gender_qid=None,
    gender_inferred_from=None,
    given_name_qids=(),
    family_name_qid=None,
    dob=None,
    dob_precision=None,
    dob_approx_range=None,
    dod=None,
    dod_precision=None,
    ref_url=None,
    ref_title=None,
    ref_retrieved=None,
):
    """Build a QS batch that creates a person item (New-Q5 pattern).

    `name` and `description` are used verbatim for the multilingual labels
    (`Lmul` + one `Lxx` per requested language) and the English description
    (`Den`) - labels are proper nouns and are generally *not* translated,
    which is exactly why New-Q5 writes the same string in every language.

    `dob`/`dod` accept a date tuple (year, month, day) or a date string; use
    `dob_approx_range=(earliest, latest)` to emit an approximate date of
    birth with P1480/P1319/P1326. `ref_url`/`ref_title`/`ref_retrieved` are
    attached as a reference (S854/S1476/S813) on the date statements.

    Returns a list of command strings.
    """
    if not name:
        raise ValueError("name is required")
    batch = ["CREATE"]
    if add_mul_label:
        batch.append(f"LAST|Lmul|{quote_string(name)}")
    for lang in languages:
        batch.append(f"LAST|L{lang}|{quote_string(name)}")
    if description:
        batch.append(f"LAST|Den|{quote_string(description)}")
    for alias in aliases:
        batch.append(f"LAST|Amul|{quote_string(alias)}")

    ref = _qs_reference(ref_url, ref_title, ref_retrieved)

    for qid in instance_of:
        batch.append(f"LAST|P31|{qid}")

    if gender_qid:
        line = f"LAST|P21|{gender_qid}"
        if gender_inferred_from:
            line += f"|S887|{gender_inferred_from}"
        batch.append(line)

    for i, qid in enumerate(given_name_qids, start=1):
        batch.append(f"LAST|P735|{qid}|P1545|{quote_string(str(i))}")
    if family_name_qid:
        batch.append(f"LAST|P734|{family_name_qid}")

    if dob:
        batch.append(f"LAST|P569|{_date_value(dob, dob_precision)}" + ref)
    elif dob_approx_range:
        earliest, latest = dob_approx_range
        batch.append(
            f"LAST|P569|+{_year_of(earliest)}-00-00T00:00:00Z/9"
            f"|P1480|Q5727902"
            f"|P1319|{_month_value(earliest)}"
            f"|P1326|{_month_value(latest)}" + ref
        )
    if dod:
        batch.append(f"LAST|P570|{_date_value(dod, dod_precision)}" + ref)
    return batch


def _date_value(date, precision):
    if isinstance(date, str):
        parts = [int(x) for x in re.split(r"[-/]", date) if x]
        if len(parts) == 1:
            return format_time(parts[0], precision=9)
        if len(parts) == 2:
            return format_time(parts[0], month=parts[1], precision=10)
        return format_time(parts[0], parts[1], parts[2], precision=11)
    if isinstance(date, (tuple, list)):
        year, *rest = date
        if not rest:
            return format_time(year, precision=9)
        if len(rest) == 1:
            return format_time(year, month=rest[0], precision=10)
        return format_time(year, rest[0], rest[1], precision=11)
    raise TypeError("date must be a (year[, month[, day]]) tuple or 'YYYY[-MM[-DD]]' string")


def _year_of(date):
    if isinstance(date, (tuple, list)):
        return date[0]
    return int(re.split(r"[-/]", str(date))[0])


def _month_value(date):
    if isinstance(date, (tuple, list)):
        year, *rest = date
    else:
        year, *rest = [int(x) for x in re.split(r"[-/]", str(date))]
    month = rest[0] if rest else None
    return format_time(year, month=month, precision=10)


def _qs_reference(url, title, retrieved):
    if not url:
        return ""
    ref = f"|S854|{quote_string(url)}"
    if title:
        ref += f"|S1476|{quote_string(title)}"
    if retrieved:
        ref += f"|S813|{_date_value(retrieved, 11)}"
    return ref


# ---------------------------------------------------------------------------
# URL encoding (#/v1= fragment)
# ---------------------------------------------------------------------------

def to_v1_url(commands, version=2):
    """Encode V1 commands into a clickable QuickStatements URL.

    QS 2.0 uses a fragment:  https://quickstatements.toolforge.org/#/v1=...
    QS 3.0 uses a query param: https://qs-dev.toolforge.org/batch/new?v1=...
    """
    fragment = "||".join(commands)
    encoded = urllib.parse.quote(fragment, safe="")
    if version == 3:
        return "https://qs-dev.toolforge.org/batch/new?v1=" + encoded
    if version == 2:
        return "https://quickstatements.toolforge.org/#/v1=" + encoded
    raise ValueError("version must be 2 or 3")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv):
    parser = argparse.ArgumentParser(
        description="Validate a QuickStatements V1 batch, build a person "
                    "batch, or produce a #/v1= URL.")
    parser.add_argument("--file", help="path to a V1 batch file to validate")
    parser.add_argument("--person", metavar="NAME",
                        help="build a New-Q5-style person-creation batch")
    parser.add_argument("--description", default="")
    parser.add_argument("--languages", default="en,de,fr,nl")
    parser.add_argument("--dob", default=None, help="YYYY[-MM[-DD]]")
    parser.add_argument("--dod", default=None, help="YYYY[-MM[-DD]]")
    parser.add_argument("--gender", default=None,
                        help="QID (e.g. Q6581097 male / Q6581072 female)")
    parser.add_argument("--ref-url", default=None)
    parser.add_argument("--url", action="store_true",
                        help="also print the clickable URL for the batch")
    parser.add_argument("--version", type=int, choices=[2, 3], default=2,
                        help="QS version for the URL (2 = quickstatements, "
                             "3 = qs-dev)")
    args = parser.parse_args(argv)

    if args.person:
        batch = build_person_batch(
            args.person, description=args.description,
            languages=tuple(l for l in args.languages.split(",") if l),
            gender_qid=args.gender, dob=args.dob, dod=args.dod,
            ref_url=args.ref_url)
        print("\n".join(batch))
        if args.url:
            print("\n" + to_v1_url(batch, version=args.version))
        return 0

    if args.file:
        with open(args.file, "r", encoding="utf-8") as fh:
            text = fh.read()
        issues = validate(text)
        if not issues:
            print("OK - no issues found")
            return 0
        for line_no, severity, msg in issues:
            print(f"{severity.upper():7s} line {line_no}: {msg}")
        return 0 if validate_ok(text) else 1

    parser.error("provide --file or --person")


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
