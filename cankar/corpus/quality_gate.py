"""Per-document quality gate for the merge stage - drops non-literary and
non-Slovene docs that survived crawl-time guards.

Calibrated on the real strays a stopword-ratio probe surfaced across the
literary shards (2026-07). Design lesson applied (ADR 0006, twice now - the
poem-amputation and the looks_like_index recalibration): a SINGLE scalar cannot
separate the failure classes, so the gate is three orthogonal signals, each
catching a class the others miss, each with margin against real verse/prose:

- language      slovene_ratio < LANG_FLOOR  -> NOT_SLOVENE
                (German study 0.01; real verse floor is 0.11, lyric 0.29)
- bibliography  year_ratio > YEAR_CEIL      -> BIBLIOGRAPHY
                (author works-lists: Primoz Trubar 14%, Izidor Cankar 22%;
                 real literary max is Bajke 0.8% - these are prose-shaped so
                 looks_like_index misses them)
- index/TOC     looks_like_index(text)      -> INDEX_LIST
                (line-structured tables of contents; reuses clean.py)

Applies to LITERARY shards only. Wikipedia proper-noun stubs legitimately sit
at slovene_ratio 0.00, so the language signal is not a quality signal there -
the merge does not gate Wikipedia (its noise is handled structurally upstream).
"""

from __future__ import annotations

import re
from enum import StrEnum

from cankar.corpus.clean import looks_like_index

# Slovene high-frequency function words - a closed lexical anchor for "is this
# running Slovene prose/verse". Deliberately conservative (unambiguous forms).
_STOPWORDS = frozenset(
    "je in se da na ne so za ki po pa bi kot ali iz pri ga mu le še že tudi ko če "
    "ni bil bila bili bo bodo med do od kaj to ta ter sem si smo ste nad pod kjer "
    "ves vsa vse ima imajo pa saj ker".split()
)
_YEAR_RE = re.compile(r"\b1[5-9]\d\d\b|\b20\d\d\b")  # 1500-2099, the catalog tell
_SAMPLE = 2000  # tokens inspected; signals are uniform over these doc classes

LANG_FLOOR = 0.05  # min Slovene-stopword ratio; 2x margin below the 0.11 verse floor
YEAR_CEIL = 0.05  # max year-token ratio; real literature peaks ~0.8%, catalogs 7-22%


class GateVerdict(StrEnum):
    """Why a doc was kept or dropped (closed set, ADR 0008)."""

    KEPT = "kept"
    NOT_SLOVENE = "not_slovene"
    BIBLIOGRAPHY = "bibliography"
    INDEX_LIST = "index_list"


def _tokens(text: str) -> list[str]:
    return text.split()[:_SAMPLE]


def slovene_ratio(text: str) -> float:
    """Fraction of the leading tokens that are Slovene function words - the
    language/register signal. Low = foreign, catalog, or bare list."""
    toks = _tokens(text)
    if not toks:
        return 0.0
    hits = sum(1 for t in toks if t.strip(".,;:!?\"'()[]«»").casefold() in _STOPWORDS)
    return hits / len(toks)


def year_ratio(text: str) -> float:
    """Fraction of leading tokens that are 4-digit years - the bibliography
    signal (works-lists are dense with 'Title, YEAR')."""
    toks = _tokens(text)
    if not toks:
        return 0.0
    return len(_YEAR_RE.findall(" ".join(toks))) / len(toks)


def gate(text: str) -> GateVerdict:
    """Classify one literary doc. First matching signal wins; order is by
    confidence (language is the hardest signal, index the softest)."""
    if slovene_ratio(text) < LANG_FLOOR:
        return GateVerdict.NOT_SLOVENE
    if year_ratio(text) > YEAR_CEIL:
        return GateVerdict.BIBLIOGRAPHY
    if looks_like_index(text):
        return GateVerdict.INDEX_LIST
    return GateVerdict.KEPT
