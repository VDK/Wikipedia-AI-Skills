#!/usr/bin/env python3
"""generate-skills-network.py — Regenerate docs/skills-network.dot from the live skill set.

Scans .claude/skills/*/SKILL.md, extracts each skill's `depends_on` entries and
inline cross-skill links (../<skill>/SKILL.md), and emits a graphviz digraph at
docs/skills-network.dot. Node styling (label, color, fontsize) is preserved for
skills already present in the previous dot file; new skills get a family color
and a derived short label.

Run after adding/removing/renaming skills, then regenerate the derivatives:
    python3 scripts/generate-skills-network.py
    python3 scripts/generate-network-html.py        # docs/skills-network.html
    dot -Tpng docs/skills-network.dot -o docs/skills-network.png
    sips -Z 1280 docs/skills-network.png            # downscale for README embed
    dot -Tsvg docs/skills-network.dot -o docs/skills-network.svg

Requires graphviz (`dot`) for the png/svg renders; the html generator is a
pure-python script.
"""

import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
DOT_PATH = REPO_ROOT / "docs" / "skills-network.dot"

# Existing node styles to preserve (label, fillcolor, fontsize) — read from the
# previous dot file so regenerating doesn't churn styling for unchanged skills.
NODE_RE = re.compile(
    r'^\s*"([a-z0-9-]+)" \[label="([^"]*)", fillcolor="#([0-9a-f]{6})", style="filled,rounded", fontsize=(\d+)\]'
)

# Family colors, matching the original network's palette.
FAMILY_COLORS = [
    ("wikipedia-", "e1bee7"),   # purple — enwiki editing
    ("wikidata", "e8f5e9"),     # green — Wikidata
    ("wikimedia-api-", "e3f2fd"),  # blue — API access
    ("wikimedia-commons-", "fff3e0"),  # orange — Commons family
    ("wikimedia-commons", "fff3e0"),
    ("toolforge-", "fce4ec"),   # pink — Toolforge
    ("mediawiki-", "c8e6c9"),   # green-light — MediaWiki
    ("wikimedia-", "fce4ec"),   # pink — other Wikimedia
    ("wikivoyage", "c8e6c9"),
    ("wiktionary", "c8e6c9"),
]
DEFAULT_COLOR = "fce4ec"

# Short labels for skills new to the network (existing ones keep their label).
NEW_LABELS = {
    "flickr": "flickr",
    "flickr-wayback-recovery": "flickr-wayback",
    "pattypan": "pattypan",
    "quickstatements": "quickstatements",
    "wikimedia-codex": "wm-codex",
    "wikimedia-commons-categories": "wm-cm-categories",
    "wikimedia-url-shortener": "wm-url-shortener",
    "wikiportraits-event-series": "wp-event-series",
}

INLINE_LINK_RE = re.compile(r"\.\./([a-z0-9-]+)/SKILL\.md")
DEPENDS_ON_RE = re.compile(r"depends_on:\s*\[([^\]]*)\]")


def family_color(name: str) -> str:
    for prefix, color in FAMILY_COLORS:
        if name.startswith(prefix):
            return color
    return DEFAULT_COLOR


def read_old_styles() -> dict:
    """Return {skill: (label, fillcolor, fontsize)} from the previous dot."""
    styles = {}
    if DOT_PATH.exists():
        for m in NODE_RE.finditer(DOT_PATH.read_text()):
            name, label, color, size = m.groups()
            styles[name] = (label, color, int(size))
    return styles


def scan_skills() -> tuple[dict, set]:
    """Return ({skill: set(targets)}, all_skill_names)."""
    skills = {}
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        name = skill_dir.name
        text = skill_file.read_text()
        targets = set()
        for m in INLINE_LINK_RE.finditer(text):
            targets.add(m.group(1))
        dm = DEPENDS_ON_RE.search(text.split("---")[1] if text.startswith("---") else text)
        if dm:
            for t in re.findall(r"[a-z][a-z0-9-]*", dm.group(1)):
                targets.add(t)
        skills[name] = targets
    return skills


def main() -> int:
    skills = scan_skills()
    old = read_old_styles()
    lines = ["digraph Skills {", "  rankdir=LR;",
             '  node [shape=box, style=rounded, fontname="Helvetica", fontsize=10];',
             '  edge [color="#666666", arrowsize=0.7];', ""]
    for name in sorted(skills):
        if name in old:
            label, color, size = old[name]
        else:
            label = NEW_LABELS.get(name, name)
            color = family_color(name)
            size = 11 if len(skills[name]) >= 4 else 10
        lines.append(
            f'  "{name}" [label="{label}", fillcolor="#{color}", '
            f'style="filled,rounded", fontsize={size}];'
        )
    lines.append("")
    for src in sorted(skills):
        for dst in sorted(skills[src]):
            if dst in skills:  # only link to real skills
                lines.append(f'  "{src}" -> "{dst}";')
    lines.append("}")
    DOT_PATH.write_text("\n".join(lines) + "\n")
    print(f"skills: {len(skills)} nodes, "
          f"{sum(len(t) for t in skills.values())} link targets "
          f"-> {DOT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
