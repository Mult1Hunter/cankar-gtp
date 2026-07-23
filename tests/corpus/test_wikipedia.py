"""Wikipedia dump ingester: streaming, filtering, provenance (ADR 0008).

Uses a tiny synthetic dump fixture carrying the real <mediawiki xmlns=...>
envelope so the namespace-localname matching (critique #1) is exercised - not a
bare <page> that would let a namespace bug pass.
"""

import json
from pathlib import Path

from cankar.corpus.wikipedia import _iter_pages, ingest

MINI = Path(__file__).parent.parent / "fixtures" / "corpus" / "mini_slwiki.xml.bz2"


def test_iter_pages_reads_namespaced_dump() -> None:
    """The dump declares a default xmlns; tags must match on localname."""
    titles = [p.title for p in _iter_pages(MINI)]
    assert titles == [
        "Optika",
        "Uporabnik:Test",
        "OptikaR",
        "Seznam fizikov",
        "Koren",
        "Drobec",
        "Prazna",
    ]


def test_ingest_filters_every_class(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "cankar.corpus.shard.dataset_manifest",
        lambda stage, name: tmp_path / f"{name}.manifest.json",
    )
    out = tmp_path / "wikipedia.jsonl"
    stats = ingest(MINI, out, min_chars=50)

    assert stats.non_ns0 == 1  # Uporabnik:Test
    assert stats.redirect == 1  # OptikaR
    assert stats.list_page == 1  # Seznam fizikov
    assert stats.disambig == 1  # Koren
    assert stats.stub_min_chars == 1  # Drobec
    assert stats.empty_text == 1  # Prazna (apparatus-only -> cleans to empty)
    assert stats.docs == 1  # only Optika survives

    docs = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(docs) == 1
    doc = docs[0]
    assert doc["title"] == "Optika"
    assert doc["source"] == "wikipedia"
    assert doc["author"] is None
    assert "== Viri" not in doc["text"]  # apparatus truncated
    assert doc["url"] == "https://sl.wikipedia.org/wiki/Optika"


def test_manifest_records_input_provenance(tmp_path, monkeypatch) -> None:
    """The output manifest's sha256 is of the shard; input dump provenance
    (name, sha256, license) lives in args (critique #10)."""
    mpath = tmp_path / "wikipedia.manifest.json"
    monkeypatch.setattr("cankar.corpus.shard.dataset_manifest", lambda stage, name: mpath)
    ingest(MINI, tmp_path / "wikipedia.jsonl", min_chars=50)
    manifest = json.loads(mpath.read_text())
    args = manifest["args"]
    assert args["dump_filename"] == "mini_slwiki.xml.bz2"
    assert args["license"] == "CC BY-SA 4.0"
    assert len(args["dump_sha256"]) == 64
    # ADR 0004 amendment: skip counts are the committed 'never silently dropped'
    # record - in the manifest, not just the logs (design-review must-fix #1)
    assert manifest["skip_counts"]["redirect"] == 1
    assert manifest["skip_counts"]["disambig"] == 1
    assert "docs" not in manifest["skip_counts"]
