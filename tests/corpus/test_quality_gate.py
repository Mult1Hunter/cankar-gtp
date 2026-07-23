"""Quality-gate tests - real labeled strays pin the boundary (ADR 0006).

Every fixture is a verbatim (head-truncated) doc that was actually in a literary
shard; the drop_* set is the contamination a stopword probe surfaced, the keep_*
set is the genuine literature that a naive single-scalar floor would amputate
(the poem-amputation failure mode, guarded against here)."""

from pathlib import Path

import pytest

from cankar.corpus.quality_gate import GateVerdict, gate, slovene_ratio, year_ratio

FIX = Path(__file__).parent.parent / "fixtures" / "corpus" / "gate"


def _text(name: str) -> str:
    return (FIX / f"{name}.txt").read_text()


@pytest.mark.parametrize(
    "fixture,expected",
    [
        ("drop_german", GateVerdict.NOT_SLOVENE),  # Askerc study in German + OCR X's
        ("drop_bibliography", GateVerdict.BIBLIOGRAPHY),  # Primoz Trubar works-list
        ("drop_toc", GateVerdict.INDEX_LIST),  # Crtice table of contents
        ("keep_verse_short", GateVerdict.KEPT),  # Angelini - short lyric, verb-sparse
        ("keep_prose_archaic", GateVerdict.KEPT),  # Trdina - 19th-c orthography
        ("keep_ocr_cankar", GateVerdict.KEPT),  # dLib OCR must survive (S1)
        ("keep_foreign_preamble", GateVerdict.KEPT),  # Slovene work w/ Latin+German preamble
    ],
)
def test_gate_on_real_docs(fixture: str, expected: GateVerdict) -> None:
    assert gate(_text(fixture)) == expected


def test_keep_docs_clear_language_floor_with_margin() -> None:
    """Real verse/prose sit well above the language floor - the poem-amputation
    guard. If this margin ever narrows, the floor is miscalibrated."""
    for keep in ("keep_verse_short", "keep_prose_archaic", "keep_ocr_cankar"):
        # true observed floor is archaic prose ~0.09; assert real slack to the
        # 0.05 gate floor, not a razor edge (design-review should-fix)
        assert slovene_ratio(_text(keep)) >= 0.07


def test_bibliography_year_density_separates_from_prose() -> None:
    assert year_ratio(_text("drop_bibliography")) > 0.05
    assert year_ratio(_text("keep_prose_archaic")) < 0.02


def test_empty_is_distinct_from_foreign() -> None:
    # empty must not inflate the not_slovene contamination counter (telemetry honesty)
    assert gate("") == GateVerdict.EMPTY
    assert gate("   \n  ") == GateVerdict.EMPTY
    assert slovene_ratio("") == 0.0
    assert year_ratio("") == 0.0
