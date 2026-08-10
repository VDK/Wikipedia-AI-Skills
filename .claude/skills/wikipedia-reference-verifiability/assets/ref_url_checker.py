"""Reference URL checker for Wikipedia pages.

Detects whether a page's references contain any HTTP/HTTPS URLs.
Handles ref tags, citation templates with URL parameters, named ref
resolution, shortened footnotes, and nested templates.

Main entry point: `has_any_url_refs(wikitext)`.
"""

from __future__ import annotations

import re

import mwparserfromhell


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def has_any_url_refs(
    wikitext: str,
) -> tuple[bool, int, int, list[str]]:
    """Analyze a page's wikitext for URL presence in references.

    Args:
        wikitext: The raw wikitext of a Wikipedia page.

    Returns:
        A tuple ``(has_any_url, total_refs, url_refs, sample_bad_refs)``:
        - ``has_any_url``: True if at least one reference contains a URL
        - ``total_refs``: Total reference count
        - ``url_refs``: Count of references with URLs
        - ``sample_bad_refs``: Up to 5 snippets of URL-free references
    """
    parsed = mwparserfromhell.parse(wikitext)

    # ---- Step 1: Collect all ref tags ----
    ref_tags = parsed.filter_tags(
        matches=lambda t: str(t.tag).strip().lower() == "ref"
    )

    # ---- Step 2: Index named ref definitions, keyed by (group, name) ----
    # Ref names are scoped per group (Cite extension): a reuse in group "n"
    # does NOT resolve against a definition in the default group, and vice
    # versa. Indexing by bare name would produce false "has URL" results.
    named_defs: dict[tuple[str, str], str] = {}
    for tag in ref_tags:
        name = _named_ref_name(tag)
        content = _tag_content(tag)
        if name and content:
            key = (_ref_group(tag), name)
            if key not in named_defs:
                named_defs[key] = content

    # ---- Step 3: Evaluate each ref ----
    total, url_count, bad_samples, _ = _evaluate_refs(
        ref_tags, named_defs, _ref_has_url
    )

    # ---- Step 4: Inline citation templates outside <ref> ----
    for template in parsed.filter_templates():
        name = str(template.name).strip().lower()
        if _is_citation_template(name):
            if _is_inside_ref(template, ref_tags):
                continue
            total += 1
            if _template_has_url_param(template):
                url_count += 1

    return (url_count > 0, total, url_count, bad_samples)


def has_any_verifiable_refs(
    wikitext: str,
) -> tuple[bool, int, int, list[str]]:
    """Like ``has_any_url_refs`` but identifiers count as verifiable.

    A DOI, PMID, PMCID, ISBN, ISSN, OCLC, JSTOR, Bibcode, arXiv, S2CID, or
    eprint parameter makes a source verifiable online even without a URL
    (identifiers resolve to landing pages / catalogs). Same return shape:
    ``(has_verifiable, total_refs, verifiable_refs, sample_unverifiable)``.
    """
    parsed = mwparserfromhell.parse(wikitext)
    ref_tags = parsed.filter_tags(
        matches=lambda t: str(t.tag).strip().lower() == "ref"
    )

    named_defs: dict[tuple[str, str], str] = {}
    for tag in ref_tags:
        name = _named_ref_name(tag)
        content = _tag_content(tag)
        if name and content:
            key = (_ref_group(tag), name)
            if key not in named_defs:
                named_defs[key] = content

    def _is_verifiable(content: str, defs) -> bool:
        return _ref_has_url(content, defs) or _ref_has_identifier(content)

    total, ok_count, bad_samples, _ = _evaluate_refs(
        ref_tags, named_defs, _is_verifiable
    )

    for template in parsed.filter_templates():
        name = str(template.name).strip().lower()
        if _is_citation_template(name):
            if _is_inside_ref(template, ref_tags):
                continue
            total += 1
            if _template_has_url_param(template) or _template_has_identifier_param(template):
                ok_count += 1

    return (ok_count > 0, total, ok_count, bad_samples)


