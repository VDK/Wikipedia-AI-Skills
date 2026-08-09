#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the 13-column pattypan manifest from the rescue state files.

Inputs:
  rescue_out/metadata.json   per-photo metadata from fetch-photo-metadata.py
  images/ + images.json      downloaded images from download-images.py
  wayback_not_on_commons.txt IDs in upload scope (default: wayback_photo_ids.txt
                            minus commons_flickr_ids.txt; precompute with
                            check-commons.py)
  skip_photos.txt            IDs the user pruned (irrelevant / derivative work)
                            -- excluded even if a file or archived URL exists

Output: manifest.csv (one row per photo to upload).

The manifest columns map 1:1 onto the pattypan template variables:
  path,name,description,date,source,archive_ts,photo_id,author,photographer,
  categories,license,title,other_fields

Usage:
  python3 build-manifest.py
  python3 build-manifest.py --scope wayback_not_on_commons.txt --out manifest.csv
"""
import argparse
import json
import os
import re
import unicodedata

# ---------------------------------------------------------------------------
# CONFIG -- adapt to the account being recovered.
# ---------------------------------------------------------------------------
ACCOUNT_NAME = "Swedish Internet Foundation"   # display name for credit/filenames
NSID = "44783532@N07"
# Flickr people page is usually 404 too -> credit the plain account name, not a
# dead flickr.com/people/<nsid>/ link.
AUTHOR = "Stiftelsen"
ACCOUNT_CAT = "Photographs by the Swedish Internet Foundation"
COMMONS_YEAR_CATS = {2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2020}

# Title abbreviation -> (event name, year). A title matching any of these keys
# (as a prefix) gets that event + year in its filename and categories.
EVENT_ALIASES = {
    "24HBC": ("24 Hour Business Camp", "2011"),
    "IDD12": ("Internetdagarna", "2012"),
    "IDD13": ("Internetdagarna", "2013"),
    "IDD14": ("Internetdagarna", "2014"),
    "IDD16": ("Internetdagarna", "2016"),
    "SIF13": ("Swedish Internet Foundation", "2013"),
    "SIF14": ("Swedish Internet Foundation", "2014"),
    "SIF15": ("Swedish Internet Foundation", "2015"),
    "SIF17": ("Swedish Internet Foundation", "2017"),
}

# Tag-like descriptions that are not real descriptions (moved to the tags).
TAGLIKE_DESC = {"arthackday 2013, sponsor .se"}
TAGLIKE_EXTRA_TAG = "SE sponsor"

# Speakers/photographed people -> person category. Target the PEOPLE IN THE
# PHOTO (speakers), not the photographer. Red/nonexistent categories are fine.
PERSON_CATS = {
    "anna-karin hatt": "Anna-Karin Hatt",
    "bruce schneier": "Bruce Schneier",
    "eva hamilton": "Eva Hamilton",
    "edward snowden": "Edward Snowden",
    "juliana rotich": "Juliana Rotich",
    "mikko hyppönen": "Mikko Hyppönen",
    "christian heilmann": "Christian Heilmann",
    "erica baker": "Erica Baker",
    "yochai benkler": "Yochai Benkler",
    "carl bildt": "Carl Bildt",
    "nnenna nwakanma": "Nnenna Nwakanma",
    "daniela l. rus": "Daniela L. Rus",
    "lynn st amour": "Lynn St Amour",
    "matt wood": "Matt Wood",
    "joakim jardenberg": "Joakim Jardenberg",
}

# Photographers detected in the description credit -> photographer category.
PHOTOG_CATS = {
    "tobias björkgren": "Photographs by Tobias Björkgren",
    "sara arnald": "Photographs by Sara Arnald",
    "kristina alexanderson": "Photographs by Kristina Alexanderson",
    "rickard dahlstrand": "Photographs by Rickard Dahlstrand",
}

ARCHIVE_BASE = "https://web.archive.org/web"
IMAGE_DIR = "images"

CAMERA_RE = re.compile(
    r"^(?:IMG[_ ]?\d+|DSC[_ ]?\d+|_?[A-Z]{2}\d{3,}|[A-Z0-9]{2,}_?\.?\d+|"
    r"\d{6,8}[-_]\w+|ind\d\d?_?\._?SE_?|IDD\d\d?[-_]?\w*|24HBC\w*\s*\d+|"
    r"[\w-]*\.(?:jpg|jpeg|png|gif))$", re.I)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def url_decode(s):
    """Flickr percent-encodes metadata with latin-1 (ISO-8859-1) bytes."""
    if not s:
        return ""
    import urllib.parse
    try:
        return urllib.parse.unquote_to_bytes(s).decode("latin-1")
    except Exception:
        return s


def norm(s):
    return unicodedata.normalize("NFKC", s).strip()


def strip_credit(text):
    """Return (photographer, cleaned_text) from an embedded credit line."""
    text = norm(text or "")
    m = re.search(r"(?im)(?:^|\n)\s*(?:Fotograf|Foto|Photo|Kredit|CC-BY)[:\-–\s]*(.+)", text)
    photographer = ""
    if m:
        photographer = m.group(1).strip(" \t:;.,")
        text = text[:m.start()] + text[m.end():]
    # "Photo: Name" inline
    m2 = re.search(r"(?i)\bPhoto[:\-]\s*([A-ZÀ-ÖØ-Þ][\w' .-]+)", text)
    if m2 and not photographer:
        photographer = m2.group(1).strip()
    return photographer, text.strip()


def normalize_title(title):
    """Return a clean title, or None if the title is camera-garbage."""
    t = norm(title)
    for prefix, (event, year) in EVENT_ALIASES.items():
        if re.match(re.escape(prefix) + r"[-_ ]?", t, re.I):
            rest = re.sub(re.escape(prefix) + r"[-_ ]?", "", t, flags=re.I).strip(" -_")
            return f"{event} {year} - {rest}" if rest else f"{event} {year}"
    if CAMERA_RE.match(t):
        return None
    # drop a redundant trailing event name ("Webbstjärnan" alone is the event)
    return t


def detect_event(cats):
    for c in cats:
        for ev, year in EVENT_ALIASES.values():
            if c == ev:
                return ev
        m = re.match(r"^(.+?) (\d{4})$", c)
        if m:
            return m.group(1)
    return ""


def derive_categories(title_norm, desc, person_photographer, rec):
    cats = []
    tl = (title_norm or "").lower() + " " + (desc or "").lower()
    event = None
    for key, (ev, year) in EVENT_ALIASES.items():
        if key.lower() in tl:
            event = ev
            break
    if event:
        cats.append(event)
        if int(year) in COMMONS_YEAR_CATS:
            cats.append(f"{event} {year}")
    # person categories from the photographed people (in the description)
    for name, cat in PERSON_CATS.items():
        if name in tl:
            if cat not in cats:
                cats.append(cat)
    if rec.get("tags"):
        tl_tags = " ".join(rec["tags"]).lower()
        for name, cat in PERSON_CATS.items():
            if name in tl_tags and cat not in cats:
                cats.append(cat)
    if person_photographer:
        pc = PHOTOG_CATS.get(person_photographer.lower())
        if pc and pc not in cats:
            cats.append(pc)
    return cats, event


def build_description(desc_cleaned, event):
    """Language-tagged description + event placeholder, one language block each."""
    out = []
    if desc_cleaned:
        lang = "sv" if re.search(r"[åäöÅÄÖ]", desc_cleaned) else "en"
        out.append(f"{{{{{lang}|1={desc_cleaned}}}}}")
    if event:
        # Placeholder in the OTHER language so we never emit two blocks in one.
        ph_lang = "sv" if not out or out[0].startswith("{{en") else "en"
        out.append(f"{{{{{ph_lang}|1={event}. Årlig svensk konferens.}}}}"
                   if ph_lang == "sv"
                   else f"{{{{{ph_lang}|1={event}. Annual conference.}}}}")
    return "\n".join(out)


def clean_tags(tags):
    return [t for t in (url_decode(t) for t in (tags or [])) if t]


def esc(s):
    return s.replace("|", "{{!}}").replace("{", "{{").replace("}", "}}")


def sanitize_name(name, pid, ext):
    name = re.sub(r"[#<>\[\]|{}/]", "", name).strip(" .")
    return f"{name} ({pid}).{ext}"


def build_name(title_norm, event, year, is_camera):
    if is_camera:
        return title_norm  # already "Account Year (NNN)"
    if event and event not in title_norm:
        return f"{title_norm} - {event}"
    return title_norm


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--meta", default="rescue_out/metadata.json")
    ap.add_argument("--scope", default="wayback_not_on_commons.txt")
    ap.add_argument("--commons", default="commons_flickr_ids.txt")
    ap.add_argument("--skip", default="skip_photos.txt")
    ap.add_argument("--state", default="images.json")
    ap.add_argument("--out", default="manifest.csv")
    args = ap.parse_args()

    meta = json.load(open(args.meta, encoding="utf-8"))
    images = {}
    if os.path.exists(args.state):
        images = json.load(open(args.state, encoding="utf-8"))
    to_scrape = set(int(x) for x in open(args.scope) if x.strip()) if os.path.exists(args.scope) else set()
    commons = set(int(x) for x in open(args.commons) if x.strip()) if os.path.exists(args.commons) else set()
    skip_photos = set(int(x) for x in open(args.skip) if x.strip()) if os.path.exists(args.skip) else set()

    rows = []
    skipped = {"no_image": 0, "nc": 0, "pruned": 0, "no_meta": 0}
    cam_seqs = {}
    for pid_s in sorted(meta, key=lambda s: int(s)):
        pid = int(pid_s)
        rec = meta[pid_s]
        if to_scrape and pid not in to_scrape:
            continue
        if rec.get("error"):
            continue
        if pid in commons:
            continue
        if rec.get("license") == 2:
            skipped["nc"] += 1
            continue
        if pid in skip_photos:
            skipped["pruned"] += 1
            continue

        # image source: local file first, else archived URL.
        local = None
        info = images.get(pid_s) or {}
        ext = info.get("ext")
        cand = os.path.join(IMAGE_DIR, f"{pid}.{ext}") if ext else None
        if cand and os.path.exists(cand):
            local = cand
        if not local:
            for f in os.listdir(IMAGE_DIR):
                if f.startswith(f"{pid}."):
                    local = os.path.join(IMAGE_DIR, f)
                    break
        img_url = None
        if not local and info.get("url"):
            img_url = info["url"]
        if not local and not img_url:
            skipped["no_image"] += 1
            continue
        ext = (local or img_url).rsplit(".", 1)[-1]

        title_raw = rec.get("title") or ""
        desc_raw = rec.get("description") or ""
        date = (rec.get("dateTaken") or rec.get("datePosted") or "")[:10]
        license_id = str(rec.get("license")) if rec.get("license") is not None else "4"

        photographer, desc_cleaned = strip_credit(f"{title_raw}\n{desc_raw}")
        title_norm = normalize_title(title_raw)
        is_camera = title_norm is None
        if is_camera:
            title_norm = ""
        tags = clean_tags(rec.get("tags"))
        desc_for_cats = desc_cleaned
        if desc_cleaned and desc_cleaned.strip().lower() in TAGLIKE_DESC:
            desc_cleaned = ""
            if TAGLIKE_EXTRA_TAG not in tags:
                tags.append(TAGLIKE_EXTRA_TAG)
        other_fields = ("{{Information field|name=Flickr tags|value="
                        + ", ".join(esc(t) for t in tags) + "}}") if tags else ""

        cats, event = derive_categories(title_norm, desc_for_cats, photographer, rec)
        foundation_fallback = not cats
        if foundation_fallback:
            cats.append("Swedish Internet Foundation")
        if is_camera:
            yr = date[:4]
            seq = cam_seqs.get(yr, 0) + 1
            cam_seqs[yr] = seq
            base = f"{ACCOUNT_NAME} {yr}" if yr else ACCOUNT_NAME
            title_norm = f"{base} ({seq:03d})"
            if not desc_cleaned or desc_cleaned == title_raw.strip():
                desc_cleaned = ""
        year = date[:4]
        name = sanitize_name(build_name(title_norm, event, year, is_camera), pid, ext)
        desc_field = build_description(desc_cleaned, event or ACCOUNT_NAME)

        archive_ts = rec.get("archive_ts") or ""
        if not archive_ts:
            m = re.search(r"web/(\d{14})/", rec.get("source_url") or "")
            archive_ts = m.group(1) if m else ""
        photo_id = str(rec.get("id") or pid)
        source = (f"[{ARCHIVE_BASE}/{archive_ts}/https://www.flickr.com/photos/"
                  f"{NSID}/{photo_id}/ archived Flickr photo page]" if archive_ts else "")
        author = f"{AUTHOR}" + (f" / {photographer}" if photographer else "")

        rows.append({
            "path": os.path.abspath(local) if local else img_url,
            "name": name,
            "description": desc_field,
            "date": date,
            "source": source,
            "archive_ts": archive_ts,
            "photo_id": photo_id,
            "author": author,
            "photographer": photographer or "",
            "categories": ";".join(cats),
            "license": license_id,
            "title": title_norm,
            "other_fields": other_fields,
        })

    import csv
    headers = list(rows[0].keys()) if rows else []
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        w.writerows(rows)

    print(f"to scrape: {len(to_scrape)} | rows: {len(rows)}")
    for k, v in skipped.items():
        print(f"  skipped ({k}): {v}")
    print(f"wrote {args.out} ({len(rows)} rows, {len(headers)} columns)")


if __name__ == "__main__":
    main()
