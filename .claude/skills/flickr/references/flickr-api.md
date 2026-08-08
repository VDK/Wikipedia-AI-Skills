# Flickr read-only API reference

Everything here is read-only (no OAuth). Base endpoint: `https://api.flickr.com/services/rest/`.

## Request shape

```
GET https://api.flickr.com/services/rest/?method=<method>&api_key=<KEY>&format=json&nojsoncallback=1&...
```

- `format=json` + `nojsoncallback=1` → plain JSON (without `nojsoncallback` you get a JS callback wrapper).
- Response envelope: `{ "stat": "ok", <container> }` or `{ "stat": "fail", "code": <n>, "message": "..." }`.
- Always send a descriptive `User-Agent`.

## Methods

### flickr.photosets.getPhotos
All photos in a photoset. Required: `photoset_id`, `user_id`. Response container: `photoset` (`page, pages, perpage, total, title, owner, ownername, photo[]`).

> The owner lives on the container, not per photo. Copy `photoset.owner`/`photoset.ownername` onto photos missing them.

### flickr.photos.search
Text search. Required: none (but parameterless searches are disabled — supply `text` or a scope). Optional: `user_id`, `tags`, `tag_mode`, `license`, `sort`, `min_taken_date`, `max_taken_date`, `extras`, `per_page`, `page`. Response container: `photos` (`page, pages, perpage, total, photo[]`).

### flickr.photos.getInfo
Single photo metadata. Required: `photo_id`. Optional: `secret`. Response container: `photo` with:

- `owner`: `nsid`, `username`, `realname`, `location`, `path_alias`
- `dates`: `taken` (string), `posted` (unix), `takengranularity` (0=full, 4=year, 6=year+month, 8=circa), `takenunknown` (`1` = unknown)
- `location` (only when geotagged): `latitude`, `longitude`, `accuracy`, `place_id`, `woeid`, `region`, `country`
- `title`/`description`: objects with `_content`
- `tags.tag[]`: tag objects with `raw`, `_content`, `machine_tag`
- `license`, `originalformat`

### flickr.people.findByUsername
Resolve a username to an NSID. Required: `username`. Container: `user.nsid`.

### flickr.people.getInfo
Owner profile. Required: `user_id`. Container: `person` (`realname`, `username`, `location`, `photosurl`, `path_alias`).

### flickr.tags.getListPhoto
Tags of one photo. Required: `photo_id`. Container: `photo.tags.tag[]`.

### flickr.photos.getSizes
Available image sizes. Required: `photo_id`. Container: `sizes.size[]` (`label`, `width`, `height`, `source`, `url`).

## Extras

Comma-delimited `extras` fields on list calls:

```
description, date_upload, date_taken, last_update, license, owner_name,
tags, machine_tags, views, media, path_alias,
url_sq, url_t, url_s, url_q, url_m, url_n, url_z, url_c, url_l, url_o,
original_format, geo, o_dims, icon_server
```

Production set for Commons prep (flickr2commons): `description,license,date_taken,geo,tags,url_o,url_l,url_m,url_q,url_s,path_alias,original_format`.

Notes:

- `description`/`title` are objects with `_content` on getInfo; `title` is a plain string on list calls.
- `geo` → object with `latitude`, `longitude`, `accuracy`, `context`, `place_id`, `woeid`.
- `tags` on list calls → space-separated string; on getInfo → `photo.tags.tag[]`.
- `original_format` → real extension (`png`, `tif`, …).
- Image URLs: prefer `url_o` → `url_l` → `url_c` → `url_z` → `url_m`.

## License ids

| id | License |
|---|---|
| 0 | All Rights Reserved |
| 1 | CC BY-NC-SA 2.0 |
| 2 | CC BY-NC 2.0 |
| 3 | CC BY-NC-ND 2.0 |
| 4 | CC BY 2.0 |
| 5 | CC BY-SA 2.0 |
| 6 | No known copyright restrictions |
| 7 | No known copyright restrictions (US) |
| 8 | US Government Work |
| 9 | CC0 |
| 10 | Public Domain Mark |
| 11 | CC BY 4.0 |
| 12 | CC BY-SA 4.0 |

Commons-compatible (free) set: `4, 5, 7, 8, 9, 10, 11, 12`.

## Error codes (common)

| code | meaning |
|---|---|
| 1 | Photo not found |
| 2 | User not found |
| 3 | Parameterless searches disabled |
| 5 | User deleted |
| 100 | Invalid API key |
| 105 | Service unavailable |
| 108 | Invalid photoset id |
| 109 | Invalid method |

## Rate limits & etiquette

- ~3600 requests/hour per key; a full photoset with `per_page=500` uses ~1 request per 500 photos.
- Descriptive `User-Agent`; reasonable `per_page` (500); paginate fully.

## Official specs

- Machine-readable (25 read-only methods): `https://github.com/flickr/flickr-api-swagger` (mirrored at `https://github.com/jentic/jentic-public-apis` → `apis/openapi/flickr.com/main/1.0.0/openapi.json`).
- Full HTML reference (~200 methods): `https://www.flickr.com/services/api/`.
- Working implementation to consult before the raw spec: the flickr2commons Toolforge tool (`https://flickr2commons.toolforge.org/`; local mirror `C:\xampp\htdocs\flickr2commons`, library `magnustools/public_html/resources/js_es6/flickr2commons.js`, template generator `fist/public_html/file_candidates/flinfo_proxy.php`).
