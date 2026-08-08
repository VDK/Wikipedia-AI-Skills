#!/usr/bin/env python3
"""verify-freshness.py — Enforce the last_verified metadata on skill files.

Every SKILL.md declares when its content was last reviewed for accuracy
(`last_verified: YYYY-MM-DD` in the frontmatter). This check:

- fails if last_verified is missing or malformed (not an ISO date),
- fails if last_verified is in the future (impossible date),
- fails if last_verified is older than --max-age-days (default 365).

The freshness gate is what forces the re-verification cadence: when the
Toolforge CLI or Wikimedia APIs change, skills need a human re-verification,
and this check makes staleness visible in CI instead of accumulating silently.

Usage:
    python3 scripts/verify-freshness.py
    python3 scripts/verify-freshness.py --max-age-days 270
    python3 scripts/verify-freshness.py --files path/to/SKILL.md ...

Exit codes: 0 = fresh, 1 = stale/missing/malformed.
"""

import argparse
import re
import sys
from datetime import date, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_SKILLS_DIR = REPO_ROOT / ".claude" / "skills"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def read_frontmatter(path: Path) -> dict:
    """Return frontmatter as a dict (best-effort; YAML subset)."""
    fm = {}
    lines = path.read_text().splitlines()
    if not lines or lines[0].strip() != "---":
        return fm
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip("\"'")
    return fm


def check_skill(path: Path, max_age_days: int) -> list[str]:
    problems = []
    fm = read_frontmatter(path)
    raw = fm.get("last_verified", "")
    if not raw:
        return [f"missing 'last_verified' in frontmatter"]
    if not DATE_RE.match(raw):
        return [f"'last_verified' is not an ISO date: {raw!r}"]
    try:
        verified = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return [f"'last_verified' is not a valid date: {raw!r}"]

    if verified > date.today():
        problems.append(f"'last_verified' is in the future: {raw}")
    age = (date.today() - verified).days
    if age > max_age_days:
        problems.append(
            f"'last_verified' is {age} days old (>{max_age_days}): {raw} — "
            f"re-verify against live systems and bump the date"
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skills-dir", type=Path, default=DEFAULT_SKILLS_DIR)
    ap.add_argument("--files", nargs="*", type=Path,
                    help="only check these SKILL.md files (default: all)")
    ap.add_argument("--max-age-days", type=int, default=365)
    args = ap.parse_args(argv)

    if args.files:
        files = [f for f in args.files if f.name == "SKILL.md"]
    else:
        files = sorted(args.skills_dir.rglob("SKILL.md"))

    violations = []
    for f in files:
        for prob in check_skill(f, args.max_age_days):
            violations.append((f, prob))

    for f, prob in violations:
        print(f"  x {f}  {prob}")
    print(f"\n{len(files)} skill(s) checked, {len(violations)} freshness violation(s).")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
