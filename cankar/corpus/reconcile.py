"""dLib coverage reconciliation - which PD records with usable text are NOT in
the corpus?

Inverts crawl()'s record-driven flow into a coverage audit. The original crawl
was registry-gated: a dLib record whose title failed to match a registry entry
went to a gitignored triage file and was effectively lost (an external review
called this out as registry-as-hard-gate; it cost us recoverable works whose
dLib titles are journal-issue titles). Reconcile fixes the class:

- every PD record with a TEXT stream is classified into an explicit bucket
  (enumerated below - ADR 0006);
- unmatched-but-PD records are upserted into the committed registry as
  DLIB_DISCOVERED candidates (ledger, not gate) instead of dying in triage;
- the audit is a committed report, reproducible via
  `cankar corpus reconcile-dlib`;
- `--pull` ingests the PD_UNPULLED bucket through the same clean_and_gate
  sequence the crawl uses, into its own gap-fill shard + manifest.

CLI: `cankar corpus reconcile-dlib` (cankar.corpus.cli).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from cankar.core.http import PoliteSession
from cankar.core.reports import generated_marker, write_report
from cankar.core.schema import CorpusDoc
from cankar.corpus.dlib import (
    BASE,
    PD_MARKER,
    EdmRecord,
    clean_and_gate,
    enumerate_urns,
    parse_edm,
)
from cankar.corpus.registry import (
    Registry,
    Source,
    SourceRef,
    SourceStatus,
    WorkFlag,
    WorkRecord,
)
from cankar.corpus.shard import ShardWriter

logger = logging.getLogger(__name__)


class Bucket(StrEnum):
    """Every dLib DOC record lands in exactly one class (enumerated: ADR 0006)."""

    NOT_AUTHOR = "not_author"  # surname absent from contributors/creators
    MANUSCRIPT = "manuscript"  # handwriting scan, OCR unusable by policy
    NOT_SLOVENE = "not_slovene"
    IN_COPYRIGHT = "in_copyright"  # no PD rights marker on this edition
    PD_NO_TEXT = "pd_no_text"  # PD but dLib exposes no TEXT stream
    PD_INGESTED = "pd_ingested"  # this URN is already in a corpus shard
    PD_COVERED = "pd_covered"  # matched work already ingested from any source
    PD_UNPULLED = "pd_unpulled"  # PD + TEXT + known work not covered: THE GAP
    PD_UNMATCHED = "pd_unmatched"  # PD + TEXT, no registry match: discovery


@dataclass
class ReconcileStats:
    """Typed audit outcome (ADR 0008)."""

    counts: dict[Bucket, int] = field(default_factory=lambda: dict.fromkeys(Bucket, 0))
    unpulled: list[tuple[str, str, int | None]] = field(default_factory=list)  # urn, title, year
    unmatched: list[tuple[str, str, str | None]] = field(
        default_factory=list
    )  # urn, title, part_of
    pulled: int = 0
    pull_gate_failed: int = 0


def match_work(reg: Registry, title: str) -> WorkRecord | None:
    """Crawl matching plus one relaxation: dLib subtitles use ' : ' - retry with
    the subtitle stripped. Every strategy is exact-on-normalized (no fuzzy
    containment - name-collision safety per the registry verification rule)."""
    work = reg.find(title)
    if work is None and " : " in title:
        work = reg.find(title.split(" : ")[0])
    return work


def classify(
    meta: EdmRecord, urn: str, reg: Registry, surname: str
) -> tuple[Bucket, WorkRecord | None]:
    """Pure bucketing of one record - the testable core of the audit."""
    if not any(surname in p.casefold() for p in meta.people):
        return Bucket.NOT_AUTHOR, None
    if "rokopisi" in meta.types or "rokopis" in meta.types:
        return Bucket.MANUSCRIPT, None
    if meta.langs and "sl" not in meta.langs:
        return Bucket.NOT_SLOVENE, None
    if PD_MARKER not in meta.rights:
        return Bucket.IN_COPYRIGHT, match_work(reg, meta.title)
    if not meta.text_url:
        return Bucket.PD_NO_TEXT, match_work(reg, meta.title)

    work = match_work(reg, meta.title)
    if work is None:
        return Bucket.PD_UNMATCHED, None
    if any(
        s.source is Source.DLIB and s.id == urn and s.status is SourceStatus.INGESTED
        for s in work.sources
    ):
        return Bucket.PD_INGESTED, work
    if any(s.status is SourceStatus.INGESTED for s in work.sources):
        return Bucket.PD_COVERED, work
    return Bucket.PD_UNPULLED, work


def reconcile(
    *,
    query_contributor: str,
    author: str,
    registry_path: Path,
    report_out: Path,
    pull_out: Path | None = None,
    min_alpha: float = 0.84,
    min_chars: int = 400,
) -> ReconcileStats:
    """Audit dLib coverage; with pull_out set, ingest the PD_UNPULLED bucket."""
    reg = Registry.load(registry_path, author)
    surname = query_contributor.split(",")[0].strip().casefold()
    stats = ReconcileStats()

    session = PoliteSession()
    bootstrap = f"{BASE}/results/?query=%27contributor%3D{query_contributor.replace(' ', '%20')}%27"
    session.get(bootstrap)  # session cookie for TEXT streams

    urns = enumerate_urns(session, query_contributor)
    doc_urns = [u for u in urns if u.split(":")[-1].startswith("DOC-")]
    logger.info(f"{len(urns)} URNs, {len(doc_urns)} DOC records")

    to_pull: list[tuple[str, EdmRecord, WorkRecord]] = []
    for i, urn in enumerate(doc_urns, 1):
        if i % 50 == 0:
            logger.info(f"  classified {i}/{len(doc_urns)}")
        try:
            meta = parse_edm(session.get(f"{BASE}/{urn}/EDM/JSON").json())
        except Exception as exc:  # noqa: BLE001 - record and continue the audit
            logger.warning(f"{urn}: EDM fetch/parse failed ({exc})")
            continue
        bucket, work = classify(meta, urn, reg, surname)
        stats.counts[bucket] += 1
        if bucket is Bucket.PD_UNPULLED and work is not None:
            stats.unpulled.append((urn, meta.title, meta.year))
            to_pull.append((urn, meta, work))
        elif bucket is Bucket.PD_UNMATCHED:
            stats.unmatched.append((urn, meta.title, meta.is_part_of))
            # ledger, not gate: discovery lands in the committed registry
            discovered = reg.upsert(meta.title, year=meta.year, flags=[WorkFlag.DLIB_DISCOVERED])
            reg.add_source(
                discovered,
                SourceRef(
                    source=Source.DLIB,
                    id=urn,
                    status=SourceStatus.CANDIDATE,
                    year=meta.year,
                    note=f"reconcile discovery (in: {meta.is_part_of})"
                    if meta.is_part_of
                    else "reconcile discovery",
                ),
            )

    if pull_out is not None and to_pull:
        writer = ShardWriter(
            pull_out,
            source=Source.DLIB,
            script="cankar corpus reconcile-dlib --pull",
            args={
                "query_contributor": query_contributor,
                "author": author,
                "min_alpha": min_alpha,
                "n_candidates": len(to_pull),
            },
        )
        with writer:
            for urn, meta, work in to_pull:
                assert meta.text_url is not None  # PD_UNPULLED guarantees it
                raw = session.get(
                    meta.text_url, headers={"Referer": f"{BASE}/details/{urn}"}
                ).content
                text, gate_fail = clean_and_gate(raw, min_alpha=min_alpha, min_chars=min_chars)
                if text is None:
                    stats.pull_gate_failed += 1
                    reg.add_source(
                        work,
                        SourceRef(
                            source=Source.DLIB,
                            id=urn,
                            status=SourceStatus.SKIPPED_QUALITY,
                            year=meta.year,
                            note=gate_fail or "",
                        ),
                    )
                    continue
                writer.write(
                    CorpusDoc(
                        title=work.title,
                        url=f"{BASE}/details/{urn}",
                        text=text,
                        n_chars=len(text),
                        source=Source.DLIB,
                        author=author,
                    )
                )
                reg.add_source(
                    work,
                    SourceRef(
                        source=Source.DLIB, id=urn, status=SourceStatus.INGESTED, year=meta.year
                    ),
                )
                stats.pulled += 1

    reg.save(registry_path)
    write_reconcile_report(stats, report_out)
    for bucket, n in stats.counts.items():
        logger.info(f"  {bucket}: {n}")
    logger.info(f"  pulled: {stats.pulled}, gate-failed: {stats.pull_gate_failed}")
    return stats


def write_reconcile_report(stats: ReconcileStats, out: Path) -> None:
    lines = [
        generated_marker("cankar corpus reconcile-dlib", snapshot=True),
        "# dLib coverage reconciliation",
        "",
        "Every dLib DOC record for the author, classified. PD_UNPULLED is the",
        "recoverable gap; PD_UNMATCHED records are upserted into the registry as",
        "DLIB_DISCOVERED candidates (ledger, not gate). Regenerate with",
        "`cankar corpus reconcile-dlib`.",
        "",
        "| bucket | records |",
        "|---|--:|",
    ]
    lines += [f"| {b} | {n} |" for b, n in stats.counts.items()]
    if stats.unpulled:
        lines += ["", "## PD_UNPULLED (recoverable)", ""]
        lines += [f"- {urn}: {title!r} [{year}]" for urn, title, year in stats.unpulled]
    if stats.unmatched:
        lines += ["", "## PD_UNMATCHED (discovery -> registry candidates)", ""]
        lines += [
            f"- {urn}: {title!r}" + (f" (in: {part})" if part else "")
            for urn, title, part in stats.unmatched
        ]
    write_report(out, lines)
