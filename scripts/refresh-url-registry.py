#!/usr/bin/env python3
"""refresh-url-registry.py — HEAD-check every external URL in the skills and
record the status in url-registry.json (ground truth for verify-links.py).

This is the live counterpart to the structural URL checks in verify-links.py:
it catches "URLs are not fabricated or guessed" (CONTRIBUTING checklist) by
actually hitting the network. Run it when URLs change, or at the same cadence
as the command registry refresh (every few months).

Wikimedia API etiquette is enforced: a descriptive User-Agent on every request
($WIKIMEDIA_USER_AGENT when set), pacing between requests (--delay), and
exponential backoff with Retry-After handling on HTTP 429.

Usage:
    python3 scripts/refresh-url-registry.py
    python3 scripts/refresh-url-registry.py --delay 1.0 --limit 50  # test run

Writes: scripts/url-registry.json   ({url: status_code})
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
OUT = SCRIPT_DIR / "url-registry.json"

URL_RE = re.compile(r"https?://[^\s\)\]>'\"`]+")
USER_AGENT = os.environ.get(
    "WIKIMEDIA_USER_AGENT",
    "wikipedia-ai-skills-url-registry/1.0 (https://github.com/fuzheado/Wikipedia-AI-Skills)",
)


def collect_urls(skills_dir: Path) -> list[str]:
    urls = set()
    for f in skills_dir.rglob("*.md"):
        for m in URL_RE.finditer(f.read_text()):
            url = m.group(0).rstrip(".,;:!?*\\")
            # trim unbalanced trailing paren (markdown link artifacts like
            # .../Python_(programming_language))
            while url.count("(") > url.count(")") and url.endswith("("):
                url = url[:-1]
            if "{" in url or "}" in url or url in ("https://", "http://") or url.endswith("..."):
                continue
            # SPARQL CONCAT prefixes like 'https://commons.wikimedia.org/entity/M'
            # (entity IDs always follow) are code fragments, not URLs
            if re.search(r"/[MQ]$", url):
                continue
            host = urlparse(url).hostname or ""
            if not host or ("." not in host and host != "localhost"):
                continue
            urls.add(url)
    return sorted(urls)


# URLs that are legitimate documentation but can never succeed with GET/HEAD:
# POST-only endpoints (Lift Wing :predict, Action API write actions, the
# wd-vectordb query endpoint, etc.). Recorded for the registry's skip list.
POST_ONLY_RE = re.compile(
    r"""(?: :predict$ | /item/query/ | /property/query/ | /similarity-score/ |
       /rest\.php/oauth2 | /rest\.php/oauth2/ |
       api\.php\?action=(?:edit|upload|delete|move|import|login|logout|createaccount|
       watch|patrol|rollback|protect|block|emailuser|undelete|revisiondelete|
       suppression|changecontentmodel|stabilize|review) )"""
, re.I | re.X)

# Clearly-illustrative example URLs that are not real resources
EXAMPLE_URL_RE = re.compile(
    r"""(?:
      example\.com|example\.org|example\.jpg|<[A-Za-z_-]+>|\{[a-z_]+\}|
      \*\.|your-[a-z-]+|my-[a-z][a-z-]*|123456\d*|wrong-[a-z-]+|\bxxx\b|
      placeholder|\bTBD\b|library/version/file|PageName|Username|Foo\.svg|Doc\.pdf|
      He_Tingbo|/thumb/$|/800px$|/1440px$|\.\.\.|/stream/$|entity/[MQ]$|/entity/$|
      /prop/(direct/|qualifier/|statement/)?$|
      rest_v1/metrics/|rest_v1/page/.*/html$|service/lw/inference/v1/models/$|core/v1/wikipedia/en/$|
      [\\<>]|\([^)]*$|Special_MyLanguage|Special:OAuth|Book_Title|rest_v1/search/page|qlever\.(cs\.uni-freiburg\.de|dev)|/sparql$
    )"""
, re.I | re.X)


def check_url(url: str, timeout: float, delay: float) -> int:
    """HEAD (fall back to GET) a URL, returning the final status code."""
    req = Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    for attempt in range(3):
        try:
            with urlopen(req, timeout=timeout) as resp:
                return resp.status
        except HTTPError as e:
            if e.code == 429:
                retry = float(e.headers.get("Retry-After", 2 ** attempt))
                print(f"  429 {url} — backing off {retry}s", file=sys.stderr)
                time.sleep(retry)
                continue
            return e.code
        except URLError as e:
            # some servers reject HEAD; retry once with GET
            if attempt == 0 and isinstance(e.reason, Exception) and "HEAD" in str(e):
                req = Request(url, headers={"User-Agent": USER_AGENT})
                continue
            return 0  # network error / DNS / timeout — record as 0
        except Exception:
            return 0
    return 429


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skills-dir", type=Path, default=DEFAULT_SKILLS_DIR)
    ap.add_argument("--delay", type=float, default=0.5,
                    help="seconds between requests (Wikimedia etiquette)")
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--limit", type=int, default=0, help="only check first N URLs (test)")
    ap.add_argument("--resume", action="store_true",
                    help="skip URLs already recorded in the registry file")
    args = ap.parse_args(argv)

    urls = collect_urls(args.skills_dir)
    if args.limit:
        urls = urls[: args.limit]
    print(f"{len(urls)} URLs to check (delay={args.delay}s)", file=sys.stderr)

    known = {}
    if args.resume and OUT.exists():
        known = json.loads(OUT.read_text()).get("urls", {})
        # re-apply classification to previously recorded URLs so example /
        # post-only entries keep their skip markers without re-fetching
        for u in list(known):
            if EXAMPLE_URL_RE.search(u):
                known[u] = -1
            elif POST_ONLY_RE.search(u):
                known[u] = -2
        print(f"resuming with {len(known)} already recorded (reclassified)", file=sys.stderr)

    registry = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "generator": "scripts/refresh-url-registry.py",
                "user_agent": USER_AGENT,
                "urls": dict(known),
                "skip": {"post_only": "POST-only endpoints (HEAD/GET cannot verify)",
                         "example": "illustrative placeholder URLs"}}
    bad = 0
    pending = [u for u in urls if u not in known]
    for i, url in enumerate(pending, 1):
        if EXAMPLE_URL_RE.search(url):
            registry["urls"][url] = -1  # illustrative placeholder — never fetch
            print(f"  [{i}/{len(pending)}] skip example {url}", file=sys.stderr)
        elif POST_ONLY_RE.search(url):
            registry["urls"][url] = -2  # POST-only endpoint — HEAD cannot verify
            print(f"  [{i}/{len(pending)}] skip post-only {url}", file=sys.stderr)
        else:
            status = check_url(url, args.timeout, args.delay)
            registry["urls"][url] = status
            if status >= 400:
                bad += 1
                print(f"  [{i}/{len(pending)}] {status} {url}", file=sys.stderr)
            elif i % 25 == 0:
                print(f"  [{i}/{len(pending)}] ...", file=sys.stderr)
        time.sleep(args.delay)
        # incremental save: never lose progress on interruption
        OUT.write_text(json.dumps(registry, indent=1, sort_keys=True) + "\n")

    # final save (covers the no-pending case where the loop never writes)
    OUT.write_text(json.dumps(registry, indent=1, sort_keys=True) + "\n")
    print(f"\nRegistry written to {OUT}", file=sys.stderr)
    print(f"  {len(pending)} URLs checked, {bad} with status >= 400", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
