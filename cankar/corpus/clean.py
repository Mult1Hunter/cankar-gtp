"""Wiki markup -> plain NFC text. Shared by the Wikivir crawler and (later)
the Wikipedia dump ingester - one clean() so both corpora get identical
normalization (golden-tested in tests/test_clean.py)."""

from __future__ import annotations

import re
import unicodedata

import mwparserfromhell

REDIRECT_RE = re.compile(r"^\s*#(redirect|preusmeritev)", re.IGNORECASE)
# category wikilinks survive strip_code() as bare "Kategorija:X" text lines
CATEGORY_LINE_RE = re.compile(r"^(Kategorija|Category):\S.*$", re.MULTILINE)
# strip_code() inlines <ref> footnote CONTENTS into prose - remove refs wholesale
REF_RE = re.compile(r"<ref[^>/]*(?:/>|>.*?</ref>)", re.DOTALL | re.IGNORECASE)
# Wikisource caret-notation footnote lines ("^Zgodovina črtica.") - never legit prose
CARET_LINE_RE = re.compile(r"^\^.*$", re.MULTILINE)
# index/catalog page titles ("Seznam del Ivana Cankarja") - bibliographies, not literature
INDEX_TITLE_RE = re.compile(r"^(Abecedni )?[Ss]eznam ")
# raw HTML div tags and MediaWiki magic words survive strip_code()
DIV_RE = re.compile(r"</?div[^>]*>", re.IGNORECASE)
MAGIC_WORD_RE = re.compile(r"__[A-Z]+__")


def is_index_title(title: str) -> bool:
    """True for list/bibliography pages that must not enter the corpus."""
    return bool(INDEX_TITLE_RE.match(title))


# calibrated companions to the thresholds below (see docstring)
DIGIT_RULE_TITLE_FLOOR = 0.30  # digit evidence only counts when lines are title-shaped


def looks_like_index(
    text: str,
    title_ratio_threshold: float = 0.65,
    digit_ratio_threshold: float = 0.10,
) -> bool:
    """Content-based bibliography detector (corpus-qa finding, PD-authors audit).

    VERSE shares short unpunctuated lines with title lists - a naive short-line
    rule amputated ~150 poems on the first roster crawl. Two dimensions separate
    the classes (calibrated 2026-07 on real Wikivir pages; title_ratio/digit_ratio):
    poems Ubezni kralj 0.02/0.00, Pijanec 0.29/0.00, Na trgu 0.60/0.00 vs
    bibliographies Zbrano delo (Kette) 0.83/0.00, Lojze Grozde 0.79/0.16,
    Kazalo (Levstik) 0.35/0.56. Internal punctuation marks natural language;
    digit-bearing lines (years, page numbers) mark catalogs.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 10:
        return False
    title_like = sum(
        1
        for ln in lines
        if len(ln) < 60
        and not ln.endswith((".", "!", "?", "«", "“", '"'))
        and not any(c in ln for c in ",;:!?.")
    ) / len(lines)
    digit = sum(1 for ln in lines if any(ch.isdigit() for ch in ln)) / len(lines)
    return title_like > title_ratio_threshold or (
        digit > digit_ratio_threshold and title_like > DIGIT_RULE_TITLE_FLOOR
    )


def is_by_other_author(title: str, other_authors: list[str]) -> str | None:
    """Attribution guard (corpus-qa finding): a title like "Josip Stritar
    (Ivan Tavcar)" is an essay ABOUT the subject BY the parenthetical author.
    Returns the true author's name when the parenthetical names someone else
    on the roster."""
    m = re.search(r"\(([^)]+)\)\s*$", title)
    if not m:
        return None
    inner = m.group(1).strip()
    for other in other_authors:
        if inner == other:
            return other
    return None


def is_redirect(wikitext: str) -> bool:
    return bool(REDIRECT_RE.match(wikitext))


def clean_wikitext(wikitext: str) -> str:
    """Strip wiki markup, NFC-normalize (č/š/ž NFD bugs are real), tidy whitespace."""
    wikitext = REF_RE.sub("", wikitext)
    code = mwparserfromhell.parse(wikitext)
    text = code.strip_code(normalize=True, collapse=True)
    text = DIV_RE.sub("", text)
    text = MAGIC_WORD_RE.sub("", text)
    text = unicodedata.normalize("NFC", text)
    text = CATEGORY_LINE_RE.sub("", text)
    text = CARET_LINE_RE.sub("", text)
    # collapse 3+ newlines, strip trailing spaces per line
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
