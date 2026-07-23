"""dLib coverage reconciliation - which PD records with usable text are NOT in
the corpus?

Supersedes the retired registry-gated `crawl-dlib` flow (ADR 0004 amendment 2:
the gate was the bug class - a record whose title failed registry matching died
in a gitignored triage file, losing recoverable works whose dLib titles are
journal-issue titles). Principles:

- every DOC record lands in exactly one enumerated bucket (ADR 0006), and every
  bucket that matched a registry work leaves a SourceRef - the ledger records
  what dLib has even when nothing is pulled;
- unmatched-but-PD records are upserted into the committed registry as
  DLIB_DISCOVERED candidates instead of dying in triage;
- title matching tries the full title, then each `[:;|]`-separated segment in
  order, exact-on-normalized (no fuzzy matching). Head-first order is
  calibrated on the discovery-loop-back incident: 27 verbatim-title upserts
  ('Hlapci| drama v petih aktih', 'Crtice; Majska noc', ...) created parallel
  identities whose heads name the canonical work, and the pull re-ingested 19
  already-covered editions before the design review caught it;
- `--pull` ingests the PD_UNPULLED bucket through the shared clean_and_gate
  sequence, one edition per work, into its own shard + manifest.

CLI: `cankar corpus reconcile-dlib` (cankar.corpus.cli).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from urllib.parse import quote

from cankar.core.http import PoliteSession
from cankar.core.reports import generated_marker, write_report
from cankar.core.schema import CorpusDoc
from cankar.corpus.dlib import (
    BASE,
    DEFAULT_MIN_ALPHA,
    DEFAULT_MIN_CHARS,
    PD_MARKER,
    EdmRecord,
    clean_and_gate,
    enumerate_urns,
    is_by_author,
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

_SEP_RE = re.compile(r"\s*[:;|]\s*")  # dLib title separators (subtitle, attribution, series)


class Bucket(StrEnum):
    """Every dLib DOC record lands in exactly one class (enumerated: ADR 0006)."""

    NOT_AUTHOR = "not_author"  # authorship check failed (creators/attribution/memorial)
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
    pull_duplicate_edition: int = 0


def match_work(reg: Registry, title: str) -> WorkRecord | None:
    """Full title first, then each separator segment head-first - every strategy
    exact-on-normalized (no fuzzy containment; name-collision safety). Head-first
    is the calibrated order: in all 27 real loop-back cases the head named the
    canonical work ('Na klancu; Spisal Ivan Cankar', 'Hlapci| drama ...')."""
    work = reg.find(title)
    if work is not None:
        return work
    for seg in _SEP_RE.split(title):
        if seg:
            work = reg.find(seg)
            if work is not None:
                return work
    return None


def classify(
    meta: EdmRecord, urn: str, reg: Registry, query_contributor: str
) -> tuple[Bucket, WorkRecord | None]:
    """Pure bucketing of one record - the testable core of the audit."""
    if not is_by_author(meta, query_contributor):
        return Bucket.NOT_AUTHOR, None
    if "rokopisi" in meta.types or "rokopis" in meta.types:
        return Bucket.MANUSCRIPT, match_work(reg, meta.title)
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


# buckets that leave a ledger SourceRef when a registry work matched
_LEDGER_STATUS: dict[Bucket, tuple[SourceStatus, str]] = {
    Bucket.MANUSCRIPT: (SourceStatus.SKIPPED_MANUSCRIPT, ""),
    Bucket.IN_COPYRIGHT: (SourceStatus.SKIPPED_RIGHTS, ""),
    Bucket.PD_NO_TEXT: (SourceStatus.CANDIDATE, "no TEXT stream"),
    Bucket.PD_COVERED: (SourceStatus.CANDIDATE, "covered by ingested source"),
}


def reconcile(
    *,
    query_contributor: str,
    author: str,
    registry_path: Path,
    report_out: Path,
    pull_out: Path | None = None,
    min_alpha: float = DEFAULT_MIN_ALPHA,
    min_chars: int = DEFAULT_MIN_CHARS,
) -> ReconcileStats:
    """Audit dLib coverage; with pull_out set, ingest the PD_UNPULLED bucket."""
    reg = Registry.load(registry_path, author)
    stats = ReconcileStats()

    session = PoliteSession()
    # session bootstrap: TEXT streams 302 without cookies
    bootstrap_query = quote(f"'contributor={query_contributor}'")
    session.get(f"{BASE}/results/?query={bootstrap_query}&pageSize=25")

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
        bucket, work = classify(meta, urn, reg, query_contributor)
        stats.counts[bucket] += 1
        if bucket in _LEDGER_STATUS and work is not None:
            status, note = _LEDGER_STATUS[bucket]
            reg.add_source(
                work,
                SourceRef(source=Source.DLIB, id=urn, status=status, year=meta.year, note=note),
            )
        elif bucket is Bucket.PD_UNPULLED and work is not None:
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
        pulled_work_ids: set[str] = set()
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
                if work.work_id in pulled_work_ids:
                    stats.pull_duplicate_edition += 1
                    reg.add_source(
                        work,
                        SourceRef(
                            source=Source.DLIB,
                            id=urn,
                            status=SourceStatus.CANDIDATE,
                            year=meta.year,
                            note="another edition already pulled",
                        ),
                    )
                    continue
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
                pulled_work_ids.add(work.work_id)
                stats.pulled += 1

    reg.save(registry_path)
    write_reconcile_report(stats, report_out)
    for bucket, n in stats.counts.items():
        logger.info(f"  {bucket}: {n}")
    logger.info(
        f"  pulled: {stats.pulled}, gate-failed: {stats.pull_gate_failed}, "
        f"duplicate-edition: {stats.pull_duplicate_edition}"
    )
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
