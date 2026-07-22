"""Wiki markup → plain NFC text. Shared by the Wikivir crawler and (later)
the Wikipedia dump ingester — one clean() so both corpora get identical
normalization (golden-tested in tests/test_clean.py)."""

from __future__ import annotations

import re
import unicodedata

import mwparserfromhell

REDIRECT_RE = re.compile(r"^\s*#(redirect|preusmeritev)", re.IGNORECASE)
# category wikilinks survive strip_code() as bare "Kategorija:X" text lines
CATEGORY_LINE_RE = re.compile(r"^(Kategorija|Category):\S.*$", re.MULTILINE)
# strip_code() inlines <ref> footnote CONTENTS into prose — remove refs wholesale
REF_RE = re.compile(r"<ref[^>/]*(?:/>|>.*?</ref>)", re.DOTALL | re.IGNORECASE)
# Wikisource caret-notation footnote lines ("^Zgodovina črtica.") — never legit prose
CARET_LINE_RE = re.compile(r"^\^.*$", re.MULTILINE)
# index/catalog page titles ("Seznam del Ivana Cankarja") — bibliographies, not literature
INDEX_TITLE_RE = re.compile(r"^(Abecedni )?[Ss]eznam ")


def is_index_title(title: str) -> bool:
    """True for list/bibliography pages that must not enter the corpus."""
    return bool(INDEX_TITLE_RE.match(title))


def is_redirect(wikitext: str) -> bool:
    return bool(REDIRECT_RE.match(wikitext))


def clean_wikitext(wikitext: str) -> str:
    """Strip wiki markup, NFC-normalize (č/š/ž NFD bugs are real), tidy whitespace."""
    wikitext = REF_RE.sub("", wikitext)
    code = mwparserfromhell.parse(wikitext)
    text = code.strip_code(normalize=True, collapse=True)
    text = unicodedata.normalize("NFC", text)
    text = CATEGORY_LINE_RE.sub("", text)
    text = CARET_LINE_RE.sub("", text)
    # collapse 3+ newlines, strip trailing spaces per line
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
