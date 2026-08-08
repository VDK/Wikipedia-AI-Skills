#!/usr/bin/env python3
"""refresh-command-registry.py — Capture the live Toolforge CLI surface into the
command ground-truth registry used by scripts/verify-commands.py.

This is the "manual testing" step, reduced to one command. Run it whenever the
Toolforge CLI might have changed (new toolforge-* binaries, subcommand renames)
or at least every few months. It SSHs to the bastion and records `--help`
output for the `toolforge` dispatcher and every sub-CLI.

Usage:
    python3 scripts/refresh-command-registry.py
    TOOLFORGE_USER=alih python3 scripts/refresh-command-registry.py
    TOOLFORGE_BASTION=alih@login.toolforge.org python3 scripts/refresh-command-registry.py

Writes: scripts/command-registry.json
Output is deterministic (sorted) so diffs are reviewable.
"""

import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
OUT = SCRIPT_DIR / "command-registry.json"

bastion = os.environ.get("TOOLFORGE_BASTION") or (
    f"{os.environ.get('TOOLFORGE_USER') or os.environ.get('USER', '')}@login.toolforge.org"
)

# Binaries that exist on the bastion but take positional args (no subcommands).
# Included for existence verification only.
STANDALONE_BINARIES = ("webservice", "sql", "become")


def ssh(cmd: str) -> str:
    """Run a command on the bastion; return stdout+stderr."""
    r = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=15", "-o", "BatchMode=yes", bastion, cmd],
        capture_output=True, text=True, timeout=60,
    )
    return r.stdout + r.stderr


def parse_commands(help_text: str) -> list[str]:
    """Extract subcommand tokens from CLI help.

    Handles both click-style ('Commands:' section) and argparse-style
    (usage line with {sub1,sub2,...}) help output.
    """
    tokens = []

    # argparse style: Usage: toolforge jobs [-h] {images,run,...}...
    for line in help_text.splitlines():
        m = re.search(r"\{([a-z][a-z-,]*)\}\s*\.\.\.", line)
        if m:
            tokens.extend(t for t in m.group(1).split(",") if re.fullmatch(r"[a-z][a-z-]*", t))

    # click style: a 'Commands:' section with indented entries
    in_cmds = False
    for line in help_text.splitlines():
        if line.startswith("Commands:"):
            in_cmds = True
            continue
        if in_cmds:
            if line.startswith("  ") and line.strip():
                tok = line.strip().split()[0]
                if re.fullmatch(r"[a-z][a-z-]*", tok):
                    tokens.append(tok)
            elif line and not line.startswith("  "):
                break
    return sorted(set(tokens))


def get_version(binary: str) -> str:
    out = ssh(f"{binary} --version 2>&1")
    return out.strip().splitlines()[0][:80] if out.strip() else ""


def main() -> int:
    print(f"Capturing Toolforge CLI surface from {bastion} ...", file=sys.stderr)

    tf_version = get_version("toolforge")
    tf_help = ssh("toolforge --help")
    tf_commands = parse_commands(tf_help)
    if not tf_commands:
        print(f"ERROR: could not capture 'toolforge --help' from {bastion}. "
              f"Is SSH access configured?", file=sys.stderr)
        return 1

    sub = {}
    for sub_name in tf_commands:
        sub[sub_name] = parse_commands(ssh(f"toolforge {sub_name} --help 2>&1"))

    registry = {
        "schema_version": 1,
        "generator": "scripts/refresh-command-registry.py",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": f"ssh {bastion}",
        "note": ("Ground-truth command surface. Do not edit by hand; regenerate "
                 "with scripts/refresh-command-registry.py."),
        "binaries": {
            "toolforge": {
                "version": tf_version,
                "subcommands": tf_commands,
                "sub": sub,
            },
        },
    }
    for name in STANDALONE_BINARIES:
        registry["binaries"][name] = {"version": get_version(name), "subcommands": []}

    OUT.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n")

    print(f"Registry written to {OUT}", file=sys.stderr)
    print(f"  toolforge: {tf_version}", file=sys.stderr)
    for sub_name in tf_commands:
        kids = ", ".join(sub[sub_name]) or "(positional args only)"
        print(f"    {sub_name}: {kids}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
