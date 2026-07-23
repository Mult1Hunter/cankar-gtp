"""Repo-anchored path policy - the only place artifact locations are defined.

Hardcoded relative f-string paths break the moment CWD changes (RunPod pods,
Phase 3); every module computes locations through these helpers instead
(ADR 0007). Assumes an editable install (uv sync), which this repo always uses.
"""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def works_registry(slug: str) -> Path:
    return repo_root() / "registry" / "works" / f"{slug}.jsonl"


def works_registries() -> list[Path]:
    return sorted((repo_root() / "registry" / "works").glob("*.jsonl"))


def corpus_shard(slug: str) -> Path:
    return repo_root() / "data" / "corpus" / f"{slug}.jsonl"


def dataset_manifest(stage: str, name: str) -> Path:
    """Committed provenance ledger (ADR 0007): manifests live in git, not in
    gitignored data/ - otherwise 'regenerate and diff' is unimplementable."""
    return repo_root() / "registry" / "datasets" / stage / f"{name}.manifest.json"


def corpus_dir() -> Path:
    return repo_root() / "data" / "corpus"


def coverage_report(slug: str) -> Path:
    return repo_root() / "registry" / "reports" / f"coverage-{slug}.md"


def collisions_report() -> Path:
    return repo_root() / "registry" / "reports" / "collisions.md"


def quality_report() -> Path:
    """Snapshot report (computed from gitignored data/) - see reports README."""
    return repo_root() / "registry" / "reports" / "corpus-quality.md"


def near_duplicates_report() -> Path:
    """Snapshot report (computed from gitignored data/) - see reports README."""
    return repo_root() / "registry" / "reports" / "near-duplicates.md"


def authors_config() -> Path:
    return repo_root() / "configs" / "corpus" / "authors.toml"
