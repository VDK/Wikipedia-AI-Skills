#!/usr/bin/env python3
"""Fetch Flickr photos (read-only REST API) and emit a pattypan manifest.

Flickr's read-only API needs no OAuth — an API key + the REST endpoint
(https://api.flickr.com/services/rest/) is enough. This script lists photos
from a photoset or a text search, normalizes them into a manifest that the
pattypan skill's build_pattypan_spreadsheet.py can turn into an .xls:

  * `path`  = direct image URL (largest available: url_o > url_l > url_c > url_z > url_m)
  * `name`  = Commons target filename: "Sanitized Title (<photo id>).jpg"
  * `description` = {{lang|1=...}} with the photo description (or title / tags)
  * `date`, `author`, `source`, `license` per Flickr metadata
  * `categories` left empty — fill from the subject/event

Usage:
  python fetch_flickr.py --photoset <id> --user <nsid> --out files.csv
  python fetch_flickr.py --search "re:publica 26" --user <nsid> --out files.csv
  python fetch_flickr.py --search "Tokyo 2024" --license 4,5,9,10 --tags-fallback --json --out files.json

Then, per the flickr SKILL.md SOP:
  python ../pattypan/scripts/build_pattypan_spreadsheet.py \
      --manifest files.csv --template information.wikitext \
      --allow-urls --output pattypan-upload.xls
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API_BASE = "https://api.flickr.com/services/rest/"

DEFAULT_EXTRAS = (
    "description,date_upload,date_taken,last_update,license,owner_name,tags,"
    "views,media,geo,path_alias,original_format,"
    "url_o,url_l,url_c,url_z,url_m"
)

# Flickr license id -> Commons license template (free/Commons-compatible set)
LICENSE_MAP = {
    "4": "{{Cc-by-2.0}}",
    "5": "{{Cc-by-sa-2.0}}",
    "7": "{{Flickr-no known copyright restrictions}}",
    "8": "{{PD-USGov}}",
    "9": "{{Cc-zero}}",
    "10": "{{Flickr-public domain mark}}",
    "11": "{{Cc-by-4.0}}",
    "12": "{{Cc-by-sa-4.0}}",
}

FREE_LICENSES = {"4", "5", "7", "8", "9", "10", "11", "12"}

MANIFEST_HEADERS = ["path", "name", "description", "date", "author", "source", "permission", "license", "categories"]


def flickr(method: str, api_key: str, params: dict | None = None) -> dict:
    """Call the Flickr REST API and return the JSON object; raise on stat != ok."""
    query = {
        "method": method,
        "api_key": api_key,
        "format": "json",
        "nojsoncallback": "1",
        **(params or {}),
    }
    url = API_BASE + "?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(url, headers={"User-Agent": "flickr-pattypan/1.0 (Commons batch upload)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("stat") != "ok":
        raise RuntimeError(f"{method} failed: {data.get('code', '')} {data.get('message', 'unknown error')}".strip())
    return data


def strip_html(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"</p>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", '"').replace("&#039;", "'")
    return re.sub(r"\s+", " ", value).strip()


def escape_template(value: str) -> str:
    return value.replace("|", "&#124;").replace("{", "&#123;").replace("}", "&#125;")


def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "-", name).strip()


def photo_title(photo: dict) -> str:
    return str(photo.get("title") or "").strip()


def photo_description(photo: dict) -> str:
    desc = photo.get("description") or ""
    if isinstance(desc, dict):
        desc = desc.get("_content", "")
    return strip_html(str(desc))


def photo_tags(photo: dict) -> list[str]:
    raw = photo.get("tags")
    if raw is None:
        return []
    if isinstance(raw, str):
        return [t for t in re.split(r"\s+", raw) if t]
    if isinstance(raw, dict):
        tags = raw.get("tag") or []
        return [str(t.get("raw") or t.get("_content") or "") for t in tags if t]
    if isinstance(raw, list):
        return [str(t.get("raw") or t.get("_content") or "") for t in raw if t]
    return []


def best_image_url(photo: dict) -> str:
    for key in ("url_o", "url_l", "url_c", "url_z", "url_m"):
        if photo.get(key):
            return photo[key]
    return ""


def taken_date(photo: dict) -> str:
    raw = str(photo.get("datetaken") or photo.get("dateupload") or "").strip()
    try:
        ts = int(raw)
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return raw


def license_template(license_id) -> str:
    return LICENSE_MAP.get(str(license_id), "{{subst:unc}}")


def fetch_photos(args) -> list[dict]:
    rows: list[dict] = []
    page = 1
    pages = 1
    base = {"extras": args.extras, "per_page": "500"}
    if args.license:
        base["license"] = args.license

    if args.photoset:
        if not args.user:
            raise SystemExit("--photoset requires --user <nsid>")
        while page <= pages:
            json_data = flickr("flickr.photosets.getPhotos", args.api_key, {
                **base, "photoset_id": args.photoset, "user_id": args.user, "page": str(page),
            })
            container = json_data["photoset"]
            pages = int(container.get("pages") or 1)
            set_owner = container.get("owner")
            set_owner_name = container.get("ownername")
            for photo in container.get("photo", []):
                # photosets.getPhotos puts the owner on the container, not per photo
                if not photo.get("owner") and set_owner:
                    photo["owner"] = set_owner
                if not photo.get("ownername") and set_owner_name:
                    photo["ownername"] = set_owner_name
                rows.append(photo)
            page += 1
    elif args.search:
        while page <= pages:
            params = {**base, "text": args.search, "page": str(page)}
            if args.user:
                params["user_id"] = args.user
            json_data = flickr("flickr.photos.search", args.api_key, params)
            container = json_data["photos"]
            pages = int(container.get("pages") or 1)
            rows.extend(container.get("photo", []))
            page += 1
    else:
        raise SystemExit('Provide either --photoset <id> --user <nsid> or --search "<query>"')
    return rows


def build_rows(photos: list[dict], args) -> list[list[str]]:
    lang = "de" if args.lang == "de" else "en"
    rows: list[list[str]] = []
    for photo in photos:
        owner = photo.get("owner") or args.user or ""
        title = photo_title(photo)
        tags = photo_tags(photo)
        if args.tags_fallback and tags:
            desc = " ".join(tags)
        else:
            desc = photo_description(photo) or title
        base_name = sanitize_filename(title) or str(photo.get("id") or "")
        name = f"{base_name} ({photo.get('id')}).jpg"
        description = "{{%s|1=%s}}" % (lang, escape_template(desc))
        date = taken_date(photo)
        author = "[https://www.flickr.com/photos/%s/ %s]" % (owner, photo.get("ownername") or owner or "Flickr")
        source = "[https://www.flickr.com/photos/%s/%s/ %s]" % (owner, photo.get("id"), escape_template(title or f"Flickr {photo.get('id')}"))
        license_tpl = license_template(photo.get("license"))
        rows.append([best_image_url(photo), name, description, date, author, source, "", license_tpl, ""])
    return rows


def write_manifest(rows: list[list[str]], args) -> None:
    parent = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(parent, exist_ok=True)
    if args.json:
        records = [dict(zip(MANIFEST_HEADERS, row)) for row in rows]
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(records, fh, ensure_ascii=False, indent=2)
    else:
        with open(args.out, "w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(MANIFEST_HEADERS)
            writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--photoset", help="fetch all photos from this photoset id (requires --user)")
    parser.add_argument("--search", help="run flickr.photos.search with this text query")
    parser.add_argument("--user", help="Flickr NSID (e.g. 36976328@N04)")
    parser.add_argument("--license", help="comma-delimited license ids filter (e.g. 4,5,9,10)")
    parser.add_argument("--extras", default=DEFAULT_EXTRAS, help="extras list (default: photo metadata + URLs + geo + tags)")
    parser.add_argument("--lang", choices=("de", "en"), default="en", help="description language template (default en)")
    parser.add_argument("--tags-fallback", action="store_true", help="use Flickr tags as description when a photo has none")
    parser.add_argument("--json", action="store_true", help="write JSON manifest instead of CSV")
    parser.add_argument("--out", default="flickr-manifest.csv", help="output manifest path (default flickr-manifest.csv)")
    parser.add_argument("--api-key", default=os.environ.get("FLICKR_API_KEY"), help="Flickr API key (or FLICKR_API_KEY env)")
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit("No API key: pass --api-key <KEY> or set FLICKR_API_KEY")
    if args.photoset and args.search:
        raise SystemExit("Provide either --photoset or --search, not both")

    photos = fetch_photos(args)
    rows = build_rows(photos, args)
    write_manifest(rows, args)

    summary = {
        "photos": len(photos),
        "output": os.path.abspath(args.out),
        "missingImageUrl": sum(1 for r in rows if not r[0]),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
