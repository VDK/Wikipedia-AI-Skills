#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Find which Flickr photo IDs are already on Wikimedia Commons.

Checks the Commons file title (``Name (12345678901).jpg``), the file wikitext
(``|Source = [https://www.flickr.com/photos/<nsid>/<id>/ ...]``) and Structured
Data (P973 / P7482 URL claims). Matches by Flickr ID, never by filename.

Input : wayback_photo_ids.txt (one ID per line) -- or pass --ids on the CLI.
Output: commons_flickr_ids.txt (IDs already on Commons) and a console summary.

Usage:
  python3 check-commons.py wayback_photo_ids.txt
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request

API = "https://commons.wikimedia.org/w/api.php"
UA = "flickr-wayback-recovery/1.0 (contact@example.org)"

FLICKR_URL_RE = re.compile(r"flickr\.com/(?:photos|photo|people)/([^/\s\"'<>]*?)/(\d{5,})", re.I)
TITLE_ID_RE = re.compile(r"\((\d{5,})\)\.(\w+)$")


def api(params):
    params = dict(params)
    params["format"] = "json"
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(API, data=data, headers={"User-Agent": UA})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except Exception as e:
            if attempt == 4:
                raise
            time.sleep(2 * (attempt + 1))


def get_wikitext(titles):
    out = {}
    for i in range(0, len(titles), 50):
        chunk = titles[i:i + 50]
        data = api({
            "action": "query", "prop": "revisions", "rvprop": "content",
            "rvslots": "main", "titles": "|".join(chunk),
        })
        for page in data.get("query", {}).get("pages", {}).values():
            t = page.get("title")
            if not t:
                continue
            revs = page.get("revisions")
            out[t] = revs[0]["slots"]["main"]["*"] if revs else None
        time.sleep(0.5)
    return out


def get_sdc(titles):
    out = {}
    for i in range(0, len(titles), 50):
        chunk = titles[i:i + 50]
        data = api({
            "action": "wbgetentities", "sites": "commonswiki",
            "titles": "|".join(chunk), "props": "claims|labels|descriptions",
        })
        for ent in data.get("entities", {}).values():
            t = ent.get("title")
            if not t:
                continue
            claims = []
            for pid, statements in (ent.get("claims") or {}).items():
                for st in statements:
                    ms = st.get("mainsnak", {})
                    dv = ms.get("datavalue")
                    claims.append({
                        "pid": pid,
                        "value": dv.get("value") if dv else None,
                    })
            out[t] = claims
        time.sleep(0.5)
    return out


def extract_flickr_ids(wt, sdc, title):
    found = set()
    for m in FLICKR_URL_RE.finditer(wt or ""):
        found.add((m.group(1), m.group(2)))
    for c in sdc:
        v = c["value"]
        if isinstance(v, dict) and v.get("url"):
            for m in FLICKR_URL_RE.finditer(v["url"]):
                found.add((m.group(1), m.group(2)))
        elif isinstance(v, str) and "flickr" in v.lower():
            for m in FLICKR_URL_RE.finditer(v):
                found.add((m.group(1), m.group(2)))
    mt = TITLE_ID_RE.search(title)
    if mt:
        found.add(("title", mt.group(1)))
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ids_file", nargs="?", default="wayback_photo_ids.txt")
    ap.add_argument("--out", default="commons_flickr_ids.txt")
    args = ap.parse_args()

    with open(args.ids_file, encoding="utf-8") as f:
        ids = sorted({x.strip() for x in f if x.strip()})

    # 1. insource search for each ID (a cheap first filter).
    candidates = set()
    for pid in ids:
        data = api({"action": "query", "list": "search",
                    "srsearch": f'insource:"{pid}"', "srnamespace": "6",
                    "srlimit": 50})
        for hit in data.get("query", {}).get("search", []):
            candidates.add(hit["title"])
        time.sleep(0.2)
    print(f"{len(candidates)} candidate Commons files found by insource search")

    # 2. wikitext + SDC scan of the candidates.
    wt = get_wikitext(sorted(candidates)) if candidates else {}
    sdc = get_sdc(sorted(candidates)) if candidates else {}
    found = set()
    for title in sorted(candidates):
        for _who, pid in extract_flickr_ids(wt.get(title), sdc.get(title, []), title):
            if pid in ids:
                found.add(pid)

    with open(args.out, "w", encoding="utf-8") as f:
        for pid in sorted(found):
            f.write(f"{pid}\n")
    print(f"{len(found)} of {len(ids)} IDs already on Commons -> {args.out}")
    print(f"{len(ids) - len(found)} still to upload")


if __name__ == "__main__":
    main()
