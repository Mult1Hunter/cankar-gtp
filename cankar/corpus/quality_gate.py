"""Per-document quality gate for the merge stage - drops non-literary and
non-Slovene docs that survived crawl-time guards.

Calibrated on the real strays a stopword-ratio probe surfaced across the
literary shards (2026-07). Design lesson applied (ADR 0006, twice now - the
poem-amputation and the looks_like_index recalibration): a SINGLE scalar cannot
separate the failure classes, so the gate is three orthogonal signals, each
catching a class the others miss, each with margin against real verse/prose:

- language      slovene_ratio < LANG_FLOOR  -> NOT_SLOVENE
                (German study 0.01; the lowest of 1042 kept docs is archaic
                 prose at 0.099, so the 0.05 floor has ~2x headroom and the
                 0.03-0.099 band is empty by measurement)
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
# running Slovene prose/verse". DERIVED, not hand-guessed: the multi-char
# function words among the 60 most frequent tokens across the literary corpus
# (2026-07 token-frequency count; `je` 412k ... `ji` 12k), plus a few common
# connectives just below that cut (vendar/zato/kadar/nic/kdo). Multi-char only -
# single-char prepositions (v z s k o a) are cross-lingual noise. Deriving it
# from the register the gate judges keeps the language signal honest.
_STOPWORDS = frozenset(
    "je in se da na ne so pa bi ni sem po ki za bil ga še ali kakor mu tudi to "
    "tako ko si mi bilo kaj od že iz vse bila ti če jo pri ter me jaz bo kako kar "
    "ta do le jih ker zdaj pred te več sta ji bili bo bodo med nad pod kjer ves "
    "vsa ima imajo saj kot vendar zato kadar nič kdo".split()
)
_YEAR_RE = re.compile(r"\b1[5-9]\d\d\b|\b20\d\d\b")  # 1500-2099, the catalog tell
_PUNCT = ".,;:!?\"'()[]«»"

LANG_FLOOR = 0.05  # min Slovene-stopword ratio; ~2x headroom below the 0.099 keep floor
YEAR_CEIL = 0.05  # max year-token ratio; real literature peaks ~0.8%, catalogs 7-22%


class GateVerdict(StrEnum):
    """Why a doc was kept or dropped (closed set, ADR 0008)."""

    KEPT = "kept"
    EMPTY = "empty"  # nothing to judge - distinct from affirmatively-foreign
    NOT_SLOVENE = "not_slovene"
    BIBLIOGRAPHY = "bibliography"
    INDEX_LIST = "index_list"


def slovene_ratio(text: str) -> float:
    """Fraction of tokens that are Slovene function words - the language/register
    signal. Low = foreign, catalog, or bare list. Whole-doc (literary docs are
    small), so a foreign preamble on a Slovene work cannot amputate it via a
    head-only sample."""
    toks = text.split()
    if not toks:
        return 0.0
    return sum(1 for t in toks if t.strip(_PUNCT).casefold() in _STOPWORDS) / len(toks)


def year_ratio(text: str) -> float:
    """Fraction of tokens that are 4-digit years - the bibliography signal
    (works-lists are dense with 'Title, YEAR')."""
    toks = text.split()
    if not toks:
        return 0.0
    return len(_YEAR_RE.findall(text)) / len(toks)


def gate(text: str) -> GateVerdict:
    """Classify one literary doc. First matching signal wins; order is by
    confidence (empty first, then language, bibliography, index)."""
    if not text.split():
        return GateVerdict.EMPTY
    if slovene_ratio(text) < LANG_FLOOR:
        return GateVerdict.NOT_SLOVENE
    if year_ratio(text) > YEAR_CEIL:
        return GateVerdict.BIBLIOGRAPHY
    if looks_like_index(text):
        return GateVerdict.INDEX_LIST
    return GateVerdict.KEPT
