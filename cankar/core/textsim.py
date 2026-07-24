"""Shingle + containment text-similarity primitives (promoted to core at the
second stage consumer - corpus dedup/merge and evals holdout-closure both
need them; design-review 2026-07, rule of two).

FineWeb-calibrated: word 5-grams. The corpus merge DROPS docs at these
thresholds, so real labeled pairs are committed as fixtures (see
tests/corpus/test_dedup.py).
"""

from __future__ import annotations

import re

SHINGLE = 5  # word n-gram size
CONTAINMENT_THRESHOLD = 0.80  # a's shingles this-fraction inside b -> a contained in b

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def shingles(text: str, k: int = SHINGLE) -> set[bytes]:
    """Word k-gram set - the unit both MinHash and containment operate on."""
    words = _WORD_RE.findall(text.casefold())
    if len(words) < k:
        return {" ".join(words).encode()} if words else set()
    return {" ".join(words[i : i + k]).encode() for i in range(len(words) - k + 1)}


def containment(sub: set[bytes], whole: set[bytes]) -> float:
    """Asymmetric overlap: fraction of `sub`'s shingles present in `whole`.
    High = sub is CONTAINED in whole (a chapter inside its collected volume) -
    the duplication class Jaccard/MinHash structurally miss, because a small
    part's shingles are a tiny fraction of the whole's union (design-review M4)."""
    if not sub:
        return 0.0
    return len(sub & whole) / len(sub)
