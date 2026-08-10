#!/usr/bin/env python3
"""Create a Commons year category and a Wikidata edition item for a recurring event.

Example:
  python create_edition.py --event "Crossing Europe" --year 2027 \\
      --series Q1141279 --edition-type Q27787439 --location Q41329 --country Q40 \\
      --edition-no 23 --decade 200 \\
      --parents "2027 film festivals" "2027 events in Linz" \\
      --desc "annual film festival held in Linz, Austria, since 2004" \\
      --prev Q140965123 --next Q140965125 --dry

Existing categories and items are detected and skipped (reruns are safe).
When --prev and/or --next are given, the neighboring items are updated
(P156 on the previous edition, P155 on the next edition) so the P155/P156
chain stays consistent both ways.

Run from inside a pywikibot checkout with user-config.py configured for the
'commons' and 'wikidata' sites.
"""

import argparse
import sys
import time

import pywikibot


def robust(fn, *args, retries=5, base_delay=20, **kwargs):
    """Retry an edit, typically because of Wikidata replication lag (maxlag)."""
    for attempt in range(retries):
        try:
            return fn(*args, **kwargs)
        except pywikibot.exceptions.OtherPageSaveError as exc:
            if attempt == retries - 1:
                raise
            print(f'   retry {attempt + 1} after: {str(exc)[:120]}')
            time.sleep(base_delay * (attempt + 1))


def make_claim(repo, pid, target):
    c = pywikibot.Claim(repo, pid)
    c.setTarget(target)
    return c


def claims_of(item):
    try:
        return item.claims
    except Exception:
        return {}


def desc_of(item):
    try:
        return item.descriptions
    except Exception:
        return {}


def sitelinks_of(item):
    try:
        return item.sitelinks
    except Exception:
        return {}


def add_claim_if_missing(item, repo, pid, target, summary, dry):
    """Add a claim unless an identical one exists. target is an ItemPage,
    a str, or a WbTime."""
    for c in claims_of(item).get(pid, []):
        t = c.getTarget()
        if t is None:
            continue
        if isinstance(target, str):
            if str(t) == target:
                return
        elif hasattr(target, 'year'):  # WbTime
            if getattr(t, 'year', None) == target.year:
                return
        elif getattr(t, 'getID', lambda: None)() == target.getID():
            return
    if dry:
        if isinstance(target, str):
            show = target
        elif hasattr(target, 'year'):
            show = target.year
        else:
            show = target.getID()
        print(f'   would add {pid} -> {show}')
        return
    robust(item.addClaim, make_claim(repo, pid, target), summary=summary)
    print(f'   added {pid} -> {getattr(target, "year", target)}')


def find_item_for_category(commons, repo, cat_title):
    """Return the ItemPage linked to a Commons category, or None."""
    page = pywikibot.Page(commons, cat_title)
    try:
        item = pywikibot.ItemPage.fromPage(page)
        item.get()
        return item
    except Exception:
        pass
    try:
        data = repo.simple_request(action='wbgetentities', sites='commonswiki',
                                   titles=cat_title, props='info').submit()
        for qid, ent in data.get('entities', {}).items():
            if not ent.get('missing'):
                item = pywikibot.ItemPage(repo, qid)
                item.get()
                return item
    except Exception:
        pass
    return None


