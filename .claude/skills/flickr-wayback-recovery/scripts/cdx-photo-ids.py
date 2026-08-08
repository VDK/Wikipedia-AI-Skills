#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Enumerate every archived photo ID of a deleted Flickr account via the CDX API.

Queries BOTH URL forms (NSID and username alias), dedupes by digest, and writes:
  wayback_full.json       all CDX rows (for later steps)
  wayback_photo_ids.txt   sorted distinct photo IDs

Usage:
  python3 cdx-photo-ids.py 44783532@N07 stiftelsen
  python3 cdx-photo-ids.py 44783532@N07 stiftelsen --outdir . --sleep 1
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request

UA = "flickr-wayback-recovery/1.0 (contact@example.org)"
CDX = "https://web.archive.org/cdx/search/cdx"

# Optional trailing slash; tolerate the `in/photostream|set-..|album-..|pool-..` suffix.
def make_photo_re(accounts):
    alt = "|".join(re.escape(a) for a in accounts)
    return re.compile(
        r"/photos/(?:%s)/(\d+)/?" % alt +
        r"(?:in/(?:photostream|set-[\w]+|album-[\w]+|pool-[\w]+))?/?$"
    )


def cdx_rows(account_url):
    qs = urllib.parse.urlencode({
        "url": account_url, "output": "json",
        "fl": "timestamp,original,statuscode,digest",
        "filter": "statuscode:200", "collapse": "digest",
    })
    url = f"{CDX}?{qs}"
    last = None
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as r:
                rows = json.load(r)
            if not rows:
                return []
            return [dict(zip(rows[0], row)) for row in rows[1:]]
        except Exception as e:
            last = e
            time.sleep(3 * (attempt + 1))
    print(f"  CDX query failed for {account_url}: {last}", file=sys.stderr)
    return []


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("accounts", nargs="+", help="NSID and/or username alias, e.g. 44783532@N07 stiftelsen")
    ap.add_argument("--outdir", default=".")
    ap.add_argument("--sleep", type=float, default=1.0, help="seconds between CDX calls")
    args = ap.parse_args()

    all_rows = []
    for account in args.accounts:
        for form in (f"https://www.flickr.com/photos/{account}/*",
                     f"http://www.flickr.com/photos/{account}/*"):
            rows = cdx_rows(form)
            print(f"{form}: {len(rows)} rows")
            all_rows.extend(rows)
            time.sleep(args.sleep)

    # collapse=digest already dedupes within a query; dedupe across the four too.
    seen = set()
    rows = []
    for r in all_rows:
        key = (r.get("timestamp"), r.get("original"), r.get("digest"))
        if key in seen:
            continue
        seen.add(key)
        rows.append(r)

    photo_re = make_photo_re(args.accounts)
    ids = sorted({int(m.group(1)) for r in rows
                  if (m := photo_re.search(r["original"]))})

    import os
    with open(os.path.join(args.outdir, "wayback_full.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    with open(os.path.join(args.outdir, "wayback_photo_ids.txt"), "w", encoding="utf-8") as f:
        for pid in ids:
            f.write(f"{pid}\n")

    print(f"\ntotal CDX rows: {len(rows)}")
    print(f"distinct photo IDs: {len(ids)}")


if __name__ == "__main__":
    main()
