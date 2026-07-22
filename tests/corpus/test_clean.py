"""Golden-file + edge-case tests for cankar.clean (validation ladder L1)."""

import unicodedata
from pathlib import Path

import pytest

from cankar.corpus.clean import clean_wikitext, is_index_title, is_redirect

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.mark.parametrize("slug", ["ada", "noc"])
def test_golden(slug: str) -> None:
    """Real Wikivir pages must clean to the frozen expected output."""
    raw = (FIXTURES / f"{slug}.wikitext").read_text()
    expected = (FIXTURES / f"{slug}.expected.txt").read_text().rstrip("\n")
    assert clean_wikitext(raw) == expected


@pytest.mark.parametrize("slug", ["ada", "noc"])
def test_golden_is_nfc_and_dirt_free(slug: str) -> None:
    out = clean_wikitext((FIXTURES / f"{slug}.wikitext").read_text())
    assert unicodedata.is_normalized("NFC", out)
    assert "{{" not in out and "}}" not in out, "template residue"
    assert "[[" not in out and "]]" not in out, "wikilink residue"
    assert "Kategorija:" not in out, "category residue"


def test_nfd_input_is_normalized() -> None:
    # "čaša" with decomposed diacritics (c + combining caron, s + combining caron)
    nfd = unicodedata.normalize("NFD", "čaša požrešnost")
    assert not unicodedata.is_normalized("NFC", nfd)
    out = clean_wikitext(nfd)
    assert unicodedata.is_normalized("NFC", out)
    assert out == "čaša požrešnost"


def test_markup_stripping() -> None:
    raw = "{{glava|avtor=X}}\n'''Krepko''' in ''ležeče'' [[cilj|besedilo]].<ref>op.</ref>\n"
    out = clean_wikitext(raw)
    assert out == "Krepko in ležeče besedilo."


def test_category_lines_removed() -> None:
    raw = "Besedilo zgodbe.\n\n[[Kategorija:Ivan Cankar]]\n[[Category:Test]]\n"
    assert clean_wikitext(raw) == "Besedilo zgodbe."


def test_excess_blank_lines_collapsed() -> None:
    assert clean_wikitext("a\n\n\n\n\nb") == "a\n\nb"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("#REDIRECT [[Tja]]", True),
        ("#preusmeritev [[Tja]]", True),
        ("  #Redirect [[Tja]]", True),
        ("Navadno besedilo", False),
    ],
)
def test_is_redirect(text: str, expected: bool) -> None:
    assert is_redirect(text) is expected


def test_caret_footnote_lines_removed() -> None:
    """Wikisource caret-notation footnotes (corpus-qa finding, first crawl).

    The removed line leaves a paragraph break - deliberate: never glue together
    prose lines that a footnote separated.
    """
    raw = "Prva vrstica.\n^Zgodovina črtica.\nDruga vrstica.\n"
    assert clean_wikitext(raw) == "Prva vrstica.\n\nDruga vrstica."


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Seznam del Ivana Cankarja", True),
        ("Abecedni seznam del Ivana Cankarja", True),
        ("Na klancu", False),
        ("Seznamka", False),  # prefix must be a whole word
    ],
)
def test_is_index_title(title: str, expected: bool) -> None:
    """List/bibliography pages are catalogs, not literature (corpus-qa finding)."""
    assert is_index_title(title) is expected
