"""Catalog page parser tests against real Wikivir fixtures."""

from pathlib import Path

from cankar.corpus.catalog import parse_catalog

FIXTURES = Path(__file__).parent.parent / "fixtures" / "corpus"


def test_author_index() -> None:
    entries, meta = parse_catalog((FIXTURES / "catalog_index.wikitext").read_text())
    assert meta.birth_year == 1876
    assert meta.death_year == 1918
    by_title = {e.title: e for e in entries}
    erotika = by_title["Erotika"]
    assert erotika.year == 1899
    assert erotika.genre == "Poezija"


def test_seznam_sample() -> None:
    entries, meta = parse_catalog((FIXTURES / "catalog_seznam_sample.wikitext").read_text())
    assert meta.birth_year is None  # no {{Avtor}} infobox on the list page
    by_title = {e.title: e for e in entries}
    # "gl." cross-reference becomes an alias, not a work
    alias = by_title["Ah, ne verjemi!"]
    assert alias.alias_of == "Ah ne verjemi, da te ne ljubim"
    # translation flag
    prevod = by_title["Ah kako se razneživši"]
    assert "prevod" in prevod.flags
    # genre from the section heading
    assert by_title["Bolnik"].genre == "Pesmi"
