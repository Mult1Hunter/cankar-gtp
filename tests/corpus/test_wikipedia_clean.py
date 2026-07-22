"""Wikipedia cleaning + classification tests, calibrated on real slwiki fixtures.

Fixtures are raw wikitext (rvprop=content / dump text - same unexpanded form the
ingester sees), per the architect critique's fidelity requirement.
"""

from pathlib import Path

import pytest

from cankar.corpus.clean import clean_wikitext
from cankar.corpus.wikipedia_clean import (
    INTERWIKI_RE,
    is_disambiguation,
    truncate_apparatus,
    wikipedia_preclean,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "corpus"


def full_clean(raw: str) -> str:
    return clean_wikitext(wikipedia_preclean(raw))


@pytest.mark.parametrize("stem", ["wp_math_media", "wp_apparatus", "wp_media", "wp_table"])
def test_golden(stem: str) -> None:
    raw = (FIXTURES / f"{stem}.wikitext").read_text()
    expected = (FIXTURES / f"{stem}.expected.txt").read_text().rstrip("\n")
    assert full_clean(raw) == expected


@pytest.mark.parametrize("stem", ["wp_math_media", "wp_apparatus", "wp_media", "wp_table"])
def test_no_residue(stem: str) -> None:
    out = full_clean((FIXTURES / f"{stem}.wikitext").read_text())
    for marker in ("thumb|", "sličica|", "px|", "{|", "|-", "Slika:", "Datoteka:"):
        assert marker not in out, f"{marker} residue in {stem}"


def test_apparatus_truncated() -> None:
    out = full_clean((FIXTURES / "wp_apparatus.wikitext").read_text())
    for heading in ("Viri", "Sklici", "Zunanje povezave", "Glej tudi"):
        assert f"== {heading}" not in out


def test_truncate_apparatus_cuts_at_first_backmatter_heading() -> None:
    wt = "Prose before.\n\n== Viri ==\n* ref one\n== Zunanje povezave ==\n* link"
    assert truncate_apparatus(wt).strip() == "Prose before."


def test_apparatus_case_insensitive() -> None:
    assert truncate_apparatus("Body.\n== zunanje POVEZAVE ==\n* x").strip() == "Body."


@pytest.mark.parametrize(
    ("stem", "expected"),
    [("wp_disambig", True), ("wp_apparatus", False), ("wp_media", False)],
)
def test_is_disambiguation(stem: str, expected: bool) -> None:
    assert is_disambiguation((FIXTURES / f"{stem}.wikitext").read_text()) is expected


def test_disambiguation_matches_lowercase_template() -> None:
    assert is_disambiguation("Foo\n{{razločitev}}") is True
    assert is_disambiguation("Foo\n[[Kategorija:Razločitev]]") is True
    assert is_disambiguation("Ordinary article about razločitev topic.") is False


def test_interwiki_stripped() -> None:
    out = wikipedia_preclean("Besedilo [[en:Ljubljana]] [[de:Laibach]] konec.")
    assert "en:" not in out and "de:" not in out


def test_interwiki_re_does_not_eat_normal_links() -> None:
    # a normal wikilink with a colon (namespace) is not a 2-3 letter lang code
    assert not INTERWIKI_RE.search("[[Kategorija:Slovenija]]")
    assert not INTERWIKI_RE.search("[[Ljubljana|mesto]]")


def test_media_link_any_nesting_depth_removed() -> None:
    """Node-filtering handles captions with nested links (the .ogg case that
    defeated the earlier regex)."""
    wt = "Start [[Slika:Film.ogg|thumb|Caption with [[nested]] and [[more|links]]]] end."
    out = full_clean(wt)
    assert "thumb" not in out and "Film.ogg" not in out
    assert "Start" in out and "end." in out
