"""Merge-stage tests - the four dedup signals, collision resolution, and the
architect's must-fix behaviors, on synthetic shards in a tmp corpus."""

import json
from pathlib import Path

import pytest

from cankar.corpus import merge
from cankar.corpus.merge import (
    ResolutionKind,
    load_resolutions,
    ordered_shards,
    shard_tier,
)
from cankar.corpus.registry import Registry, normalize_title


def test_shard_tier_and_ordering(tmp_path: Path) -> None:
    for stem in ("cankar", "wikipedia", "dlib-cankar", "dlib-cankar-gapfill", "askerc"):
        (tmp_path / f"{stem}.jsonl").write_text("")
    order = [p.stem for p in ordered_shards(tmp_path)]
    # literary (tier 0) alphabetical, then dlib, then gapfill, then wikipedia
    assert order == ["askerc", "cankar", "dlib-cankar", "dlib-cankar-gapfill", "wikipedia"]
    assert shard_tier("cankar") == 0 < shard_tier("dlib-cankar") < shard_tier("wikipedia")


def test_load_resolutions(tmp_path: Path) -> None:
    toml = tmp_path / "r.toml"
    toml.write_text(
        '[[collision]]\ntitle = "Rokovnjači"\nresolution = "same_work"\n'
        'attribution = "A, B"\n\n[[collision]]\ntitle = "Ljubezen"\nresolution = "distinct"\n'
    )
    r = load_resolutions(toml)
    assert r[normalize_title("Rokovnjači")].resolution is ResolutionKind.SAME_WORK
    assert r[normalize_title("Rokovnjači")].attribution == "A, B"
    assert r[normalize_title("Ljubezen")].resolution is ResolutionKind.DISTINCT


def _doc(title: str, text: str, source: str, author: str | None) -> dict:
    return {
        "title": title,
        "url": f"http://x/{title}",
        "text": text,
        "n_chars": len(text),
        "source": source,
        "author": author,
    }


def _write(path: Path, docs: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in docs) + "\n")


# two textually DISTINCT works, so the only near-dup is between the Rokovnjači pair
DOMOV = (
    "Na klancu je stala hiša majhna in siva s streho vdrto v sredini kakor bi jo "
    "bila starost potisnila k tlom in okoli nje je raslo nekaj sadnih dreves po "
    "večini jablan in hrušk ki so se sklanjale nad nizko leseno ograjo ob poti."
)
LETTER = (
    "Dragi prijatelj sporočam ti da sem prispel v mesto in da me tukaj čaka "
    "mnogo dela vendar mislim nate in na najine skupne večere ob reki kjer sva "
    "tako pogosto razpravljala o umetnosti in o težkem življenju slovenskega "
    "pisatelja ki mora ustvarjati sredi splošne ravnodušnosti in pomanjkanja."
)
ROKOVNJACI = (
    "Rokovnjači so se zbirali v temnih gozdovih pod Gorjanci kjer jih ni mogla "
    "najti nobena gosposka in od tam so napadali bogate trgovce ki so vozili "
    "svoje blago po cesti proti mestu ter delili plen med uboge kmete v dolini "
    "kajti tako je bila njihova stara navada ohranjena iz časov ko so gospodje "
    "še kruto gospodarili nad ljudstvom in mu jemali zadnji groš za davke tako "
    "da se nihče ni upal glasno pritožiti čeprav je vsak v srcu čutil krivico "
    "ki se je iz roda v rod nabirala kakor težka megla nad tiho slovensko zemljo."
)


@pytest.fixture
def merged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    # cankar registry knows "Domov" (for registry-identity) and "Rokovnjači"
    reg = Registry("Ivan Cankar")
    reg.upsert("Domov")
    kersnik = Registry("Janko Kersnik")

    _write(
        corpus / "cankar.jsonl",
        [
            _doc("Domov", DOMOV, "wikivir", "Ivan Cankar"),
            _doc(
                "German",
                "Der Wald ist still und dunkel und der Fluss rauscht.",
                "wikivir",
                "Ivan Cankar",
            ),
            _doc("Dvojnik", DOMOV, "wikivir", "Ivan Cankar"),  # exact dup of Domov text
            _doc("Pismo Murna", LETTER, "wikivir", "Ivan Cankar"),  # same letter as murn shard
        ],
    )
    _write(
        corpus / "murn.jsonl",
        [_doc("Pismo Murna", LETTER, "wikivir", "Josip Murn")],  # byte-identical -> exact_dup
    )
    _write(
        corpus / "jurcic.jsonl",
        [_doc("Rokovnjači", ROKOVNJACI, "wikivir", "Josip Jurčič")],
    )
    _write(
        corpus / "kersnik.jsonl",
        [_doc("Rokovnjači", ROKOVNJACI.replace("temnih", "gostih"), "wikivir", "Janko Kersnik")],
    )
    # gapfill: OCR of the SAME Domov work -> registry-identity drop
    _write(
        corpus / "dlib-cankar-gapfill.jsonl",
        [_doc("Domov", DOMOV.replace("stala", "stalo"), "dlib", "Ivan Cankar")],
    )
    # wikipedia: a biography ABOUT Cankar (S5 hard negative) - must survive
    _write(
        corpus / "wikipedia.jsonl",
        [
            _doc(
                "Ivan Cankar",
                "Ivan Cankar je bil slovenski pisatelj rojen leta 1876 v Vrhniki.",
                "wikipedia",
                None,
            )
        ],
    )

    res = tmp_path / "res.toml"
    res.write_text(
        '[[collision]]\ntitle = "Rokovnjači"\nresolution = "same_work"\n'
        'attribution = "Josip Jurčič, Janko Kersnik"\nnote = "joint"\n\n'
        '[[collision]]\ntitle = "Pismo Murna"\nresolution = "same_work"\n'
        'attribution = "Josip Murn"\nnote = "letter by Murn"\n'
    )
    monkeypatch.setattr(
        merge, "_author_registries", lambda: {"Ivan Cankar": reg, "Janko Kersnik": kersnik}
    )
    monkeypatch.setattr(
        "cankar.corpus.shard.dataset_manifest",
        lambda stage, name: tmp_path / f"{name}.manifest.json",
    )
    out = tmp_path / "merged.jsonl"
    stats = merge.merge(
        corpus_dir=corpus, out=out, resolution_path=res, report_out=tmp_path / "merge.md"
    )
    docs = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
    return stats, {d["title"]: d for d in docs}, docs


