"""Wikipedia-specific pre-cleaning and structural classification.

Runs BEFORE the shared cankar.corpus.clean.clean_wikitext (ADR 0007 keeps that
shared and its ada/noc goldens frozen). Wikipedia dump wikitext carries dirt
Wikisource never had - calibrated on real slwiki articles (2026-07):

- media wikilinks with a CASE-INSENSITIVE namespace ([[slika:...|thumb|...]])
  defeat strip_code and leak `thumb|300px|caption` fragments
- apparatus sections (== Viri ==, == Sklici ==, == Zunanje povezave == ...) are
  reference/link lists, not prose, and end nearly every article
- tables ({|...|}) nest and survive strip_code as jumbled cells
- interwiki links ([[en:...]]) leak as bare `en:Foo` lines
- render-only tag blocks (score, hiero, mapframe, syntaxhighlight, ...)

Classification is STRUCTURAL (templates/categories/title), never the
looks_like_index body heuristic - that was calibrated on Wikisource verse vs
bibliography and misfires on Wikipedia articles (proven: it flags the Levstik
biography and the Triglav article as bibliographies). ADR 0006.
"""

from __future__ import annotations

import re

import mwparserfromhell

# media namespace aliases (Slovene + English) matched on a wikilink's title;
# node-filtering (not regex) handles any caption nesting depth safely
_MEDIA_NS = ("slika", "datoteka", "file", "image", "berilo")
# interwiki language links: [[xx:Title]] or [[xx:Title|text]] with a 2-3 letter code
INTERWIKI_RE = re.compile(r"\[\[[a-z]{2,3}(?:-[a-z]+)?:[^\]]+\]\]")
# render-only tag blocks strip_code leaves as content
TAG_BLOCK_RE = re.compile(
    r"<(score|hiero|chem|mapframe|maplink|syntaxhighlight|source|imagemap|"
    r"gallery|timeline|math|templatestyles)\b[^>]*>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)
SELF_CLOSING_TAG_RE = re.compile(r"<(templatestyles|mapframe|maplink)\b[^>]*/>", re.IGNORECASE)

# apparatus / back-matter section headings (Slovene) - prose ends here
APPARATUS_HEADINGS = (
    "viri",
    "sklici",
    "opombe",
    "reference",
    "zunanje povezave",
    "glej tudi",
    "literatura",
    "nadaljnje branje",
    "sorodne strani",
    "opombe in sklici",
)
_APPARATUS_RE = re.compile(
    r"^=+\s*(" + "|".join(re.escape(h) for h in APPARATUS_HEADINGS) + r")\s*=+\s*$",
    re.IGNORECASE | re.MULTILINE,
)

DISAMBIG_RE = re.compile(r"\{\{\s*Razločitev|Kategorija:\s*Razločitev", re.IGNORECASE)


def is_disambiguation(wikitext: str) -> bool:
    """Structural disambiguation detection (template/category, not prose shape)."""
    return bool(DISAMBIG_RE.search(wikitext))


def truncate_apparatus(wikitext: str) -> str:
    """Cut everything from the first back-matter heading onward."""
    m = _APPARATUS_RE.search(wikitext)
    return wikitext[: m.start()] if m else wikitext


def _is_media_link(node: mwparserfromhell.nodes.Wikilink) -> bool:
    title = str(node.title).split(":", 1)
    return len(title) == 2 and title[0].strip().casefold() in _MEDIA_NS


def strip_tables_and_media(wikitext: str) -> str:
    """Remove tables and media wikilinks via node filtering - nesting-safe at any
    depth, unlike the caption-nesting regex it replaces (corpus-qa/critique #9).

    Known limitation (corpus-qa audit, full 125k-article run): ~3.8% of articles
    retain raw `{|...` markup because their tables are malformed/unclosed (no
    `|}`), which mwparserfromhell cannot parse as table nodes. Accepted for a
    pretraining layer (residue tokenizes harmlessly); a line-level `{|`/`|-` sweep
    is the fix if a Phase-2 pass ever needs it, deliberately not a fragile
    whole-table regex.
    """
    from mwparserfromhell.nodes import Node

    code = mwparserfromhell.parse(wikitext)
    doomed: list[Node] = list(code.filter_tags(matches=lambda n: n.tag == "table"))
    doomed += list(code.filter_wikilinks(matches=_is_media_link))
    for node in doomed:
        try:
            code.remove(node)
        except ValueError:
            pass  # already removed as a child of another removed node
    return str(code)


def wikipedia_preclean(wikitext: str) -> str:
    """Wikipedia pre-strip applied before the shared clean_wikitext."""
    text = truncate_apparatus(wikitext)
    text = TAG_BLOCK_RE.sub("", text)
    text = SELF_CLOSING_TAG_RE.sub("", text)
    text = strip_tables_and_media(text)
    text = INTERWIKI_RE.sub("", text)
    return text
