"""JSONL document streaming - the interchange-format reader (ADR 0003).

Promoted to core at the third consumer (corpus shards, tokenizer train/eval,
chunking - design-review deferral 2026-07). Blank lines are skipped, matching
the historical read_shard behavior; the missing-file hint is caller-supplied
because the right remedy depends on the stage.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from cankar.core.errors import CankarError


def iter_jsonl_docs(path: Path, missing_hint: str = "") -> Iterator[dict]:
    """Parsed docs in file order - the deterministic stream every stage uses.
    The existence check is EAGER (design-review 2026-07): a generator-deferred
    check fires at first next(), after callers may have opened output files."""
    if not path.exists():
        suffix = f" ({missing_hint})" if missing_hint else ""
        raise CankarError(f"JSONL file not found: {path}{suffix}")
    return _iter_lines(path)


def _iter_lines(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)
