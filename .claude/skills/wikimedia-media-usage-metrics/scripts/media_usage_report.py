#!/usr/bin/env python3
"""Report media usage for a Wikimedia Commons file (works for ANY file, no allow-list).

Pipeline:
  1. Resolve title -> upload path   (imageinfo iiprop=url)
  2. Where used                     (prop=globalusage, paginated)
  3. Transfers                      (mediarequests/per-file)
  4. Reach                          (pageviews/per-article over using pages)
  5. File-page interest             (pageviews/per-article on File: title)

Usage:
  python3 media_usage_report.py "File:Crab Nebula.jpg" --days 30 --max-pages 50

Requires: requests (pip install requests)
"""
import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

try:
    import requests
except ImportError:
    sys.exit("Missing dependency: pip install requests")

UA = {"User-Agent": "MediaUsageReport/1.0 (https://meta.wikimedia.org; your@email.example) MediaUsageMetrics"}

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
AQS = "https://wikimedia.org/api/rest_v1/metrics"


def _get(url, params=None):
    r = requests.get(url, params=params, headers=UA, timeout=30)
    r.raise_for_status()
    return r.json()


def _get_or_none(url):
    """GET a JSON endpoint; return None on HTTP 404 (no data), raise otherwise."""
    r = requests.get(url, headers=UA, timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def resolve_path(file_title):
    """Return the upload.wikimedia.org path (WITH leading slash) for a File: title."""
    data = _get(COMMONS_API, {
        "action": "query", "prop": "imageinfo", "iiprop": "url",
        "titles": file_title, "format": "json",
    })
    page = next(iter(data["query"]["pages"].values()))
    if "imageinfo" not in page or "missing" in page:
        raise SystemExit(f"File not found: {file_title}")
    url = page["imageinfo"][0]["url"]  # https://upload.wikimedia.org/wikipedia/commons/...
    url = url.split("?", 1)[0]  # drop any ?utm_source=... tracking params
    return "/" + url.split("upload.wikimedia.org", 1)[1].lstrip("/")


def global_usage(file_title, max_usage=5000):
    """Return (list_of_(wiki,title), truncated_bool) for all pages using the file."""
    params = {
        "action": "query", "prop": "globalusage", "titles": file_title,
        "format": "json", "gulimit": "500",
    }
    out = []
    truncated = False
    while True:
        data = _get(COMMONS_API, params)
        page = next(iter(data["query"]["pages"].values()))
        for gu in page.get("globalusage", []):
            if len(out) >= max_usage:
                truncated = True
                return out, truncated
            out.append((gu["wiki"], gu["title"]))
        if "continue" in data:
            params["gucontinue"] = data["continue"]["gucontinue"]
            params["continue"] = data["continue"]["continue"]
        else:
            return out, truncated


def mediarequests(path, start, end):
    """Total transfer count for a file. path must include leading slash.
    Returns (0, 0) if there is no data for the window (HTTP 404)."""
    encoded = quote(path, safe="")  # encode slashes too (verified required)
    url = f"{AQS}/mediarequests/per-file/all-referers/all-agents/{encoded}/daily/{start}/{end}"
    data = _get_or_none(url)
    if data is None:
        return 0, 0
    items = data.get("items", [])
    return sum(i["requests"] for i in items), len(items)


def pageviews(project, title, start, end):
    """Total page views for one page in a window.
    Returns None if the page has no pageview data (HTTP 404) — common for
    low-traffic pages such as user pages and talk pages."""
    title_q = quote(title.replace(" ", "_"), safe="")
    url = f"{AQS}/pageviews/per-article/{project}/all-access/user/{title_q}/daily/{start}/{end}"
    data = _get_or_none(url)
    if data is None:
        return None
    return sum(i["views"] for i in data.get("items", []))


def main():
    ap = argparse.ArgumentParser(description="Report media usage for a Commons file.")
    ap.add_argument("file", help='File title, e.g. "File:Crab Nebula.jpg"')
    ap.add_argument("--days", type=int, default=30, help="window in days (default 30)")
    ap.add_argument("--max-pages", type=int, default=50, help="cap on using pages for reach sum (default 50)")
    ap.add_argument("--max-usage", type=int, default=5000, help="cap on GlobalUsage enumeration (default 5000)")
    args = ap.parse_args()

    # ~48h data lag for both mediarequests and pageviews
    end = (datetime.now(timezone.utc) - timedelta(days=2)).date()
    start = end - timedelta(days=args.days - 1)
    s, e = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

    print(f"File:   {args.file}")
    print(f"Window: {start} .. {end} ({args.days} days)")
    print("-" * 60)

    path = resolve_path(args.file)
    print(f"Storage path: {path}")

    usage, usage_truncated = global_usage(args.file, max_usage=args.max_usage)
    wikis = {w for w, _ in usage}
    print(f"\n[1] USAGE (GlobalUsage)")
    print(f"    distinct wikis:      {len(wikis)}")
    print(f"    total using pages:   {len(usage)}" + ("  (TRUNCATED at cap)" if usage_truncated else ""))

    total_req, days = mediarequests(path, s, e)
    print(f"\n[2] TRANSFERS (mediarequests)")
    print(f"    requests served:     {total_req:,}  ({days} day(s) of data)")

    shown = usage[: args.max_pages]
    reach = 0
    no_data = 0
    for i, (wiki, title) in enumerate(shown, 1):
        project = wiki.removesuffix(".org")  # 'en.wikipedia.org' -> 'en.wikipedia'
        v = pageviews(project, title, s, e)
        if v is None:
            no_data += 1
        else:
            reach += v
        if i % 20 == 0:
            time.sleep(0.1)
    truncated = len(usage) > args.max_pages
    print(f"\n[3] REACH (sum of pageviews of pages using the file)")
    print(f"    reach (page views):  {reach:,}")
    if no_data:
        print(f"    (skipped {no_data} using-page(s) with no pageview data — treated as 0)")
    if truncated:
        print(f"    (PARTIAL — capped at {args.max_pages} of {len(usage)} using pages)")

    fp = pageviews("commons.wikimedia", args.file, s, e) or 0
    print(f"\n[4] FILE-PAGE VIEWS (interest in the asset itself)")
    print(f"    file page views:     {fp:,}")

    print("\nNOTE: transfers count thumbnail fetches on articles;")
    print("      file-page views count people opening the file's own page.")
    print("      REACH is a lower-bound SAMPLE (first N using pages, not the")
    print("      most-viewed). Exact reach needs pageviews for ALL using pages")
    print("      (slow), or Commons Impact Metrics if the file is allow-listed.")


if __name__ == "__main__":
    main()
