"""Near-duplicate detection tests - proving MinHash LSH catches near-dups that
exact hashing misses (the dedup gap the external review flagged)."""

from cankar.corpus.dedup import find_near_duplicates


def _docs(*texts: str) -> list[dict]:
    return [{"text": t} for t in texts]


def test_distinct_docs_not_flagged() -> None:
    result, drop = find_near_duplicates(
        _docs(
            "Na klancu je stala hiša majhna in siva s streho vdrto v sredini vasi.",
            "Optika je veja fizike ki obravnava svetlobo in njeno obnašanje v snovi.",
            "Reka teče skozi dolino mimo starih mlinov in pozabljenih vaških cerkva.",
        )
    )
    assert drop == []
    assert result.duplicate_rate == 0.0


def test_near_duplicate_caught_despite_edits() -> None:
    """Reworded copy (edition variant / OCR-vs-transcription) is a near-dup even
    though its bytes differ, so exact hashing would miss it."""
    base = " ".join(f"beseda{i}" for i in range(60))
    variant = base.replace("beseda3 ", "beseda3a ").replace("beseda40", "beseda40x")
    result, drop = find_near_duplicates(_docs(base, variant, "povsem drugačno besedilo tukaj"))
    assert 1 in drop  # the variant is dropped
    assert 2 not in drop  # the distinct doc is kept
    assert result.n_duplicate_docs == 1


def test_geo_stub_boilerplate_clustered() -> None:
    """Templated near-identical stubs (the Wikipedia geo-stub problem) cluster:
    a long shared template with only the place name varying."""
    template = (
        "je naselje v Republiki Sloveniji v občini Test in se nahaja v osrednji "
        "statistični regiji ob reki ki teče skozi dolino mimo starih hiš in polj "
        "Po popisu prebivalstva iz leta je imelo naselje nekaj deset prebivalcev "
        "ki se večinoma ukvarjajo s kmetijstvom in gozdarstvom v okoliških hribih"
    )
    stubs = _docs(*[f"Vas {name} {template}" for name in ("Gorica", "Dolina", "Ravne", "Bistra")])
    result, drop = find_near_duplicates(stubs)
    assert result.n_duplicate_docs == 3  # 3 of 4 collapse into the first's cluster
    assert result.n_clusters == 1