def test_german_gated(merged) -> None:
    stats, by_title, _ = merged
    assert "German" not in by_title
    assert stats.skip_counts["gate_not_slovene"] == 1


def test_exact_dup_dropped(merged) -> None:
    stats, _, _ = merged
    assert stats.skip_counts["exact_dup"] == 2  # Dvojnik==Domov, and the murn-copy letter


def test_registry_identity_drops_ocr_edition(merged) -> None:
    """The gapfill OCR 'Domov' resolves to the same work_id as the Wikivir
    'Domov' - dropped even though MinHash might not catch the OCR variant (M3)."""
    stats, _, _ = merged
    assert stats.skip_counts["registry_identity"] == 1


def test_cross_author_same_work_reattributed(merged) -> None:
    """Kersnik's Rokovnjači near-dups Jurčič's; kept once, attributed jointly
    from the collision table - not silently to whichever shard sorted first."""
    stats, by_title, _ = merged
    assert by_title["Rokovnjači"]["author"] == "Josip Jurčič, Janko Kersnik"
    assert any("Rokovnjači" in line for line in stats.reattributed)
    assert stats.skip_counts["near_dup"] == 1


def test_exact_dup_cross_author_reattributed(merged) -> None:
    """The Murn letter is byte-identical in the cankar and murn shards, so it is
    caught by EXACT dup, not near-dup - yet the collision table must still fix
    attribution (the bug: exact/registry drops bypassed reattribution)."""
    stats, by_title, _ = merged
    assert by_title["Pismo Murna"]["author"] == "Josip Murn"  # not Ivan Cankar
    assert any("Pismo Murna" in line and "exact_dup" in line for line in stats.cross_author)


def test_wikipedia_biography_survives(merged) -> None:
    """S5 hard negative: a Wikipedia article ABOUT Cankar must NOT collapse into
    a Cankar work - different register, kept with author=None."""
    _, by_title, _ = merged
    assert "Ivan Cankar" in by_title
    assert by_title["Ivan Cankar"]["author"] is None


def test_expected_kept_set(merged) -> None:
    _, _, docs = merged
    titles = [d["title"] for d in docs]
    # Domov kept once (Wikivir), German gated, Dvojnik exact-dup, gapfill identity-dropped,
    # Pismo Murna kept once, one Rokovnjači, the wiki bio - in preference order
    assert titles == ["Domov", "Pismo Murna", "Rokovnjači", "Ivan Cankar"]


def test_registry_identity_requires_content_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two different-year collections normalize to one work_id but share NO text
    (the real 'Črtice (Cankar 1914)' vs '1907-09' case). They must NOT be
    collapsed - registry identity confirms by containment before dropping."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    reg = Registry("Ivan Cankar")
    w = reg.upsert("Črtice")  # both titles resolve here via disambiguator stripping
    reg.add_alias(w, "Črtice (Cankar 1914)")
    reg.add_alias(w, "Črtice (Cankar 1907-09)")
    _write(
        corpus / "cankar.jsonl",
        [
            _doc("Črtice (Cankar 1907-09)", DOMOV, "wikivir", "Ivan Cankar"),
            _doc("Črtice (Cankar 1914)", ROKOVNJACI, "wikivir", "Ivan Cankar"),  # disjoint text
        ],
    )
    res = tmp_path / "res.toml"
    res.write_text("")
    monkeypatch.setattr(merge, "_author_registries", lambda: {"Ivan Cankar": reg})
    monkeypatch.setattr(
        "cankar.corpus.shard.dataset_manifest",
        lambda stage, name: tmp_path / f"{name}.manifest.json",
    )
    out = tmp_path / "m.jsonl"
    stats = merge.merge(
        corpus_dir=corpus, out=out, resolution_path=res, report_out=tmp_path / "m.md"
    )
    titles = sorted(json.loads(ln)["title"] for ln in out.read_text().splitlines() if ln.strip())
    assert titles == ["Črtice (Cankar 1907-09)", "Črtice (Cankar 1914)"]  # both kept
    assert stats.skip_counts.get("registry_identity", 0) == 0
    assert any("content differs" in line for line in stats.registry_mismatch)


