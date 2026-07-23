"""Shared metric helpers (rule of three - design-review 2026-07: corpus
stats, tokenizer eval, and chunking all computed percentiles, with two
different index formulas between them. One definition lives here)."""

from __future__ import annotations

from collections.abc import Sequence


def percentile(sorted_values: Sequence[int | float], q: float) -> int | float:
    """Nearest-rank percentile over an ALREADY SORTED sequence; 0 when empty."""
    if not sorted_values:
        return 0
    return sorted_values[int(q * (len(sorted_values) - 1))]
