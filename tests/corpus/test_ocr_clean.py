"""OCR cleaner tests: encoding, golden fixture from a real dLib stream, edges."""

import unicodedata
from pathlib import Path

from cankar.corpus.ocr_clean import decode_stream, line_quality, ocr_clean

FIXTURES = Path(__file__).parent.parent / "fixtures" / "corpus"


def test_decode_cp1250() -> None:
    raw = (FIXTURES / "jure_sample.cp1250").read_bytes()
    text = decode_stream(raw)
    assert sum(text.count(c) for c in "čšž") > 50  # diacritics survived
    assert "oblečenih kmetic" in text


def test_decode_utf8_passthrough() -> None:
    assert decode_stream("čaša požrešnost".encode()) == "čaša požrešnost"


def test_golden_jure_sample() -> None:
    """Real dLib OCR stream must clean to the frozen expected output."""
    raw = (FIXTURES / "jure_sample.cp1250").read_bytes()
    cleaned, metrics = ocr_clean(decode_stream(raw))
    expected = (FIXTURES / "jure_sample.expected.txt").read_text().rstrip("\n")
    assert cleaned == expected
    assert unicodedata.is_normalized("NFC", cleaned)
    assert metrics["alpha_ratio"] > 0.9


def test_garbage_lines_dropped() -> None:
    text = (
        "Lepa čista vrstica prve zgodbe.\n"
        "yhr^Sozno v mra^ ^e k'10' ^°se ~|[\n"
        "455\n"
        "Spisal Ivan Cankar.\n"
        "Druga čista vrstica."
    )
    cleaned, metrics = ocr_clean(text)
    assert "yhr" not in cleaned
    assert "455" not in cleaned
    assert "Spisal" not in cleaned
    assert cleaned == "Lepa čista vrstica prve zgodbe.\nDruga čista vrstica."
    assert metrics["dropped_lines"] == 3


def test_dehyphenation() -> None:
    cleaned, _ = ocr_clean("Voznik je po-\nstal ob cesti.")
    assert "postal" in cleaned


def test_dialogue_punctuation_not_penalized() -> None:
    line = "„Z Bogom!“ je rekel voznik, „kaj pa ti?“"
    assert line_quality(line) > 0.95


def test_orphan_fragments_dropped_roman_numerals_kept() -> None:
    """corpus-qa finding, dLib audit: orphan OCR fragments in the opening zone.

    Roman-numeral chapter markers are authentic literary structure and stay.
    """
    text = "Prva vrstica zgodbe je tukaj.\nJ*\nI.\nDruga vrstica zgodbe sledi tukaj.\nf"
    cleaned, _ = ocr_clean(text)
    assert "J*" not in cleaned
    assert "\nf" not in cleaned
    assert "I." in cleaned


def test_publication_headers_dropped_in_opening_zone() -> None:
    text = (
        "Štev. 2. V Ljubljani, dne 1. svečana 1896. Leto XVI.\n"
        "Leposloven in znanstven list.\n"
        "Zgodba se začne v vasi pod goro nekega jutra."
    )
    cleaned, _ = ocr_clean(text)
    assert "Štev." not in cleaned
    assert "Leposloven" not in cleaned
    assert "Zgodba se začne" in cleaned


def test_backslash_artifacts_removed() -> None:
    cleaned, _ = ocr_clean("Beseda\\ nadaljevanje stavka tukaj.\n\\\nDruga vrstica besedila.")
    assert "\\" not in cleaned


def test_early_noise_metric_flags_corrupted_opening() -> None:
    """Severe docs fuse garbage INTO lines that pass the quality floor
    (corpus-qa dLib audit, doc 'Greh'): the metric counts what survives."""
    fused_line = (
        "K!^Jm| oplo je bilo, in sneg se je tajal na strehah; kapalo je dol "
        "in čaplje so se <^ lesketale nad vodo v jutranjem soncu tam daleč.\n"
    )
    _, metrics = ocr_clean(fused_line * 4)
    assert metrics["kept_lines"] == 4  # lines pass the floor - that is the point
    assert metrics["early_noise"] > 10
