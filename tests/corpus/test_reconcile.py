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
        creators=frozenset({"Cankar, Ivan"}),
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


def test_real_contamination_rejected() -> None:
    """The three real records the corpus-qa audit caught in the first gap-fill
    pull (ADR 0006: real labeled examples pin the boundary). Metadata is
    verbatim from dLib EDM JSON, 2026-07."""
    reg = make_registry()
    gregorcic = rec(  # URN:NBN:SI:DOC-IWN6782U - creators decide
        title="Izbrane pesmi| za stoletnico pesnikovega rojstva 1844-1944",
        creators=frozenset({"Gregorčič, Simon"}),
        people=frozenset({"Gregorčič, Simon", "Cankar, Ivan"}),
    )
    askerc = rec(  # URN:NBN:SI:DOC-AYWISGCW - no creator; title attribution
        title="Lirske in epske poezije; Napisal A. Aškerc",
        creators=frozenset(),
        people=frozenset({"Cankar, Ivan"}),
    )
    memorial = rec(  # URN:NBN:SI:DOC-CRK1R8WE - no creator; memorial title
        title="Spominu Ivana Cankarja| (1876-1918)",
        creators=frozenset(),
        people=frozenset({"Cankar, Ivan", "Šlebinger, Janko"}),
    )
    for meta in (gregorcic, askerc, memorial):
        bucket, _ = classify(meta, "URN:NBN:SI:DOC-X", reg, "cankar")
        assert bucket is Bucket.NOT_AUTHOR, f"{meta.title!r} must be rejected"


def test_journal_record_without_creator_still_accepted() -> None:
    """Legit Cankar journal publications often lack dc:creator - the people
    fallback must keep accepting them (no attribution phrase, no memorial)."""
    reg = make_registry()
    meta = rec(creators=frozenset(), people=frozenset({"Cankar, Ivan"}))
    bucket, _ = classify(meta, "URN:NBN:SI:DOC-X", reg, "cankar")
    assert bucket is Bucket.PD_UNPULLED


def test_own_attribution_not_rejected() -> None:
    """'Napisal Ivan Cankar' in a title names the author himself - keep."""
    reg = make_registry()
    meta = rec(
        title="Hlapec Jernej : povest; Napisal Ivan Cankar",
        creators=frozenset(),
        people=frozenset({"Cankar, Ivan"}),
    )
    bucket, _ = classify(meta, "URN:NBN:SI:DOC-X", reg, "cankar")
    assert bucket is Bucket.PD_UNPULLED


def test_every_bucket_reachable() -> None:
    reg = make_registry()
    cases = [
        (
            rec(people=frozenset({"Novak, Janez"}), creators=frozenset({"Novak, Janez"})),
            Bucket.NOT_AUTHOR,
        ),
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
