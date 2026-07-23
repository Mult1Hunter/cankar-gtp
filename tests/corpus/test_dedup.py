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


def test_containment_catches_subpart_that_minhash_misses() -> None:
    """A chapter inside its collected volume: high containment, low Jaccard -
    the class MinHash structurally misses (design-review M4)."""
    from cankar.corpus.dedup import NearDupIndex, containment, shingles

    chapter = " ".join(f"beseda{i}" for i in range(40))
    volume = chapter + " " + " ".join(f"drugo{i}" for i in range(400))
    assert containment(shingles(chapter), shingles(volume)) > 0.8  # chapter is inside
    assert containment(shingles(volume), shingles(chapter)) < 0.2  # volume is not
    # and MinHash at 0.75 does NOT flag them (Jaccard is tiny) - proving the gap
    idx = NearDupIndex()
    assert idx.add_or_match("000", volume) is None
    assert idx.add_or_match("001", chapter) is None  # not caught as near-dup


def test_minhash_is_deterministic() -> None:
    """Seeded permutations -> identical drops across runs (design-review S3)."""
    from cankar.corpus.dedup import minhash

    a = minhash("na klancu je stala hiša majhna in siva s streho vdrto v sredini")
    b = minhash("na klancu je stala hiša majhna in siva s streho vdrto v sredini")
    assert a.jaccard(b) == 1.0


def test_near_dup_index_returns_earliest_root() -> None:
    from cankar.corpus.dedup import NearDupIndex

    idx = NearDupIndex()
    base = " ".join(f"beseda{i}" for i in range(60))
    assert idx.add_or_match("000", base) is None
    assert idx.add_or_match("001", "povsem drugačno besedilo o nečem drugem tukaj") is None
    assert idx.add_or_match("002", base.replace("beseda3 ", "beseda3x ")) == "000"
