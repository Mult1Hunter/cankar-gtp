"""Shard provenance manifests (ADR 0003): regenerate and diff to verify.

Every corpus shard `<name>.jsonl` gets a sibling `<name>.manifest.json` that is
the authority on its expected schema, counts, and sanity band - the corpus-qa
agent reads it before auditing.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel


class ShardManifest(BaseModel):
    schema_version: int = 1
    source: str  # e.g. "wikivir"
    script: str  # repo-relative generating script
    git_sha: str
    retrieved_at: str  # ISO 8601 UTC
    args: dict[str, object]  # CLI args used, for reproduction
    n_docs: int
    n_chars: int
    n_words: int
    sha256: str  # content hash of the shard file
    expected_band_words: tuple[int, int] | None = None  # sanity band (corpus-qa)
    # per-reason drop counts for sources that filter by count, not per-item triage
    # (ADR 0004 amendment: this IS the committed "never silently dropped" record)
    skip_counts: dict[str, int] | None = None


def git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def write_manifest(manifest: ShardManifest, out: Path) -> Path:
    """Write to the committed ledger path (cankar.core.paths.dataset_manifest) -
    manifests are provenance and live in git, never only beside gitignored data."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest.model_dump(), ensure_ascii=False, indent=2) + "\n")
    return out
