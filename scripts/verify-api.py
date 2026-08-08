#!/usr/bin/env python3
"""verify-api.py — Check every Wikimedia Action API invocation in the skills
against the ground-truth module surface (scripts/api-surface.json).

Catches hallucinated API calls: action=querry, prop=revisons, meta=siteifno,
action=templatestyles, prop=translationinfo — module/property names that look
plausible but do not exist on the live API. The registry is generated from
live paraminfo on enwiki/wikidata/commons (scripts/refresh-api-surface.py).

Scope: URLs containing api.php (Action API). Verifies:
  - action=<name>          -> top-level module
  - prop/list/meta=<tokens> -> query submodules when action=query
  - prop=<tokens>           -> the action's own prop parameter values for
                               non-query actions (e.g. parse: wikitext, text)

Usage:
    python3 scripts/verify-api.py
    python3 scripts/verify-api.py --json

Exit codes: 0 = clean, 1 = violations found.
"""

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_SURFACE = SCRIPT_DIR / "api-surface.json"
DEFAULT_SKILLS_DIR = REPO_ROOT / ".claude" / "skills"

BACKTICK = chr(96)
API_URL_RE = re.compile(
    "https?://[^\\s\\)\\]>'\"`]*api\\.php[^\\s\\)\\]>'\"`]*"
)

TOKEN_RE = re.compile(r"[a-z][a-z0-9_-]*")


def parse_api_call(url: str) -> dict:
    """Extract action/prop/list/meta from an api.php URL query string."""
    qs = url.split("?", 1)[1] if "?" in url else ""
    params = {}
    for kv in qs.split("&"):
        if "=" in kv:
            k, v = kv.split("=", 1)
            params[k] = v
    out = {"action": params.get("action", "query")}
    for kind in ("prop", "list", "meta"):
        if kind in params:
            out[kind] = [t for t in params[kind].split("|") if TOKEN_RE.fullmatch(t)]
    return out


def scan_file(path: Path, surface: dict) -> list[str]:
    problems = []
    rel = str(path)  # full path; relative_to fails for external test dirs
    actions = set(surface["action"])
    query = surface.get("query", {})
    action_props = surface.get("action_props", {})

    for m in API_URL_RE.finditer(path.read_text()):
        call = parse_api_call(m.group(0))
        action = call["action"]

        if action != "query" and action not in actions:
            problems.append(f"{rel}: unknown action={action} -> {m.group(0)[:90]}")

        for kind in ("prop", "list", "meta"):
            tokens = call.get(kind, [])
            if not tokens:
                continue
            if action == "query":
                valid = set(query.get(kind, []))
                for t in tokens:
                    if t not in valid:
                        problems.append(
                            f"{rel}: unknown query {kind}={t} (action={action}) -> {m.group(0)[:90]}")
            elif kind == "prop":
                valid = set(action_props.get(action, []))
                if not valid:
                    problems.append(
                        f"{rel}: prop= with action={action} cannot be verified "
                        f"(no prop registry for it) -> {m.group(0)[:90]}")
                else:
                    for t in tokens:
                        if t not in valid:
                            problems.append(
                                f"{rel}: unknown {action} prop={t} -> {m.group(0)[:90]}")
            else:
                problems.append(
                    f"{rel}: {kind}= with non-query action={action} cannot be "
                    f"verified -> {m.group(0)[:90]}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--surface", type=Path, default=DEFAULT_SURFACE)
    ap.add_argument("--skills-dir", type=Path, default=DEFAULT_SKILLS_DIR)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    surface = json.loads(args.surface.read_text())
    all_problems = []
    for f in sorted(args.skills_dir.rglob("*.md")):
        all_problems.extend(scan_file(f, surface))

    if args.json:
        print(json.dumps(all_problems, indent=2))
    else:
        for p in all_problems:
            print(f"  x {p}")
        print(f"\n{len(list(args.skills_dir.rglob('*.md')))} files scanned, "
              f"{len(all_problems)} API violation(s).")
    return 1 if all_problems else 0


if __name__ == "__main__":
    sys.exit(main())
