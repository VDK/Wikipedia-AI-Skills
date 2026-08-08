#!/usr/bin/env python3
"""verify-snippets.py — Syntax-check code blocks in the skills.

Catches the "syntactically impossible" hallucination class: code examples that
look right but would not parse. Checks:
  - python / python3 blocks -> ast.parse
  - bash / sh / shell / console blocks -> bash -n
  - json blocks -> json.loads
  - javascript / js blocks -> node --check (when node is available)

Fragments are skipped conservatively: blocks containing placeholder markers
(${...}, <...>, "your-", "my-", "...", prompt prefixes like $ or >>>, or
obvious mid-file snippets) are treated as illustrative, not complete programs.
Blocks that look complete and fail to parse are violations.

Usage:
    python3 scripts/verify-snippets.py
    python3 scripts/verify-snippets.py --json

Exit codes: 0 = clean, 1 = violations found.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_SKILLS_DIR = REPO_ROOT / ".claude" / "skills"

PLACEHOLDER_RE = re.compile(
    r"(your-|my-|<[a-z_][a-z_-]*>|example|placeholder|TODO|TBD|xxx|foo|bar)|"
    r"\$\{[^}]+\}|\.\.\."
)
PROMPT_LINE_RE = re.compile(r"^\s*[$#>] ")
# pseudo-code indicators: arrows, annotation comments inside code
PSEUDOCODE_RE = re.compile(r"[←→⇒⇐↔]")
LANG_ALIASES = {
    "python": "python", "python3": "python", "py": "python",
    "bash": "bash", "sh": "bash", "shell": "bash", "console": "bash", "zsh": "bash",
    "json": "json", "javascript": "js", "js": "js",
}


def is_complete(block: str, lang: str) -> bool:
    """Heuristic: is this a complete program rather than an illustrative fragment?

    Skips: placeholder markers, pseudo-code arrows, annotation comments (JSON
    blocks with # comments), deliberately-broken anti-pattern examples, and
    snippets that clearly start mid-expression.
    """
    block = block.strip()
    lines = [l for l in block.splitlines() if l.strip() and not PROMPT_LINE_RE.match(l)]
    if not lines:
        return False
    if PLACEHOLDER_RE.search(block):
        return False
    if PSEUDOCODE_RE.search(block):
        return False
    # anti-pattern demonstrations (BAD/❌/✗/"don't do this" blocks)
    if re.search(r"(?i)\b(bad|wrong|never do|do not use|don'?t do this|❌|✗|\\u274c)", block[:400]):
        return False
    if lang == "json" and (
        any(l.lstrip().startswith(("#", "//")) for l in lines)
        or re.search(r" # | // ", block)
    ):
        return False  # annotated JSON (comments in JSON are invalid but illustrative)
    if block.lstrip().startswith(("...", "..", "return ", "await ", "}")):
        return False
    if lang == "python":
        # must look like a full script: starts with import/def/class/#!/simple stmt
        first = lines[0].lstrip()
        if not re.match(r"^(import |from |def |class |@|if __name__|#!|async |[a-zA-Z_][\w]*\s*[=(])", first):
            return False
        # must end with a statement, not a dangling expression continuation
        if re.search(r"[=,+-/\\(]$", lines[-1].rstrip()):
            return False
    if lang == "bash":
        if not re.match(r"^(#!|set |export |[a-zA-Z_]+=|[a-z]+ |cd |mkdir |touch |echo )", lines[0].lstrip()):
            return False
    if lang == "json":
        if not block.lstrip().startswith(("{", "[")):
            return False
        # truncated examples end mid-object
        if block.rstrip().endswith(("{", "[", ",", ":")):
            return False
    return True


def check_python(block: str) -> str | None:
    import ast
    try:
        ast.parse(block)
        return None
    except SyntaxError as e:
        return f"python syntax error: line {e.lineno}: {e.msg}"


def check_json(block: str) -> str | None:
    try:
        json.loads(block)
        return None
    except json.JSONDecodeError as e:
        return f"json error: line {e.lineno}: {e.msg}"


def check_bash(block: str) -> str | None:
    bash = shutil.which("bash")
    if not bash:
        return None
    r = subprocess.run([bash, "-n"], input=block, capture_output=True, text=True)
    if r.returncode != 0:
        first_err = (r.stderr or r.stdout).strip().splitlines()
        return f"bash syntax error: {first_err[0] if first_err else 'unknown'}"
    return None


def check_js(block: str) -> str | None:
    import tempfile
    node = shutil.which("node")
    if not node:
        return None
    # node --check on stdin treats input as CommonJS; write to a .mjs temp
    # file so ESM syntax (import, top-level await) parses correctly
    suffix = ".mjs" if ("import " in block or "export " in block or "await " in block) else ".js"
    with tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False) as f:
        f.write(block)
        tmp = f.name
    try:
        r = subprocess.run([node, "--check", tmp], capture_output=True, text=True)
    finally:
        Path(tmp).unlink(missing_ok=True)
    if r.returncode != 0:
        first_err = (r.stderr or "").strip().splitlines()
        return f"js syntax error: {first_err[0] if first_err else 'unknown'}"
    return None


CHECKERS = {"python": check_python, "bash": check_bash, "json": check_json, "js": check_js}


def scan_file(path: Path) -> list[dict]:
    problems = []
    lines = path.read_text().splitlines()
    i = 0
    n = len(lines)
    while i < n:
        if lines[i].strip().startswith("```"):
            tag = lines[i].strip()[3:].strip()
            lang = tag.split()[0].lower() if tag else ""
            j = i + 1
            buf = []
            while j < n and not lines[j].strip().startswith("```"):
                buf.append(lines[j])
                j += 1
            block = "\n".join(buf)
            # code blocks nested under list items inherit markdown indentation —
            # dedent before syntax-checking
            import textwrap
            block = textwrap.dedent(block)
            kind = LANG_ALIASES.get(lang)
            if kind and is_complete(block, kind):
                err = CHECKERS[kind](block)
                if err:
                    problems.append({"file": str(path), "line": i + 1,
                                     "lang": lang, "error": err})
            i = j + 1
        else:
            i += 1
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skills-dir", type=Path, default=DEFAULT_SKILLS_DIR)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    all_problems = []
    for f in sorted(args.skills_dir.rglob("*.md")):
        all_problems.extend(scan_file(f))

    if args.json:
        print(json.dumps(all_problems, indent=2))
    else:
        for p in all_problems:
            print(f"  x {p['file']}:{p['line']}  [{p['lang']}] {p['error']}")
        print(f"\n{len(list(args.skills_dir.rglob('*.md')))} files scanned, "
              f"{len(all_problems)} snippet violation(s).")
    return 1 if all_problems else 0


if __name__ == "__main__":
    sys.exit(main())