def ensure_sitelink(item, commons, cat_title, dry):
    if cat_title in sitelinks_of(item):
        return
    if dry:
        print(f'   would set sitelink commonswiki -> {cat_title}')
        return
    robust(item.setSitelink, pywikibot.SiteLink(cat_title, site=commons),
           summary='Link Commons category')
    print('   set sitelink')


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--event', required=True, help='event name, e.g. "Crossing Europe"')
    ap.add_argument('--year', required=True, type=int)
    ap.add_argument('--series', required=True, help='QID of the event/series item')
    ap.add_argument('--edition-type', required=True,
                    help='QID of the edition class, e.g. Q27787439')
    ap.add_argument('--location', required=True, help='QID of the city, e.g. Q41329')
    ap.add_argument('--country', required=True, help='QID of the country, e.g. Q40')
    ap.add_argument('--edition-no', required=True, type=int,
                    help='ordinal edition number (P393)')
    ap.add_argument('--decade', type=int, default=None,
                    help='decade for the navbox, e.g. 200')
    ap.add_argument('--parents', nargs='*', default=[],
                    help='extra parent categories, e.g. "2027 film festivals"')
    ap.add_argument('--desc', default=None,
                    help='English description; default "film festival edition"')
    ap.add_argument('--prev', default=None, help='QID of the previous edition item')
    ap.add_argument('--next', default=None, help='QID of the next edition item')
    ap.add_argument('--put-throttle', type=float, default=2.0)
    ap.add_argument('--dry', action='store_true', help='preview without editing')
    args = ap.parse_args()

    pywikibot.config.put_throttle = args.put_throttle

    commons = pywikibot.Site('commons', 'commons')
    repo = pywikibot.Site('wikidata', 'wikidata')
    if not args.dry:
        commons.login()
        repo.login()

    label = f'{args.event} {args.year}'
    cat_title = f'Category:{label}'
    desc = args.desc or 'film festival edition'

    # --- 1. Commons year category -----------------------------------------
    page = pywikibot.Page(commons, cat_title)
    if page.exists():
        print(f'skip category (exists): {cat_title}')
    else:
        text = '{{Wikidata Infobox}}\n'
        if args.decade is not None:
            text += (f'{{{{Decade years navbox\n|header={{{{C|{args.event}}}}}\n'
                     f'|decade={args.decade}\n|cat_prefix={args.event}\n'
                     f'|cat_suffix=\n}}}}\n\n')
        parent_lines = [f'[[Category:{p}]]' for p in args.parents]
        parent_lines.append(f'[[Category:{args.event}|{args.year}]]')
        text += '\n'.join(parent_lines) + '\n'
        print(f'create category {cat_title}')
        if not args.dry:
            page.text = text
            robust(page.save, summary=f'Create year category for {label}')
            print('   saved category')

    # --- 2. Wikidata edition item -----------------------------------------
    item = find_item_for_category(commons, repo, cat_title)
    if item is None:
        print(f'no existing item; create new: {label}')
        item = pywikibot.ItemPage(repo)
        if not args.dry:
            robust(item.editLabels, {'en': label}, summary=f'Create item for {label}')
            robust(item.editDescriptions, {'en': desc}, summary=f'Create item for {label}')
            print('   created item', item.title())
    else:
        print(f'found existing item: {item.title()}')
        if desc_of(item).get('en') != desc:
            if args.dry:
                print(f'   would set description en = {desc!r}')
            else:
                robust(item.editDescriptions, {'en': desc},
                       summary='Align description with series pattern')

    # --- 3. Claims ---------------------------------------------------------
    add_claim_if_missing(item, repo, 'P31',
                         pywikibot.ItemPage(repo, args.edition_type), 'Add edition type', args.dry)
    add_claim_if_missing(item, repo, 'P179',
                         pywikibot.ItemPage(repo, args.series), 'Add event series', args.dry)
    add_claim_if_missing(item, repo, 'P276',
                         pywikibot.ItemPage(repo, args.location), 'Add location', args.dry)
    add_claim_if_missing(item, repo, 'P17',
                         pywikibot.ItemPage(repo, args.country), 'Add country', args.dry)
    add_claim_if_missing(item, repo, 'P393', str(args.edition_no), 'Add edition number', args.dry)
    add_claim_if_missing(item, repo, 'P373', label, 'Add Commons category', args.dry)
    add_claim_if_missing(item, repo, 'P585',
                         pywikibot.WbTime(year=args.year, precision='year'),
                         'Add year of edition', args.dry)
    ensure_sitelink(item, commons, cat_title, args.dry)

    # --- 4. P155/P156 chaining --------------------------------------------
    if args.prev:
        prev = pywikibot.ItemPage(repo, args.prev)
        prev.get()
        add_claim_if_missing(item, repo, 'P155', prev, 'Add previous edition', args.dry)
        add_claim_if_missing(prev, repo, 'P156', item, 'Add next edition', args.dry)
    if args.next:
        nxt = pywikibot.ItemPage(repo, args.next)
        nxt.get()
        add_claim_if_missing(item, repo, 'P156', nxt, 'Add next edition', args.dry)
        add_claim_if_missing(nxt, repo, 'P155', item, 'Add previous edition', args.dry)

    print('DONE')
    sys.exit(0)


if __name__ == '__main__':
    main()
