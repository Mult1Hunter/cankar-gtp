"""Registry contract tests (ADR 0004): normalization, matching, collisions."""

from pathlib import Path

import pytest

from cankar.corpus.registry import (
    Registry,
    SourceRef,
    normalize_for_author,
    normalize_title,
    slugify,
)


def test_normalize_keeps_diacritics() -> None:
    assert normalize_title("Hlapec Jernej in njegova pravica") == "hlapec jernej in njegova pravica"
    assert normalize_title("Križ na gori!") == "križ na gori"
    assert "č" in normalize_title("Črtice")


def test_normalize_for_author_strips_disambiguator() -> None:
    assert normalize_for_author("Ada (Ivan Cankar)", "Ivan Cankar") == "ada"
    # unrelated parenthetical survives
    assert normalize_for_author("Pesem (odlomek)", "Ivan Cankar") == "pesem odlomek"


def test_slugify_ascii() -> None:
    assert slugify("Križ na gori") == "kriz-na-gori"


def test_upsert_find_alias_roundtrip() -> None:
    reg = Registry("Ivan Cankar")
    w = reg.upsert("Hlapec Jernej in njegova pravica", year=1907, genre="povest")
    assert reg.find("Hlapec Jernej in njegova pravica") is w
    assert reg.find("hlapec jernej in njegova PRAVICA!") is w
    reg.add_alias(w, "Hlapec Jernej")
    assert reg.find("Hlapec Jernej") is w
    # upsert on alias/title returns existing, does not duplicate
    assert reg.upsert("Hlapec Jernej in njegova pravica") is w
    assert len(reg.works) == 1


def test_add_source_idempotent_and_upgrade() -> None:
    reg = Registry("Ivan Cankar")
    w = reg.upsert("Jure", year=1907)
    reg.add_source(w, SourceRef(source="dlib", id="URN:X", status="candidate"))
    reg.add_source(w, SourceRef(source="dlib", id="URN:X", status="ingested", year=1907))
    assert len(w.sources) == 1
    assert w.sources[0].status == "ingested"
    # ingested is never downgraded
    reg.add_source(w, SourceRef(source="dlib", id="URN:X", status="candidate"))
    assert w.sources[0].status == "ingested"


def test_unknown_status_rejected() -> None:
    with pytest.raises(ValueError, match="unknown status"):
        SourceRef(source="dlib", id="URN:X", status="whatever")


def test_validate_year_range() -> None:
    reg = Registry("Ivan Cankar")
    w = reg.upsert("Jure")
    reg.add_source(w, SourceRef(source="dlib", id="URN:X", status="candidate", year=1850))
    problems = reg.validate(min_year=1891, max_year=1958)
    assert any("outside plausible range" in p for p in problems)


def test_save_load_roundtrip(tmp_path: Path) -> None:
    reg = Registry("Ivan Cankar")
    w = reg.upsert("Jure", year=1907, genre="črtica")
    reg.add_source(w, SourceRef(source="wikivir", id="Jure", status="ingested"))
    path = tmp_path / "reg.jsonl"
    reg.save(path)
    again = Registry.load(path, "Ivan Cankar")
    assert again.find("Jure").sources[0].status == "ingested"
