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

Usage:
    uv run scripts/crawl_dlib.py \
        --query-contributor "Cankar, Ivan" \
        --author "Ivan Cankar" \
        --registry registry/cankar.jsonl \
        --out data/corpus/dlib-cankar.jsonl
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests

from cankar.core.manifest import ShardManifest, git_sha, sha256_of, utc_now_iso, write_manifest
from cankar.core.schema import CorpusDoc
from cankar.corpus.ocr_clean import decode_stream, ocr_clean
from cankar.corpus.registry import Registry, SourceRef

BASE = "https://www.dlib.si"
UA = "CankarGTP-corpus-builder/0.1 (+https://nextgen-solutions.xyz; educational project)"
SLEEP = 0.5  # polite delay, seconds
URN_RE = re.compile(r"URN:NBN:SI:[A-Z]+-[A-Z0-9]+")
PD_MARKER = "publicdomain"
YEAR_RE = re.compile(r"\d{4}")


def polite_get(session: requests.Session, url: str, **kw) -> requests.Response:
    resp = session.get(url, timeout=60, **kw)
    resp.raise_for_status()
    time.sleep(SLEEP)
    return resp


def as_list(v) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def txt(v) -> str | None:
    """EDM values appear as plain strings or {'#text': ..., '@xml:lang': ...}."""
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        return v.get("#text")
    return None


def enumerate_urns(session: requests.Session, contributor: str) -> list[str]:
    """All URNs from the paged results listing."""
    urns: list[str] = []
    seen: set[str] = set()
    page = 1
    while True:
        q = quote(f"'contributor={contributor}'")
        url = f"{BASE}/results/?query={q}&pageSize=100&page={page}"
        found = URN_RE.findall(polite_get(session, url).text)
        new = [u for u in dict.fromkeys(found) if u not in seen]
        if not new:
            return urns
        seen.update(new)
        urns += new
        page += 1


