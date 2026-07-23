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


def test_merged_is_deterministic(merged, tmp_path, monkeypatch) -> None:
    """Same inputs -> byte-identical merged output (seeded MinHash + fixed order)."""
    _, _, docs = merged
    titles = [d["title"] for d in docs]
    # Domov kept once (Wikivir), German gated, Dvojnik exact-dup, gapfill identity-dropped,
    # one Rokovnjači, the wiki bio -> deterministic kept set
    assert titles == ["Domov", "Pismo Murna", "Rokovnjači", "Ivan Cankar"]
