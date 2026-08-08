#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scrape per-photo metadata from archived Flickr photo pages.

For each ID in wayback_photo_ids.txt (or --id): pick the newest archived
capture from wayback_full.json, fetch the archived page (cached in pages/),
parse the modelExport blob, and write rescue_out/metadata.json.

Resumable: IDs already in metadata.json are skipped.

Usage:
  python3 fetch-photo-metadata.py wayback_photo_ids.txt
  python3 fetch-photo-metadata.py wayback_photo_ids.txt --id 10964377675 --limit 10
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "assets"))
import inspect_model  # noqa: E402

UA = "flickr-wayback-recovery/1.0 (contact@example.org)"
NSID = "44783532@N07"
ALIAS = "stiftelsen"
CDX_FILE = "wayback_full.json"


def load_cdx():
    with open(CDX_FILE, encoding="utf-8") as f:
        return json.load(f)


def build_id_map(cdx_rows):
    m = re.compile(r"/photos/(?:%s|%s)/(\d+)" % (re.escape(NSID), re.escape(ALIAS)))
    out = {}
    for r in cdx_rows:
        mm = m.search(r["original"])
        if not mm:
            continue
        pid = int(mm.group(1))
        if r["statuscode"] != "200":
            continue
        out.setdefault(pid, []).append({"url": r["original"], "ts": r["timestamp"]})
    for pid in out:
        out[pid].sort(key=lambda c: c["ts"])
    return out


def http_get(url, timeout=120, retries=6):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (404, 403):
                break
            time.sleep(3 * (attempt + 1))
        except Exception as e:
            last = e
            time.sleep(5 * (attempt + 1))
    raise last


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ids_file", nargs="?", default="wayback_photo_ids.txt")
    ap.add_argument("--id", type=int)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--outdir", default="rescue_out")
    ap.add_argument("--pages", default="pages")
    ap.add_argument("--sleep", type=float, default=1.0)
    args = ap.parse_args()

    ids = []
    if args.id:
        ids = [args.id]
    elif args.ids_file:
        with open(args.ids_file, encoding="utf-8") as f:
            ids = [int(x) for x in f.read().split() if x.strip()]
    if args.limit:
        ids = ids[:args.limit]

    os.makedirs(args.outdir, exist_ok=True)
    os.makedirs(args.pages, exist_ok=True)

    id_map = build_id_map(load_cdx())
    results_path = os.path.join(args.outdir, "metadata.json")
    results = {}
    if os.path.exists(results_path):
        with open(results_path, encoding="utf-8") as f:
            results = json.load(f)

    for pid in ids:
        key = str(pid)
        if key in results:
            continue
        caps = id_map.get(pid)
        if not caps:
            print(f"[{pid}] no archived capture", flush=True)
            results[key] = {"id": pid, "error": "no capture"}
            continue
        meta = None
        for cap in reversed(caps):  # newest first
            page_url = f"https://web.archive.org/web/{cap['ts']}/{cap['url']}"
            page_file = os.path.join(args.pages, f"{pid}_{cap['ts']}.html")
            try:
                if os.path.exists(page_file):
                    html = open(page_file, encoding="utf-8", errors="replace").read()
                else:
                    html = http_get(page_url).decode("utf-8", errors="replace")
                    open(page_file, "w", encoding="utf-8").write(html)
                data = inspect_model.extract_model(html)
                if not data:
                    continue
                meta = inspect_model.photo_metadata(data)
                if meta:
                    meta["archive_ts"] = cap["ts"]
                    meta["source_url"] = page_url
                    meta["page_file"] = os.path.basename(page_file)
                    break
            except Exception as e:
                print(f"[{pid}] capture {cap['ts']} failed: {e}", flush=True)
        if meta:
            results[key] = meta
            print(f"[{pid}] ok: {meta.get('title', '')[:60]!r}", flush=True)
        else:
            results[key] = {"id": pid, "error": "no model"}
            print(f"[{pid}] no usable photo model", flush=True)
        time.sleep(args.sleep)

    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print(f"metadata: {len(results)} records in {results_path}")


if __name__ == "__main__":
    main()