def parse_edm(data: dict) -> dict:
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
    return {
        "title": title,
        "year": int(year_m.group(0)) if year_m else None,
        "types": types,
        "langs": langs,
        "people": people,
        "rights": rights,
        "text_url": text_url,
        "is_part_of": is_part_of,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--query-contributor", required=True, help="dLib contributor, 'Surname, Name'")
    ap.add_argument("--author", required=True, help="canonical author name for the registry")
    ap.add_argument("--registry", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--triage", type=Path, default=None, help="triage report path")
    ap.add_argument("--min-alpha", type=float, default=0.84, help="doc OCR quality gate")
    ap.add_argument("--min-chars", type=int, default=400)
    args = ap.parse_args()
    triage_path = args.triage or args.out.parent / f"{args.out.stem}-triage.md"

    reg = Registry.load(args.registry, args.author)
    surname = args.query_contributor.split(",")[0].strip().casefold()

    session = requests.Session()
    session.headers["User-Agent"] = UA
    # session bootstrap: streams 302 to the details page without cookies
    bootstrap_q = quote(f"'contributor={args.query_contributor}'")
    polite_get(session, f"{BASE}/results/?query={bootstrap_q}&pageSize=25")

    urns = enumerate_urns(session, args.query_contributor)
    doc_urns = [u for u in urns if u.split(":")[-1].startswith("DOC-")]
    print(f"{len(urns)} URNs listed, {len(doc_urns)} DOC records", file=sys.stderr)

    stats = {
        "ingested": 0,
        "candidate_covered": 0,
        "manuscript": 0,
        "not_pd": 0,
        "not_slovene": 0,
        "no_text": 0,
        "unmatched": 0,
        "not_author": 0,
        "low_quality": 0,
        "duplicate_edition": 0,
    }
    triage: list[str] = []
    ingested_work_ids: set[str] = set()
    n_docs = n_chars = n_words = 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    out_f = args.out.open("w", encoding="utf-8")

    for i, urn in enumerate(doc_urns, 1):
        if i % 25 == 0:
            print(f"  metadata {i}/{len(doc_urns)}", file=sys.stderr)
        try:
            meta = parse_edm(polite_get(session, f"{BASE}/{urn}/EDM/JSON").json())
        except Exception as exc:  # noqa: BLE001 - record and continue the crawl
            triage.append(f"- {urn}: EDM fetch/parse failed ({exc})")
            continue

        if not any(surname in p.casefold() for p in meta["people"]):
            stats["not_author"] += 1
            continue
        if "rokopisi" in meta["types"] or "rokopis" in meta["types"]:
            stats["manuscript"] += 1
            work = reg.find(meta["title"])
            if work:
                reg.add_source(
                    work,
                    SourceRef(
                        source="dlib", id=urn, status="skipped-manuscript", year=meta["year"]
                    ),
                )
            continue
        if meta["langs"] and "sl" not in meta["langs"]:
            stats["not_slovene"] += 1
            continue
        if PD_MARKER not in meta["rights"]:
            stats["not_pd"] += 1
            work = reg.find(meta["title"])
            if work:
                reg.add_source(
                    work,
                    SourceRef(source="dlib", id=urn, status="skipped-rights", year=meta["year"]),
                )
            continue

        work = reg.find(meta["title"])
        if work is None:
            stats["unmatched"] += 1
            part = f" (in: {meta['is_part_of']})" if meta["is_part_of"] else ""
            triage.append(
                f"- {urn}: no registry match for {meta['title']!r} [{meta['year']}]{part}"
            )
            continue

        covered = any(s.source == "wikivir" and s.status == "ingested" for s in work.sources)
        if covered:
            stats["candidate_covered"] += 1
            reg.add_source(
                work,
                SourceRef(
                    source="dlib",
                    id=urn,
                    status="candidate",
                    year=meta["year"],
                    note="wikivir transcription preferred",
                ),
            )
            continue
        if work.work_id in ingested_work_ids:
            stats["duplicate_edition"] += 1
            reg.add_source(
                work,
                SourceRef(
                    source="dlib",
                    id=urn,
                    status="candidate",
                    year=meta["year"],
                    note="another edition already ingested",
                ),
            )
            continue
        if not meta["text_url"]:
            stats["no_text"] += 1
            reg.add_source(
                work,
                SourceRef(
                    source="dlib",
                    id=urn,
                    status="candidate",
                    year=meta["year"],
                    note="no TEXT stream",
                ),
            )
            continue

        # the gap-filler: fetch + clean + gate
        raw = polite_get(
            session, meta["text_url"], headers={"Referer": f"{BASE}/details/{urn}"}
        ).content
        text, metrics = ocr_clean(decode_stream(raw))
        if metrics["early_noise"] > 10:
            # severely corrupted opening (mangled decorated title page) -
            # corpus-qa finding: these docs are unreadable, exclude wholesale
            stats["low_quality"] += 1
            reg.add_source(
                work,
                SourceRef(
                    source="dlib",
                    id=urn,
                    status="skipped-quality",
                    year=meta["year"],
                    note=f"severe opening corruption (early_noise={metrics['early_noise']})",
                ),
            )
            continue
        if metrics["alpha_ratio"] < args.min_alpha or metrics["n_chars"] < args.min_chars:
            stats["low_quality"] += 1
            reg.add_source(
                work,
                SourceRef(
                    source="dlib",
                    id=urn,
                    status="skipped-quality",
                    year=meta["year"],
                    note=f"alpha={metrics['alpha_ratio']} chars={metrics['n_chars']}",
                ),
            )
            continue

        doc = CorpusDoc(
            title=work.title,
            url=f"{BASE}/details/{urn}",
            text=text,
            n_chars=len(text),
            source="dlib",
            author=args.author,
        )
        out_f.write(doc.model_dump_json() + "\n")
        reg.add_source(work, SourceRef(source="dlib", id=urn, status="ingested", year=meta["year"]))
        ingested_work_ids.add(work.work_id)
        stats["ingested"] += 1
        n_docs += 1
        n_chars += len(text)
        n_words += len(text.split())

    out_f.close()
    reg.save(args.registry)

    triage_path.parent.mkdir(parents=True, exist_ok=True)
    triage_path.write_text(
        "# dLib triage - unmatched/failed records (regenerated by crawl_dlib.py)\n\n"
        + "\n".join(triage)
        + "\n"
    )

    manifest = ShardManifest(
        source="dlib",
        script="scripts/corpus/crawl_dlib.py",
        git_sha=git_sha(),
        retrieved_at=utc_now_iso(),
        args={
            "query_contributor": args.query_contributor,
            "author": args.author,
            "min_alpha": args.min_alpha,
        },
        n_docs=n_docs,
        n_chars=n_chars,
        n_words=n_words,
        sha256=sha256_of(args.out),
        expected_band_words=None,
    )
    write_manifest(args.out, manifest)

    print(f"\nwrote {args.out} - {n_docs} docs, {n_words:,} words", file=sys.stderr)
    for k, v in stats.items():
        print(f"  {k}: {v}", file=sys.stderr)
    print(f"  triage report: {triage_path} ({len(triage)} lines)", file=sys.stderr)


if __name__ == "__main__":
    main()
