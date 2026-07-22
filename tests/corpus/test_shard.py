"""ShardWriter tests - the provenance seam three sources route through (ADR 0008)."""

import json

from cankar.core.manifest import ShardManifest
from cankar.core.paths import dataset_manifest
from cankar.core.schema import CorpusDoc
from cankar.corpus.shard import ShardWriter


def make_doc(text: str) -> CorpusDoc:
    return CorpusDoc(
        title="T",
        url="https://example/x",
        text=text,
        n_chars=len(text),
        source="wikipedia",
        author=None,
    )


def test_writes_jsonl_and_manifest(tmp_path, monkeypatch) -> None:
    # redirect the committed-ledger path into tmp so the test writes nothing real
    monkeypatch.setattr(
        "cankar.corpus.shard.dataset_manifest",
        lambda stage, name: tmp_path / f"{name}.manifest.json",
    )
    out = tmp_path / "x.jsonl"
    with ShardWriter(out, source="wikipedia", script="test", args={"k": "v"}) as w:
        w.write(make_doc("prva vrstica besedila"))
        w.write(make_doc("druga daljša vrstica besedila tukaj"))

    lines = out.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["source"] == "wikipedia"
    assert w.n_docs == 2
    assert w.n_words == 3 + 5

    manifest = ShardManifest.model_validate_json((tmp_path / "x.manifest.json").read_text())
    assert manifest.n_docs == 2
    assert manifest.source == "wikipedia"
    assert manifest.args == {"k": "v"}


def test_manifest_hashes_closed_file(tmp_path, monkeypatch) -> None:
    """sha256 must be of the finished shard - manifest is written after close."""
    mpath = tmp_path / "x.manifest.json"
    monkeypatch.setattr("cankar.corpus.shard.dataset_manifest", lambda stage, name: mpath)
    out = tmp_path / "x.jsonl"
    with ShardWriter(out, source="wikipedia", script="test", args={}) as w:
        w.write(make_doc("besedilo"))
    import hashlib

    assert (
        ShardManifest.model_validate_json(mpath.read_text()).sha256
        == hashlib.sha256(out.read_bytes()).hexdigest()
    )


def test_dataset_manifest_targets_committed_ledger() -> None:
    p = dataset_manifest("corpus", "wikipedia")
    assert p.parts[-3:] == ("datasets", "corpus", "wikipedia.manifest.json")
