"""Reconcile bucketing tests - every enumerated class exercised (ADR 0006).

classify() is the pure core of the coverage audit; these tests pin the bucket
boundaries and the ledger-not-gate discovery behavior."""

from cankar.corpus.dlib import EdmRecord
from cankar.corpus.reconcile import (
    Bucket,
    ReconcileStats,
    classify,
    match_work,
    write_reconcile_report,
)
from cankar.corpus.registry import Registry, Source, SourceRef, SourceStatus


def rec(**kw) -> EdmRecord:
    base = dict(
        title="Hlapec Jernej",
        year=1907,
        types=frozenset({"knjige"}),
        langs=frozenset({"sl"}),
        people=frozenset({"Cankar, Ivan"}),
        rights="http://creativecommons.org/publicdomain/mark/1.0/",
        text_url="https://www.dlib.si/stream/X/TEXT",
        is_part_of=None,
    )
    base.update(kw)
    return EdmRecord(**base)


def make_registry(**source_kw) -> Registry:
    reg = Registry("Ivan Cankar")
    work = reg.upsert("Hlapec Jernej", year=1907)
    if source_kw:
        reg.add_source(work, SourceRef(**source_kw))
    return reg


def test_every_bucket_reachable() -> None:
    reg = make_registry()
    cases = [
        (rec(people=frozenset({"Novak, Janez"})), Bucket.NOT_AUTHOR),
        (rec(types=frozenset({"rokopisi"})), Bucket.MANUSCRIPT),
        (rec(langs=frozenset({"de"})), Bucket.NOT_SLOVENE),
        (rec(rights="http://rightsstatements.org/vocab/InC/1.0/"), Bucket.IN_COPYRIGHT),
        (rec(text_url=None), Bucket.PD_NO_TEXT),
        (rec(title="Neznano delo brez vpisa"), Bucket.PD_UNMATCHED),
        (rec(), Bucket.PD_UNPULLED),
    ]
    for meta, expected in cases:
        bucket, _ = classify(meta, "URN:NBN:SI:DOC-X", reg, "cankar")
        assert bucket is expected, f"{meta.title}/{meta.rights} -> {bucket}, wanted {expected}"


def test_ingested_urn_recognized() -> None:
    reg = make_registry(
        source=Source.DLIB, id="URN:NBN:SI:DOC-X", status=SourceStatus.INGESTED, year=1907
    )
    bucket, _ = classify(rec(), "URN:NBN:SI:DOC-X", reg, "cankar")
    assert bucket is Bucket.PD_INGESTED


def test_work_covered_by_wikivir_not_repulled() -> None:
    reg = make_registry(source=Source.WIKIVIR, id="Hlapec Jernej", status=SourceStatus.INGESTED)
    bucket, _ = classify(rec(), "URN:NBN:SI:DOC-Y", reg, "cankar")
    assert bucket is Bucket.PD_COVERED  # transcription beats a second OCR pull


def test_subtitle_relaxation_matches() -> None:
    """dLib titles carry ' : ' subtitles the crawl's exact match missed - the
    class of the 1914-crtice gap."""
    reg = make_registry()
    assert match_work(reg, "Hlapec Jernej : povest") is not None
    assert match_work(reg, "Povsem drugo delo : povest") is None  # no fuzzy overreach


def test_report_lists_gap_and_discovery(tmp_path) -> None:
    stats = ReconcileStats()
    stats.counts[Bucket.PD_UNPULLED] = 1
    stats.unpulled.append(("URN:NBN:SI:DOC-A", "Jure", 1914))
    stats.unmatched.append(("URN:NBN:SI:DOC-B", "Slovan 1914/5", "Slovan"))
    out = tmp_path / "r.md"
    write_reconcile_report(stats, out)
    text = out.read_text()
    assert text.startswith("<!-- GENERATED")
    assert "'Jure' [1914]" in text
    assert "(in: Slovan)" in text