def test_containment_drops_fully_contained_keeps_volume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A poem fully inside a collected volume is dropped (its text survives in
    the volume - lossless); the volume and a partially-overlapping work stay."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()

    def sl(indices: range | list[int]) -> str:
        # function-word-rich so the quality gate keeps it; unique per-index tokens
        # give distinct shingles for the containment math
        return " ".join(
            f"in je bilo tako da se je v hiši numer{i} zgodilo nekaj kar mesto{i} ni nihče videl"
            for i in indices
        )

    poem = sl(range(20))  # a small work
    volume = sl(range(600))  # >= MIN_SHINGLES, contains the poem's sentences
    partial = sl(list(range(10)) + list(range(1000, 1010)))  # ~50% overlaps the poem
    _write(
        corpus / "kette.jsonl",
        [
            _doc("Poezije 1907", volume, "wikivir", "Dragotin Kette"),
            _doc("Jesen", poem, "wikivir", "Dragotin Kette"),  # fully inside -> dropped
            _doc("Delno", partial, "wikivir", "Dragotin Kette"),  # ~50% -> kept
        ],
    )
    res = tmp_path / "res.toml"
    res.write_text("")
    monkeypatch.setattr(merge, "_author_registries", dict)
    monkeypatch.setattr(
        "cankar.corpus.shard.dataset_manifest",
        lambda stage, name: tmp_path / f"{name}.manifest.json",
    )
    out = tmp_path / "m.jsonl"
    stats = merge.merge(
        corpus_dir=corpus, out=out, resolution_path=res, report_out=tmp_path / "m.md"
    )
    titles = sorted(json.loads(ln)["title"] for ln in out.read_text().splitlines() if ln.strip())
    assert titles == ["Delno", "Poezije 1907"]  # Jesen dropped, volume + partial kept
    assert stats.skip_counts["containment"] == 1
    assert any("Jesen" in line for line in stats.containment_dropped)


def test_distinct_works_both_survive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two DIFFERENT works sharing a title that MinHash flags as near-dup must
    BOTH survive when the collision table marks them distinct (M2 protect path;
    exercises NearDupIndex.insert - the method that was uncommitted)."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    # near-identical text but declared distinct works by two authors
    _write(corpus / "cankar.jsonl", [_doc("Slovo", ROKOVNJACI, "wikivir", "Ivan Cankar")])
    _write(
        corpus / "kveder.jsonl",
        [_doc("Slovo", ROKOVNJACI.replace("temnih", "gostih"), "wikivir", "Zofka Kveder")],
    )
    res = tmp_path / "res.toml"
    res.write_text('[[collision]]\ntitle = "Slovo"\nresolution = "distinct"\n')
    monkeypatch.setattr(merge, "_author_registries", dict)
    monkeypatch.setattr(
        "cankar.corpus.shard.dataset_manifest",
        lambda stage, name: tmp_path / f"{name}.manifest.json",
    )
    out = tmp_path / "m.jsonl"
    stats = merge.merge(
        corpus_dir=corpus, out=out, resolution_path=res, report_out=tmp_path / "m.md"
    )
    authors = sorted(
        json.loads(line)["author"] for line in out.read_text().splitlines() if line.strip()
    )
    assert authors == ["Ivan Cankar", "Zofka Kveder"]  # both kept, not merged
    assert stats.skip_counts["near_dup"] == 0


def test_merge_is_byte_reproducible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two runs on the same inputs produce identical bytes (seeded MinHash)."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _write(
        corpus / "cankar.jsonl",
        [
            _doc("A", DOMOV, "wikivir", "Ivan Cankar"),
            _doc("B", ROKOVNJACI, "wikivir", "Ivan Cankar"),
        ],
    )
    res = tmp_path / "res.toml"
    res.write_text("")
    monkeypatch.setattr(merge, "_author_registries", dict)
    monkeypatch.setattr(
        "cankar.corpus.shard.dataset_manifest",
        lambda stage, name: tmp_path / f"{name}.manifest.json",
    )
    out1, out2 = tmp_path / "1.jsonl", tmp_path / "2.jsonl"
    merge.merge(corpus_dir=corpus, out=out1, resolution_path=res, report_out=tmp_path / "r1.md")
    merge.merge(corpus_dir=corpus, out=out2, resolution_path=res, report_out=tmp_path / "r2.md")
    assert out1.read_bytes() == out2.read_bytes()
