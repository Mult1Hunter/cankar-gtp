"""Chunking invariants on the fixture corpus (ADR 0012, critique MF-1..MF-6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cankar.core.errors import CankarError
from cankar.core.schema import ChunkDoc
from cankar.tokenizer import chunk, train
from cankar.tokenizer.chunk import ChunkLevel

FIXTURE = Path(__file__).parent.parent / "fixtures" / "tokenizer" / "mini-corpus.jsonl"


@pytest.fixture(scope="module")
def enc():
    return train.train_encoding(FIXTURE, 300)


def _n(enc, text: str) -> int:
    return len(enc.encode_ordinary(text))


def _texts(pairs: list[tuple[str, int]]) -> list[str]:
    return [t for t, _ in pairs]


def test_budget_boundary_semantics(enc) -> None:
    """MF-4: budget is <= (a chunk of exactly budget tokens passes through);
    one token less forces a split."""
    text = next(train.iter_corpus_texts(FIXTURE))
    n = _n(enc, text)
    pairs, level, seam = chunk.chunk_text(text, enc, budget=n)
    assert _texts(pairs) == [text] and level is ChunkLevel.PASS_THROUGH and seam == 0
    pairs, level, _ = chunk.chunk_text(text, enc, budget=n - 1)
    assert len(pairs) > 1 and level > ChunkLevel.PASS_THROUGH


@pytest.mark.parametrize("budget", [16, 32, 64])
def test_reconstruction_all_fixture_docs(enc, budget: int) -> None:
    """MF-1: chunks concatenate byte-exact; every reported n_tokens is the
    re-encoded count and <= budget."""
    for text in train.iter_corpus_texts(FIXTURE):
        pairs, _, _ = chunk.chunk_text(text, enc, budget)
        assert "".join(_texts(pairs)) == text
        for t, n in pairs:
            assert n == _n(enc, t) <= budget


def test_real_paragraph_doc_splits_at_paragraph_level(enc) -> None:
    """MF-5: the real Ada excerpt (committed fixture, two paragraphs) splits
    at the paragraph rung - the rung 15.6k real docs use."""
    doc = [json.loads(line) for line in FIXTURE.open(encoding="utf-8")][-1]
    assert "\n\n" in doc["text"] and doc["author"] == "Ivan Cankar"
    budget = _n(enc, doc["text"]) - 1  # force exactly one split decision
    pairs, level, _ = chunk.chunk_text(doc["text"], enc, budget)
    assert level is ChunkLevel.PARAGRAPH
    assert "".join(_texts(pairs)) == doc["text"]


def test_ladder_recurses_per_piece(enc) -> None:
    """MF-2: a structured doc with one over-budget paragraph keeps its other
    paragraphs paragraph-grained - the first chunk is exactly the intact
    short paragraph (design-review: 'in' was too weak to catch regressions)."""
    short = "Kratek odstavek."
    mega = ("beseda " * 200).strip()
    text = f"{short}\n\n{mega}\n\n{short}"
    pairs, level, _ = chunk.chunk_text(text, enc, budget=24)
    texts = _texts(pairs)
    assert "".join(texts) == text
    assert level > ChunkLevel.PARAGRAPH  # mega paragraph descended
    assert texts[0] == f"{short}\n\n"  # intact paragraph piece, not a hard cut


def test_sentence_level_per_piece(enc) -> None:
    """Level-2 per-piece path: one over-budget sentence among intact ones -
    the intact sentences survive as their own pieces."""
    first = "Prva poved. "
    mega = "dolga " * 120
    text = f"{first}{mega.strip()}. Zadnja poved."
    budget = _n(enc, first) + 8
    pairs, level, _ = chunk.chunk_text(text, enc, budget=budget)
    texts = _texts(pairs)
    assert "".join(texts) == text
    assert level is ChunkLevel.HARD  # the mega sentence had no finer separator
    assert texts[0].startswith(first)  # intact first sentence leads its chunk


def test_no_paragraph_doc_descends(enc) -> None:
    """No-para docs (3,332 in the real corpus) go line -> sentence -> hard."""
    text = "Prva poved brez odstavkov. Druga poved sledi takoj! Tretja se konča?"
    pairs, _, _ = chunk.chunk_text(text, enc, budget=12)
    assert "".join(_texts(pairs)) == text
    assert all(n <= 12 for _, n in pairs)


def test_hard_split_multibyte_safety(enc) -> None:
    """MF-3: hard splits over multi-byte chars never emit U+FFFD or split
    a UTF-8 sequence - strict decode with back-off."""
    text = "čžšđć" * 100  # no spaces, no sentences: forces the hard rung
    pairs, level, _ = chunk.chunk_text(text, enc, budget=16)
    assert "".join(_texts(pairs)) == text
    assert level is ChunkLevel.HARD
    for t, n in pairs:
        assert "�" not in t
        assert n <= 16


def test_duplicate_url_raises(enc, tmp_path: Path) -> None:
    """MF-6: url is the holdout key; duplicates abort the run."""
    doc = {"title": "t", "url": "u", "text": "besedilo.", "source": "wikivir", "author": None}
    p = tmp_path / "dup.jsonl"
    p.write_text(json.dumps(doc) + "\n" + json.dumps(doc) + "\n", encoding="utf-8")
    with pytest.raises(CankarError, match="duplicate url"):
        list(chunk.chunk_corpus(p, enc, 64))


def test_chunk_corpus_spans_and_stats(enc, tmp_path: Path) -> None:
    """Spans are adjacent, cover the doc, and text == doc.text[start:end]."""
    out = tmp_path / "chunks.jsonl"
    stats = chunk.run_chunking(FIXTURE, enc, 32, out)
    assert stats.n_docs == 9
    docs = {json.loads(line)["url"]: json.loads(line)["text"] for line in FIXTURE.open()}
    by_url: dict[str, list[ChunkDoc]] = {}
    for line in out.open(encoding="utf-8"):
        c = ChunkDoc.model_validate_json(line)
        by_url.setdefault(c.url, []).append(c)
    assert len(by_url) == 9
    for url, chunks in by_url.items():
        chunks.sort(key=lambda c: c.chunk_index)
        assert chunks[0].char_start == 0
        assert chunks[-1].char_end == len(docs[url])
        for a, b in zip(chunks, chunks[1:], strict=False):
            assert a.char_end == b.char_start
        for c in chunks:
            assert c.text == docs[url][c.char_start : c.char_end]


def test_missing_corpus_leaves_no_artifact(enc, tmp_path: Path) -> None:
    """Design-review: the eager existence check must fire before run_chunking
    opens its output file - no empty artifact on error."""
    out = tmp_path / "chunks.jsonl"
    with pytest.raises(CankarError, match="not found"):
        chunk.run_chunking(tmp_path / "missing.jsonl", enc, 32, out)
    assert not out.exists()


def test_chunkdoc_validator_rejects_bad_span() -> None:
    with pytest.raises(ValueError, match="span"):
        ChunkDoc(
            title="t",
            url="u",
            text="ab",
            n_chars=2,
            n_tokens=1,
            source="wikivir",
            chunk_index=0,
            n_chunks=1,
            char_start=0,
            char_end=3,
        )


def test_bestfit_simulation_pinned() -> None:
    """Full chunks (budget tokens + 1 BOS == capacity) pack losslessly; the
    mixed case is hand-traced and pinned (design-review: an open range
    asserts nothing)."""
    assert chunk.simulate_bestfit_crop([64] * 100, budget=64) == 0.0
    frac = chunk.simulate_bestfit_crop([64, 40, 40, 64], budget=64, buffer_size=2)
    assert frac == pytest.approx(17 / 212)
