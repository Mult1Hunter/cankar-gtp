"""Generated registry reports: per-author coverage + cross-author collisions.

Everything this module writes lands in registry/reports/ with a GENERATED
marker and must regenerate byte-identically (CI drift check, ADR 0007).
Human annotations belong in registry/works/NOTES.md, never here.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from cankar.core.reports import generated_marker, write_report
from cankar.corpus.registry import Registry, SourceStatus, WorkFlag, WorkRecord, normalize_title

GENERATED_MARKER = generated_marker("cankar corpus report", snapshot=False)


def work_status(w: WorkRecord) -> str:
    # a misattribution is never Cankar coverage, even though its text was fetched
    # (SourceRef stays 'ingested' - honest about the crawl); it must not inflate the
    # ingested count that quality claims lean on (ADR 0014).
    if WorkFlag.NOT_BY_AUTHOR in w.flags:
        return "excluded (not by author)"
    statuses = {(s.source, s.status) for s in w.sources}
    if any(st is SourceStatus.INGESTED for _, st in statuses):
        srcs = sorted({str(src) for src, st in statuses if st is SourceStatus.INGESTED})
        return f"ingested ({'+'.join(srcs)})"
    if any(st is SourceStatus.CANDIDATE for _, st in statuses):
        return "candidate (text exists, not fetched)"
    if any(str(st).startswith("skipped") for _, st in statuses):
        return next(str(st) for _, st in sorted(statuses) if str(st).startswith("skipped"))
    return "missing (no usable source known)"


def write_coverage(registry_path: Path, author: str, out: Path) -> Counter:
    reg = Registry.load(registry_path, author)
    rows = sorted(reg.works.values(), key=lambda w: w.work_id)
    counts = Counter(work_status(w) for w in rows)

    lines = [
        GENERATED_MARKER,
        f"# Coverage - {author}",
        "",
        f"Source registry: `{registry_path.name}`. Regenerate: `cankar corpus report --all`.",
        "",
        f"**{len(rows)} known works.**",
        "",
        "| Status | Works |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in sorted(counts.items())],
        "",
        "| Work | Year | Genre | Status | Sources |",
        "|---|---|---|---|---|",
    ]
    for w in rows:
        srcs = "; ".join(f"{s.source}:{s.status}" for s in w.sources) or "-"
        flags = f" [{', '.join(w.flags)}]" if w.flags else ""
        lines.append(
            f"| {w.title}{flags} | {w.year or ''} | {w.genre or ''} | {work_status(w)} | {srcs} |"
        )

    write_report(out, lines)
    return counts


def cross_author_collisions(registry_paths: list[Path]) -> list[str]:
    by_norm: dict[str, list[str]] = defaultdict(list)
    for path in registry_paths:
        for line in path.read_text().splitlines():
            if not line:
                continue
            w = WorkRecord.model_validate_json(line)
            by_norm[normalize_title(w.title)].append(f"{w.author}: {w.title} ({path.name})")
    return sorted(
        f"title collision across authors - confirm these are different works: {sorted(entries)}"
        for entries in by_norm.values()
        if len({e.split(":")[0] for e in entries}) > 1
    )


def write_collisions(registry_paths: list[Path], out: Path) -> int:
    collisions = cross_author_collisions(registry_paths)
    lines = [
        GENERATED_MARKER,
        "# Cross-author title collisions",
        "",
        "Human resolution notes live in `registry/works/NOTES.md` (never here).",
        "",
        *[f"- {c}" for c in collisions],
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    return len(collisions)
