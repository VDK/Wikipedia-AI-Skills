"""Tests for scripts/verify-commands.py — the ground-truth command verifier.

The verifier guards against the "hallucinated command" bug class (e.g.
`toolforge tools create`, `toolforge env set` — commands that never existed).
These tests keep the verifier itself honest: it must pass on the real repo and
must flag known-bad commands.
"""

import json
import sys
import tempfile
from pathlib import Path
import importlib.util

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# verify-commands.py has a hyphen, so load it as a module via importlib.
_SPEC = importlib.util.spec_from_file_location(
    "verify_commands", REPO_ROOT / "scripts" / "verify-commands.py"
)
verify_commands = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(verify_commands)

REGISTRY = REPO_ROOT / "scripts" / "command-registry.json"


def make_skill(tmp_path: Path, content: str) -> Path:
    skill = tmp_path / "skills" / "test-skill"
    skill.mkdir(parents=True)
    f = skill / "SKILL.md"
    f.write_text(content)
    return skill


# ---------------------------------------------------------------------------
# The verifier must PASS on the real repo (no false positives).
# ---------------------------------------------------------------------------

def test_repo_is_clean():
    assert REGISTRY.exists(), "registry missing — run scripts/refresh-command-registry.py"
    violations = []
    for md in (REPO_ROOT / ".claude" / "skills").rglob("*.md"):
        violations.extend(verify_commands.scan_file(md, verify_commands.load_registry(REGISTRY)))
    assert violations == [], f"expected clean repo, got:\n" + "\n".join(map(str, violations))


# ---------------------------------------------------------------------------
# The verifier must FLAG hallucinated / non-existent commands.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "toolforge tools create my-tool",
    "toolforge tools maintainers add my-tool alih",
    "toolforge env set MY_VAR value",
    "toolforge env list",
    "toolforge env unset MY_VAR",
    "toolforge db list",
    "toolforge envvars delet API_KEY",          # typo in real subcommand
    "toolforge envvars liost",                  # typo in real subcommand
])
def test_flags_unknown_commands(tmp_path, bad):
    skill = make_skill(tmp_path, f"```bash\n{bad}\n```\n")
    violations = verify_commands.scan_file(skill / "SKILL.md",
                                           verify_commands.load_registry(REGISTRY))
    assert violations, f"expected violation for: {bad}"


# ---------------------------------------------------------------------------
# The verifier must ACCEPT real commands (no false positives).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("good", [
    "toolforge envvars create MY_VAR value",
    "toolforge envvars delete MY_VAR",
    "toolforge envvars list",
    "toolforge jobs run daily --command 'python3 script.py'",
    "toolforge jobs flush",
    "toolforge build start https://gitlab.wikimedia.org/foo/bar",
    "toolforge build quota",
    "toolforge webservice buildservice start",
    "toolforge webservice python3.11 start",
    "toolforge migrate-index old-index new-index",
    "become my-tool",
    "sql enwiki_p",
])
def test_accepts_real_commands(tmp_path, good):
    skill = make_skill(tmp_path, f"```bash\n{good}\n```\n")
    violations = verify_commands.scan_file(skill / "SKILL.md",
                                           verify_commands.load_registry(REGISTRY))
    assert violations == [], f"unexpected violation for: {good}: {violations}"


# ---------------------------------------------------------------------------
# Context handling: documented removals and error demos are NOT violations.
# ---------------------------------------------------------------------------

def test_ignores_removal_documentation(tmp_path):
    content = (
        "The `toolforge tools ...` command family was removed from the CLI.\n"
        "\n"
        "| Mistake | Symptom | Fix |\n"
        "|---|---|---|\n"
        "| `toolforge env set` | `No such command 'env'` | Use `toolforge envvars create` |\n"
        "\n"
        "```bash\n"
        "# No CLI equivalent — `toolforge tools` was removed in CLI 0.3.x.\n"
        "toolforge envvars create API_KEY value\n"
        "```\n"
    )
    skill = make_skill(tmp_path, content)
    violations = verify_commands.scan_file(skill / "SKILL.md",
                                           verify_commands.load_registry(REGISTRY))
    assert violations == [], violations


def test_ignores_error_demo_in_fenced_block(tmp_path):
    content = (
        "```console\n"
        "$ toolforge tools create test\n"
        "Error: No such command 'tools'.\n"
        "```\n"
    )
    skill = make_skill(tmp_path, content)
    violations = verify_commands.scan_file(skill / "SKILL.md",
                                           verify_commands.load_registry(REGISTRY))
    assert violations == [], violations


# ---------------------------------------------------------------------------
# CLI entry point.
# ---------------------------------------------------------------------------

def test_main_exit_code(tmp_path):
    skill = make_skill(tmp_path, "```bash\ntoolforge env set X y\n```\n")
    rc = verify_commands.main(["--skills-dir", str(skill), "--max-age-days", "0"])
    assert rc == 1


def test_registry_schema():
    reg = verify_commands.load_registry(REGISTRY)
    assert reg["schema_version"] == 1
    tf = reg["binaries"]["toolforge"]
    assert "envvars" in tf["subcommands"]
    assert set(tf["sub"]["envvars"]) == {"create", "delete", "list", "quota", "show"}
    assert "tools" not in tf["subcommands"]  # never existed — must never reappear
    assert "env" not in tf["subcommands"]
    assert "db" not in tf["subcommands"]
