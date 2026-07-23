"""Slice classification, metrics, and report determinism."""

from __future__ import annotations

from pathlib import Path

import pytest

from cankar.core.paths import tokenizer_probes_config
from cankar.tokenizer import evaluate, train
from cankar.tokenizer.evaluate import Slice, classify

FIXTURE = Path(__file__).parent.parent / "fixtures" / "tokenizer" / "mini-corpus.jsonl"


@pytest.fixture(scope="module")
def enc():
    return train.train_encoding(FIXTURE, 300)


def test_classify_slice_key() -> None:
    """The slice key needs source AND author (critique MF-3): Cankar is an
    author inside wikivir/dlib, never a source; comma-joined multi-author
    values are literary, not phantom authors."""
    assert classify("wikivir", "Ivan Cankar") is Slice.CANKAR
    assert classify("dlib", "Ivan Cankar") is Slice.CANKAR
    assert classify("wikipedia", None) is Slice.WIKIPEDIA
    assert classify("wikivir", "Anton Aškerc") is Slice.LITERARY
    assert classify("wikivir", "Josip Jurčič, Janko Kersnik") is Slice.LITERARY
    assert classify("dlib", "Dragotin Kette") is Slice.LITERARY


def test_evaluate_slices_and_notes(enc) -> None:
    evals, notes = evaluate.evaluate_candidates(FIXTURE, {"v300": enc})
    (ev,) = evals
    assert ev.slices[Slice.CANKAR].n_docs == 3  # Na klancu + Hlapci + Ada
    assert ev.slices[Slice.WIKIPEDIA].n_docs == 2
    assert ev.slices[Slice.LITERARY].n_docs == 4
    for sl in Slice:
        st = ev.slices[sl]
        assert st.n_tokens > 0 and st.tokens_per_word > 0
        assert len(st.per_doc_fertility) == st.n_docs
        assert st.fertility_p95 >= sorted(st.per_doc_fertility)[0]
    assert notes.n_docs == 9
    assert notes.docs_with_soft_hyphen == 1  # the OCR fixture doc
    assert notes.docs_with_tabs == 1


def test_vocab_param_rows_match_critique_table() -> None:
    """Pin the MF-2 formula to the architect critique's computed numbers:
    d6/V16384 = 42.1M total at 75% vocab share (over the 30M budget)."""
    rows = {r["depth"]: r for r in evaluate.vocab_param_rows(16384)}
    assert rows[6]["dim"] == 384
    assert rows[6]["total_m"] == pytest.approx(42.1, abs=0.1)
    assert rows[6]["share"] == pytest.approx(0.75, abs=0.01)
    rows4k = {r["depth"]: r for r in evaluate.vocab_param_rows(4096)}
    assert rows4k[6]["total_m"] == pytest.approx(18.5, abs=0.1)


def test_probes_config_loads_and_segments(enc) -> None:
    probes = evaluate.load_probes(tokenizer_probes_config())
    assert {"case_paradigm", "archaic", "elision"} <= set(probes)
    seg = evaluate.segment(enc, "solnce")
    assert seg.replace("|", "") == "solnce"


def test_report_is_deterministic(enc, tmp_path: Path) -> None:
    """Byte-identical regeneration (report drift rule, ADR 0007)."""
    evals, notes = evaluate.evaluate_candidates(FIXTURE, {"v300": enc})
    probes = evaluate.load_probes(tokenizer_probes_config())
    a = evaluate.write_eval_report(
        tmp_path / "a.md", "sha", evals, notes, probes, {"v300": enc}, None, None
    )
    b = evaluate.write_eval_report(
        tmp_path / "b.md", "sha", evals, notes, probes, {"v300": enc}, None, None
    )
    assert a.read_bytes() == b.read_bytes()
    sel = evaluate.write_eval_report(
        tmp_path / "c.md", "sha", evals, notes, probes, {"v300": enc}, "v300", "test reason"
    )
    assert "Selected candidate: **v300**. test reason" in sel.read_text()
