"""Holdout selection invariants (ADR 0013, architect critique MF-1..MF-6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cankar.core.errors import CankarError
from cankar.evals import holdout
from cankar.evals.holdout import HoldoutParams
from cankar.tokenizer import train

FIX = Path(__file__).parent.parent / "fixtures"
EVALS = FIX / "evals" / "mini-cankar.jsonl"
TOK = FIX / "tokenizer" / "mini-corpus.jsonl"

# small band: excludes the 452-char volume from candidacy (but keeps it in the
# doc set as a container), excludes the 23-char verse, keeps the ~250-char prose
PARAMS = HoldoutParams(
    min_chars=100, max_chars=400, containment_reject=0.5, target_token_fraction=0.3, min_works=3
)


@pytest.fixture(scope="module")
def enc():
    return train.train_encoding(TOK, 300)


@pytest.fixture(scope="module")
def docs():
    return holdout.cankar_docs(EVALS)


def test_cankar_docs_are_only_cankar(docs) -> None:
    assert docs and all(d["author"] == "Ivan Cankar" for d in docs)
    assert "Ljubljana" not in {d["title"] for d in docs}  # wikipedia dropped


def test_containment_closure_rejects_contained_work(enc, docs) -> None:
    """MF-1 forward: 'Hlapec Jernej odlomek' text lives inside the kept 'Zbrani
    spisi' volume - holding it out would score seen text. It must be rejected,
    and the report must name its container so a human can audit."""
    r = holdout.select_holdout(docs, enc, PARAMS)
    assert "Hlapec Jernej odlomek" not in {w.title for w in r.works}
    hlapec = [row for row in r.rejected if "Hlapec" in row[0]]
    assert hlapec and hlapec[0][1] >= PARAMS.containment_reject
    assert "Zbrani spisi" in hlapec[0][2]  # container named
    assert all(cont >= PARAMS.containment_reject for _, cont, _ in r.rejected)


def test_reverse_closure_excludes_excerpt_of_heldout(enc, docs) -> None:
    """Design-review: if a HELD-OUT work contains a smaller retained doc, that
    doc must land in also_exclude_urls so Phase 3 drops it too."""
    # 'Zbrani spisi' (volume) is not a candidate (over max_chars) but contains
    # 'Hlapec Jernej odlomek'. If Zbrani is held out, Hlapec must be co-excluded.
    wide = PARAMS.model_copy(update={"max_chars": 1000, "min_works": 1})
    r = holdout.select_holdout(docs, enc, wide)
    held = {w.url for w in r.works}
    hlapec_url = "https://sl.wikisource.org/wiki/Hlapec_Jernej_odlomek"
    zbrani_url = "https://sl.wikisource.org/wiki/Zbrani_spisi"
    if zbrani_url in held:  # Zbrani selected -> its excerpt Hlapec co-excluded
        assert hlapec_url in r.also_exclude_urls


def test_misattribution_excluded(enc, docs) -> None:
    """The audited about-Cankar essay is out of candidacy even though it is
    Cankar-attributed, Wikivir, and in the length band."""
    r = holdout.select_holdout(docs, enc, PARAMS)
    assert "Kulturni pomen Ivana Cankarja" not in {w.title for w in r.works}


def test_source_and_band_filters(enc, docs) -> None:
    titles = {w.title for w in holdout.select_holdout(docs, enc, PARAMS).works}
    assert "Sultanove sandale" not in titles  # dlib source
    assert "Erotika" not in titles  # below min_chars (verse)
    assert "Zbrani spisi (zbirka)" not in titles  # above max_chars (volume)


def test_selection_deterministic(enc, docs) -> None:
    a = holdout.select_holdout(docs, enc, PARAMS)
    b = holdout.select_holdout(docs, enc, PARAMS)
    assert [w.url for w in a.works] == [w.url for w in b.works]
    assert a.also_exclude_urls == b.also_exclude_urls


def test_excludes_filter_unions_both_directions(enc, docs) -> None:
    r = holdout.select_holdout(docs, enc, PARAMS)
    manifest = _manifest(r.works, r.also_exclude_urls)
    ex = holdout.holdout_excludes(manifest)
    assert ex == frozenset(w.url for w in r.works) | frozenset(r.also_exclude_urls)
    assert "https://example.com/not-holdout" not in ex


def test_manifest_roundtrip(enc, docs, tmp_path: Path) -> None:
    r = holdout.select_holdout(docs, enc, PARAMS)
    works = r.works
    manifest = _manifest(works)
    p = tmp_path / "holdout.json"
    p.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    loaded = holdout.load_holdout(p)
    assert [w.url for w in loaded.works] == [w.url for w in works]
    assert loaded.params.min_works == PARAMS.min_works


def test_iter_holdout_texts_detects_drift(enc, docs) -> None:
    """MF-4: hashes are valid only against one corpus text; a drifted work must
    fail loudly, not silently score the wrong bytes."""
    good = _manifest(holdout.select_holdout(docs, enc, PARAMS).works)
    assert dict(holdout.iter_holdout_texts(EVALS, good))  # round-trips clean

    tampered = good.model_copy(deep=True)
    tampered.works[0].content_sha256 = "deadbeef" * 8
    with pytest.raises(CankarError, match="drifted"):
        list(holdout.iter_holdout_texts(EVALS, tampered))


def test_min_works_raises(enc, docs) -> None:
    strict = PARAMS.model_copy(update={"min_works": 999})
    with pytest.raises(CankarError, match="clean holdout works"):
        holdout.select_holdout(docs, enc, strict)


def _manifest(works, also_exclude: list[str] | None = None) -> holdout.HoldoutManifest:
    total = sum(w.n_tokens for w in works)
    return holdout.HoldoutManifest(
        corpus_sha256="test",
        tokenizer_name="v300",
        params=PARAMS,
        cankar_total_tokens=total * 4,
        holdout_tokens=total,
        holdout_fraction=0.25,
        git_sha="test",
        created_at="2026-07-24T00:00:00+00:00",
        works=works,
        also_exclude_urls=also_exclude or [],
    )
