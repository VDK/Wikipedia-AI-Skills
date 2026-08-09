#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate a pattypan manifest before upload.

Checks (0 errors required):
  - filenames: illegal chars `#<>[]|{}/`, trailing dot/space, byte-length <= 240
  - no empty description / date / archive_ts
  - every path points at an existing local file (no URL paths)
  - every file is a valid image (magic bytes)
  - no row references a skipped/pruned Flickr ID

Usage:
  python3 validate-manifest.py manifest.csv [--skip skip_photos.txt]
"""
import argparse
import os
import re
import sys

ILLEGAL = re.compile(r"[#<>\[\]|{}/]")
MAGIC = [(b"\xff\xd8\xff", "jpg"), (b"\x89PNG\r\n\x1a\n", "png"),
         (b"GIF87a", "gif"), (b"GIF89a", "gif")]


def looks_like_image(path):
    with open(path, "rb") as f:
        head = f.read(16)
    for magic, _ext in MAGIC:
        if head.startswith(magic):
            return True
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("manifest")
    ap.add_argument("--skip", default="skip_photos.txt")
    args = ap.parse_args()

    import csv
    import io
    rows = list(csv.DictReader(io.open(args.manifest, encoding="utf-8")))
    skip = set()
    if os.path.exists(args.skip):
        skip = set(x.strip() for x in open(args.skip, encoding="utf-8"))

    errors, warnings = [], []
    for i, r in enumerate(rows, start=2):
        name = r.get("name", "")
        if ILLEGAL.search(name):
            errors.append(f"row {i}: illegal char in filename {name!r}")
        if name != name.strip() or name.endswith("."):
            errors.append(f"row {i}: trailing space/dot in filename {name!r}")
        if len(name.encode("utf-8")) > 240:
            errors.append(f"row {i}: filename >240 bytes: {name[:60]!r}...")
        for col in ("description", "date", "archive_ts", "photo_id"):
            if not (r.get(col) or "").strip():
                errors.append(f"row {i}: empty {col}")
        path = r.get("path", "")
        if path.startswith("http"):
            errors.append(f"row {i}: path is a URL, not a local file: {path[:60]}")
        elif not os.path.exists(path):
            errors.append(f"row {i}: file missing: {path}")
        elif not looks_like_image(path):
            errors.append(f"row {i}: not a valid image: {path}")
        if r.get("photo_id") in skip:
            errors.append(f"row {i}: photo {r['photo_id']} is in the skip list")
        if r.get("license") not in ("4", "5", "7", "8", "9", "10", "11", "12"):
            warnings.append(f"row {i}: non-free license id {r.get('license')!r}")

    print(f"rows: {len(rows)}")
    print(f"errors: {len(errors)}   warnings: {len(warnings)}")
    for e in errors[:50]:
        print("  E", e)
    for w in warnings[:20]:
        print("  W", w)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
