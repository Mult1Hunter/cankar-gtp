"""Corpus quality-metric tests - proving the metrics flag garbage (the training
signal the external review said we don't measure). Metrics are pure functions;
these tests assert they discriminate clean text from noise."""

from cankar.corpus.stats import ShardMetrics, compute_metrics


def _docs(*texts: str) -> list[dict]:
    return [{"text": t} for t in texts]


def test_clean_prose_scores_well() -> None:
    prose = (
        "Na klancu je stala hiša, majhna in siva, s streho vdrto v sredini. "
        "Okoli nje je raslo nekaj sadnih dreves, po večini jablan in hrušk."
    )
    m = compute_metrics("clean", _docs(prose, prose.replace("hiša", "koča")))
    assert m.unknown_char_rate == 0.0
    assert m.dup_line_frac == 0.0
    assert m.exact_dup_rate == 0.0
    assert all(v == 0.0 for v in m.markup_doc_rate.values())


def test_ocr_garbage_flagged_by_unknown_chars() -> None:
    garbage = "K!^Jm| <=> ^^ %%%% Sozno v mra^ ^e k'10' ^°se ~|[ @#$ nadaljevanje"
    m = compute_metrics("ocr", _docs(garbage))
    assert m.unknown_char_rate > 0.05  # symbol soup is far above clean prose


def test_duplicate_lines_flagged() -> None:
    m = compute_metrics("rep", _docs("ista vrstica\n" * 50 + "unikat\n"))
    assert m.dup_line_frac > 0.9  # Gopher-style duplicate-line garbage


def test_exact_duplicates_counted() -> None:
    m = compute_metrics("dup", _docs("isto besedilo", "isto besedilo", "drugo"))
    assert m.exact_dup_rate > 0.3  # 1 of 3 is a repeat


def test_residual_markup_detected() -> None:
    m = compute_metrics(
        "markup",
        _docs(
            "{| wikitable |}", "[[wikilink]]", "{{template}}", "thumb|caption", "clean prose here"
        ),
    )
    assert m.markup_doc_rate["wikitable"] == 0.2
    assert m.markup_doc_rate["wikilink"] == 0.2
    assert m.markup_doc_rate["template"] == 0.2
    assert m.markup_doc_rate["image_frag"] == 0.2


def test_low_lexical_diversity_flagged() -> None:
    """Boilerplate (same words repeated) -> low type-token ratio."""
    boiler = compute_metrics("b", _docs("naselje v občini kraj " * 200))
    diverse = compute_metrics("d", _docs(" ".join(f"beseda{i}" for i in range(2000))))
    assert boiler.mattr < 0.10
    assert diverse.mattr > 0.9


def test_empty_shard_is_safe() -> None:
    m = compute_metrics("empty", [])
    assert isinstance(m, ShardMetrics)
    assert m.n_docs == 0