def _evaluate_refs(ref_tags, named_defs, check_fn) -> tuple[int, int, list[str], set]:
    """Shared ref evaluation: returns (total, ok, bad_samples, seen_named)."""
    total = 0
    ok_count = 0
    bad_samples: list[str] = []
    seen_named: set[tuple[str, str]] = set()

    for tag in ref_tags:
        name = _named_ref_name(tag)
        group = _ref_group(tag)
        key = (group, name) if name else None
        content = _tag_content(tag)

        if not content and name:
            content = named_defs.get(key, "")
        elif not content:
            continue

        if key:
            if key in seen_named:
                continue
            seen_named.add(key)

        total += 1
        if check_fn(content, named_defs):
            ok_count += 1
        else:
            if len(bad_samples) < 5:
                bad_samples.append(_summarize_ref(content))

    return total, ok_count, bad_samples, seen_named


def has_infobox(wikitext: str) -> bool:
    """Return True if the page wikitext contains an infobox template."""
    try:
        parsed = mwparserfromhell.parse(wikitext)
    except Exception:
        return False
    for template in parsed.filter_templates():
        name = str(template.name).strip()
        if name.lower().startswith("infobox"):
            return True
    return False


def get_shortened_footnotes(
    wikitext: str,
) -> list[dict[str, str]]:
    """Return a list of shortened footnote refs (harvsp, sfn, etc.).

    Each entry: ``{"author_year": str, "template": str}``.
    """
    parsed = mwparserfromhell.parse(wikitext)
    results: list[dict[str, str]] = []

    SHORT_FN = frozenset({"harvsp", "harvnb", "harv", "sfn", "harvard citation"})

    ref_tags = parsed.filter_tags(
        matches=lambda t: str(t.tag).strip().lower() == "ref"
    )

    for tag in ref_tags:
        content = _tag_content(tag)
        if not content:
            continue
        inner = mwparserfromhell.parse(content)
        for tpl in inner.filter_templates():
            name = str(tpl.name).strip().lower()
            if name in SHORT_FN or name.startswith("harv") or name.startswith("sfn"):
                results.append(
                    {
                        "author_year": str(tpl)[:80],
                        "template": name,
                    }
                )

    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

URL_RE = re.compile(r"https?://", re.IGNORECASE)

# Identifier parameters that make a source verifiable online WITHOUT a URL
# (e.g. a DOI resolves to a landing page, an ISBN to a library catalog).
# The skill's purpose is verifiability, and these identifiers satisfy it.
IDENTIFIER_PARAMS = frozenset(
    {
        "doi",
        "pmid",
        "pmc",
        "isbn",
        "issn",
        "oclc",
        "jstor",
        "bibcode",
        "arxiv",
        "s2cid",
        "eprint",   # cite arXiv / cite bioRxiv
    }
)

CITATION_TEMPLATES = frozenset(
    {
        "cite web",
        "cite news",
        "cite book",
        "cite journal",
        "cite magazine",
        "cite encyclopedia",
        "cite thesis",
        "cite report",
        "cite conference",
        "cite interview",
        "cite podcast",
        "cite episode",
        "cite serial",
        "cite sign",
        "cite speech",
        "cite map",
        "cite video",
        "cite av media",
        "citation",
        "web citation",
    }
)

URL_PARAM_NAMES = frozenset(
    {
        "url",
        "chapter-url",
        "conference-url",
        "contribution-url",
        "transcript-url",
        "archive-url",
        "chapterurl",
        "conferenceurl",
        "contributionurl",
        "transcripturl",
        "archiveurl",
    }
)

SHORTENED_FOOTNOTE_TEMPLATES = frozenset(
    {"harvsp", "harvnb", "harv", "sfn", "harvard citation"}
)


def _ref_has_url(ref_text: str, named_defs: dict[tuple[str, str], str]) -> bool:
    """Return True if a single <ref> body contains a URL."""
    if _contains_raw_url(ref_text):
        return True

    try:
        parsed = mwparserfromhell.parse(ref_text)
    except Exception:
        return _contains_raw_url(ref_text)

    for template in parsed.filter_templates():
        if _template_has_url_param(template):
            return True
        for param in template.params:
            try:
                inner = mwparserfromhell.parse(str(param.value))
                for nt in inner.filter_templates():
                    if _template_has_url_param(nt):
                        return True
            except Exception:
                if _contains_raw_url(str(param.value)):
                    return True

    return False


