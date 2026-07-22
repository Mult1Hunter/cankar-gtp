#!/usr/bin/env python3
"""Crawl dLib.si (National Library digital archive) to fill registry gaps.

Registry-first (ADR 0004): only works matched by title to the author's registry
are ingested; whole-journal-issue records and other unmatched DOC items go to a
triage report, never silently dropped. Manuscripts are recorded and skipped.
Wikivir-ingested works are recorded as dLib `candidate` without fetching text
(hand transcription beats OCR).

Terms-of-use compliance (dlib.si/Help.aspx, checked 2026-07): only records
carrying dLib's public-domain rights mark are ingested (everything else is
recorded as skipped-rights); "Digitalna knjiznica Slovenije - dLib.si" is
credited as source in README "Data sources". Polite crawl: 0.5s delay, UA
with contact.

Verified dLib API surface (2026-07):
- results HTML pages carry URN:NBN:SI:<TYPE>-<ID> identifiers (100/page)
- per-URN EDM JSON at /URN.../EDM/JSON (title, year, language, types, rights,
  stream links); rights PD marker: creativecommons.org/publicdomain/mark
- TEXT streams need a session cookie (visit a details page first) + referer,
  and are usually windows-1250 encoded (cankar.ocr_clean handles both)

CLI: `cankar corpus crawl-dlib` (cankar.corpus.cli). ADR 0007: importable module,
no standalone script.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from cankar.core.http import PoliteSession
from cankar.core.manifest import ShardManifest, git_sha, sha256_of, utc_now_iso, write_manifest
from cankar.core.paths import dataset_manifest
from cankar.core.schema import CorpusDoc
from cankar.corpus.ocr_clean import decode_stream, ocr_clean
from cankar.corpus.registry import Registry, Source, SourceRef, SourceStatus

logger = logging.getLogger(__name__)

BASE = "https://www.dlib.si"
EARLY_NOISE_MAX = 10  # ocr_clean early_noise gate; calibrated on the first dLib audit


@dataclass
class DlibStats:
    """Typed crawl outcome counters (ADR 0008)."""

    ingested: int = 0
    candidate_covered: int = 0
    manuscript: int = 0
    not_pd: int = 0
    not_slovene: int = 0
    no_text: int = 0
    unmatched: int = 0
    not_author: int = 0
    low_quality: int = 0
    duplicate_edition: int = 0
    triage: list[str] = field(default_factory=list)


URN_RE = re.compile(r"URN:NBN:SI:[A-Z]+-[A-Z0-9]+")
PD_MARKER = "publicdomain"
YEAR_RE = re.compile(r"\d{4}")


def as_list(v: object) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def txt(v: object) -> str | None:
    """EDM values appear as plain strings or {'#text': ..., '@xml:lang': ...}."""
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        return v.get("#text")
    return None


def enumerate_urns(session: PoliteSession, contributor: str) -> list[str]:
    """All URNs from the paged results listing."""
    urns: list[str] = []
    seen: set[str] = set()
    page = 1
    while True:
        q = quote(f"'contributor={contributor}'")
        url = f"{BASE}/results/?query={q}&pageSize=100&page={page}"
        found = URN_RE.findall(session.get(url).text)
        new = [u for u in dict.fromkeys(found) if u not in seen]
        if not new:
            return urns
        seen.update(new)
        urns += new
        page += 1


@dataclass(frozen=True)
class EdmRecord:
    """Parsed dLib EDM metadata for one URN (ADR 0008: typed, immutable)."""

    title: str
    year: int | None
    types: frozenset[str]
    langs: frozenset[str]
    people: frozenset[str]
    rights: str
    text_url: str | None
    is_part_of: str | None


def parse_edm(data: dict) -> EdmRecord:
    rdf = data.get("edm:RDF", {})
    cho = rdf.get("edm:ProvidedCHO", {})
    agg = rdf.get("ore:Aggregation", {})

    title = (txt(as_list(cho.get("dc:title"))[0]) or "").rstrip("|").strip()
    year_m = YEAR_RE.search(str(txt(as_list(cho.get("dcterms:issued"))[0]) or ""))
    types = {(txt(t) or "").casefold() for t in as_list(cho.get("dc:type"))}
    langs = {(txt(v) or "").casefold() for v in as_list(cho.get("dc:language"))}
    people = {
        (txt(p) or "") for key in ("dc:contributor", "dc:creator") for p in as_list(cho.get(key))
    }
    rights = (as_list(agg.get("edm:rights"))[0] or {}).get("@rdf:resource", "") if agg else ""
    text_url = next(
        (
            wr.get("@rdf:about")
            for wr in as_list(rdf.get("edm:WebResource"))
            if str(wr.get("@rdf:about", "")).endswith("/TEXT")
        ),
        None,
    )
    is_part_of = next(
        (txt(p) for p in as_list(cho.get("dcterms:isPartOf")) if txt(p)),
        None,
    )
    return EdmRecord(
        title=title,
        year=int(year_m.group(0)) if year_m else None,
        types=frozenset(types),
        langs=frozenset(langs),
        people=frozenset(people),
        rights=rights,
        text_url=text_url,
        is_part_of=is_part_of,
    )


def crawl(
    *,
    query_contributor: str,
    author: str,
    registry_path: Path,
    out: Path,
    triage: Path | None = None,
    min_alpha: float = 0.84,
    min_chars: int = 400,
) -> DlibStats:
    triage_path = triage or out.parent / f"{out.stem}-triage.md"

    reg = Registry.load(registry_path, author)
    surname = query_contributor.split(",")[0].strip().casefold()

    session = PoliteSession()
    # session bootstrap: streams 302 to the details page without cookies
    bootstrap_q = quote(f"'contributor={query_contributor}'")
    session.get(f"{BASE}/results/?query={bootstrap_q}&pageSize=25")

    urns = enumerate_urns(session, query_contributor)
    doc_urns = [u for u in urns if u.split(":")[-1].startswith("DOC-")]
    logger.info(f"{len(urns)} URNs listed, {len(doc_urns)} DOC records")

    stats = DlibStats()
    ingested_work_ids: set[str] = set()
    n_docs = n_chars = n_words = 0

    out.parent.mkdir(parents=True, exist_ok=True)
    out_f = out.open("w", encoding="utf-8")

    for i, urn in enumerate(doc_urns, 1):
        if i % 25 == 0:
            logger.info(f"  metadata {i}/{len(doc_urns)}")
        try:
            meta = parse_edm(session.get(f"{BASE}/{urn}/EDM/JSON").json())
        except Exception as exc:  # noqa: BLE001 - record and continue the crawl
            stats.triage.append(f"- {urn}: EDM fetch/parse failed ({exc})")
            continue

        if not any(surname in p.casefold() for p in meta.people):
            stats.not_author += 1
            continue
        if "rokopisi" in meta.types or "rokopis" in meta.types:
            stats.manuscript += 1
            work = reg.find(meta.title)
            if work:
                reg.add_source(
                    work,
                    SourceRef(
                        source=Source.DLIB,
                        id=urn,
                        status=SourceStatus.SKIPPED_MANUSCRIPT,
                        year=meta.year,
                    ),
                )
            continue
        if meta.langs and "sl" not in meta.langs:
            stats.not_slovene += 1
            continue
        if PD_MARKER not in meta.rights:
            stats.not_pd += 1
            work = reg.find(meta.title)
            if work:
                reg.add_source(
                    work,
                    SourceRef(
                        source=Source.DLIB,
                        id=urn,
                        status=SourceStatus.SKIPPED_RIGHTS,
                        year=meta.year,
                    ),
                )
            continue

        work = reg.find(meta.title)
        if work is None:
            stats.unmatched += 1
            part = f" (in: {meta.is_part_of})" if meta.is_part_of else ""
            stats.triage.append(
                f"- {urn}: no registry match for {meta.title!r} [{meta.year}]{part}"
            )
            continue

        covered = any(
            s.source is Source.WIKIVIR and s.status is SourceStatus.INGESTED for s in work.sources
        )
        if covered:
            stats.candidate_covered += 1
            reg.add_source(
                work,
                SourceRef(
                    source=Source.DLIB,
                    id=urn,
                    status=SourceStatus.CANDIDATE,
                    year=meta.year,
                    note="wikivir transcription preferred",
                ),
            )
            continue
        if work.work_id in ingested_work_ids:
            stats.duplicate_edition += 1
            reg.add_source(
                work,
                SourceRef(
                    source=Source.DLIB,
                    id=urn,
                    status=SourceStatus.CANDIDATE,
                    year=meta.year,
                    note="another edition already ingested",
                ),
            )
            continue
        if not meta.text_url:
            stats.no_text += 1
            reg.add_source(
                work,
                SourceRef(
                    source=Source.DLIB,
                    id=urn,
                    status=SourceStatus.CANDIDATE,
                    year=meta.year,
                    note="no TEXT stream",
                ),
            )
            continue

        # the gap-filler: fetch + clean + gate
        raw = session.get(meta.text_url, headers={"Referer": f"{BASE}/details/{urn}"}).content
        text, metrics = ocr_clean(decode_stream(raw))
        if metrics["early_noise"] > EARLY_NOISE_MAX:
            # severely corrupted opening (mangled decorated title page) -
            # corpus-qa finding: these docs are unreadable, exclude wholesale
            stats.low_quality += 1
            reg.add_source(
                work,
                SourceRef(
                    source=Source.DLIB,
                    id=urn,
                    status=SourceStatus.SKIPPED_QUALITY,
                    year=meta.year,
                    note=f"severe opening corruption (early_noise={metrics['early_noise']})",
                ),
            )
            continue
        if metrics["alpha_ratio"] < min_alpha or metrics["n_chars"] < min_chars:
            stats.low_quality += 1
            reg.add_source(
                work,
                SourceRef(
                    source=Source.DLIB,
                    id=urn,
                    status=SourceStatus.SKIPPED_QUALITY,
                    year=meta.year,
                    note=f"alpha={metrics['alpha_ratio']} chars={metrics['n_chars']}",
                ),
            )
            continue

        doc = CorpusDoc(
            title=work.title,
            url=f"{BASE}/details/{urn}",
            text=text,
            n_chars=len(text),
            source=Source.DLIB,
            author=author,
        )
        out_f.write(doc.model_dump_json() + "\n")
        reg.add_source(
            work,
            SourceRef(source=Source.DLIB, id=urn, status=SourceStatus.INGESTED, year=meta.year),
        )
        ingested_work_ids.add(work.work_id)
        stats.ingested += 1
        n_docs += 1
        n_chars += len(text)
        n_words += len(text.split())

    out_f.close()
    reg.save(registry_path)

    triage_path.parent.mkdir(parents=True, exist_ok=True)
    triage_path.write_text(
        "# dLib triage - unmatched/failed records (regenerated by crawl_dlib.py)\n\n"
        + "\n".join(stats.triage)
        + "\n"
    )

    manifest = ShardManifest(
        source=Source.DLIB,
        script="cankar corpus crawl-dlib",
        git_sha=git_sha(),
        retrieved_at=utc_now_iso(),
        args={
            "query_contributor": query_contributor,
            "author": author,
            "min_alpha": min_alpha,
        },
        n_docs=n_docs,
        n_chars=n_chars,
        n_words=n_words,
        sha256=sha256_of(out),
        expected_band_words=None,
    )
    write_manifest(manifest, dataset_manifest("corpus", out.stem))

    logger.info(f"\nwrote {out} - {n_docs} docs, {n_words:,} words")
    for k, v in vars(stats).items():
        logger.info(f"  {k}: {v}")
    logger.info(f"  triage report: {triage_path} ({len(stats.triage)} lines)")
    return stats