def _template_has_identifier_param(
    template: mwparserfromhell.nodes.Template,
) -> bool:
    """True if the template carries a verifiable identifier (DOI, ISBN, ...)."""
    for param in template.params:
        name = str(param.name).strip().lower()
        if name in IDENTIFIER_PARAMS:
            value = str(param.value).strip()
            if value and value.lower() not in ("none", "n/a"):
                return True
    return False


def _ref_has_identifier(ref_text: str) -> bool:
    """True if a ref body contains a verifiable identifier (DOI/ISBN/...)."""
    try:
        parsed = mwparserfromhell.parse(ref_text)
    except Exception:
        return False
    for template in parsed.filter_templates():
        if _template_has_identifier_param(template):
            return True
        for param in template.params:
            try:
                inner = mwparserfromhell.parse(str(param.value))
                for nt in inner.filter_templates():
                    if _template_has_identifier_param(nt):
                        return True
            except Exception:
                continue
    return False


def _contains_raw_url(text: str) -> bool:
    return bool(URL_RE.search(text))


def _template_has_url_param(
    template: mwparserfromhell.nodes.Template,
) -> bool:
    for param in template.params:
        name = str(param.name).strip().lower()
        if name in URL_PARAM_NAMES:
            value = str(param.value).strip()
            if value:
                return True
        if not name and _contains_raw_url(str(param.value)):
            return True
    return False


def _is_citation_template(name: str) -> bool:
    return name in CITATION_TEMPLATES or name.startswith("cite ")


def _is_shortened_footnote(name: str) -> bool:
    return (
        name in SHORTENED_FOOTNOTE_TEMPLATES
        or name.startswith("harv")
        or name.startswith("sfn")
    )


def _named_ref_name(tag: mwparserfromhell.nodes.Tag) -> str | None:
    if not tag.has("name"):
        return None
    name_val = str(tag.get("name").value).strip()
    if name_val and name_val[0] in ('"', "'"):
        name_val = name_val[1:]
    if name_val and name_val[-1] in ('"', "'"):
        name_val = name_val[:-1]
    return name_val.strip() or None


def _ref_group(tag: mwparserfromhell.nodes.Tag) -> str:
    """Return the ref's group attribute ("" for the default group).

    Refs are scoped per group: ``name="x"`` in group "n" is a DIFFERENT
    name from ``name="x"`` in the default (unnamed) group. Definitions
    must be resolved by the (group, name) pair, never by name alone.
    """
    if not tag.has("group"):
        return ""
    val = str(tag.get("group").value).strip()
    if val and val[0] in ('"', "'"):
        val = val[1:]
    if val and val[-1] in ('"', "'"):
        val = val[:-1]
    return val.strip()


def _tag_content(tag: mwparserfromhell.nodes.Tag) -> str:
    try:
        return str(tag.contents).strip()
    except Exception:
        return ""


def _is_inside_ref(
    template: mwparserfromhell.nodes.Template,
    ref_tags: list[mwparserfromhell.nodes.Tag],
) -> bool:
    for tag in ref_tags:
        try:
            tag_str = str(tag)
        except Exception:
            continue
        if str(template) in tag_str:
            return True
    return False


def _summarize_ref(content: str) -> str:
    """Produce a short, readable snippet of a reference body."""
    cleaned = re.sub(
        r"\{\{(\s*[Cc]ite\s+\w+|\s*[Hh]arv[np]?\w*|\s*[Ss]fn)\b[^}]*\}\}",
        lambda m: "[" + m.group(1).strip() + "]",
        content,
    )
    cleaned = re.sub(r"\{\{[^}]*\}\}", "[template]", cleaned)
    cleaned = re.sub(r"\[\[([^\]|\]]+)\|([^\]]+)\]\]", r"\2", cleaned)
    cleaned = re.sub(r"\[\[([^\]|]+)\]\]", r"\1", cleaned)
    cleaned = re.sub(r"'''''|'''|''", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > 80:
        cleaned = cleaned[:77] + "..."
    return cleaned or "(empty ref)"
