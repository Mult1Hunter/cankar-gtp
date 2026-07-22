"""OCR text cleaning + quality gating for dLib TEXT streams.

dLib OCR reality (verified on live streams, 2026-07): windows-1250 encoding
(not UTF-8), no blank-line paragraph structure (line-per-line text), line-break
hyphenation, page numbers, "Spisal <author>" bylines, and OCR-mangled decorated
initials corrupting opening lines. Cleaning therefore works LINE-wise. This
module is the dLib counterpart of cankar.clean (which handles wiki markup).
"""

from __future__ import annotations

import re
import unicodedata

# words split across line breaks: "pri-\nsel" -> "prisel"
DEHYPH_RE = re.compile(r"(\w)[-¬]\n(\w)")
# lines that are only page numbers / folio marks
PAGE_NUMBER_RE = re.compile(r"^\s*[-]?\s*\d{1,4}\s*[-]?\s*$")
# front-matter bylines ("Spisal Ivan Cankar.", "Napisal ...")
BYLINE_RE = re.compile(r"^\s*(Spisal|Napisal|Spisala|Napisala)\b.{0,60}$")
# journal publication headers, only dangerous in the opening lines
HEADER_RE = re.compile(r"^\s*(Štev\.|V Ljubljani,? dne|Leposloven)|(\bLeto [IVX]+\.?\s*$)")
# roman-numeral chapter/section markers are authentic literary structure - keep
ROMAN_RE = re.compile(r"^[IVXLC]{1,6}\.?$")
# standalone backslash lines / backslash-space artifacts from margin OCR
BACKSLASH_LINE_RE = re.compile(r"^\\+\s*$")
# characters typical of severely corrupted OCR (mangled decorated title pages)
NOISE_CHARS = set("<>^=~|%&$#")
HEADER_ZONE = 10  # lines
ORPHAN_ZONE = 30  # lines

# characters that count as "good" beyond letters/spaces (Slovene typography)
_GOOD_PUNCT = set(".,;:!?-\"'()„“”«»*…")


def decode_stream(raw: bytes) -> str:
    """dLib TEXT streams are usually cp1250; some newer ones are UTF-8."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1250", errors="replace")


def line_quality(line: str) -> float:
    """Share of alphabetic/space/normal-punctuation chars; OCR garbage is
    heavy on ^ ~ | ° digits-in-words and similar symbol noise."""
    stripped = line.strip()
    if not stripped:
        return 1.0
    good = sum(1 for ch in stripped if ch.isalpha() or ch.isspace() or ch in _GOOD_PUNCT)
    return good / len(stripped)


def ocr_clean(text: str, line_floor: float = 0.85) -> tuple[str, dict[str, float | int]]:
    """Clean OCR text line-wise; drop hopeless lines; report quality metrics.

    Returns (cleaned_text, metrics). Callers gate whole docs on
    metrics["alpha_ratio"] and inspect metrics["dropped_lines"].
    """
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("�", "")
    text = DEHYPH_RE.sub(r"\1\2", text)
    text = re.sub(r"\\\s+", " ", text)  # backslash-space margin artifacts

    kept: list[str] = []
    dropped = 0
    for i, line in enumerate(text.split("\n")):
        line = re.sub(r"[ \t]+", " ", line.strip())
        if not line:
            kept.append("")
            continue
        if PAGE_NUMBER_RE.match(line) or BYLINE_RE.match(line) or BACKSLASH_LINE_RE.match(line):
            dropped += 1
            continue
        if i < HEADER_ZONE and HEADER_RE.search(line):
            dropped += 1
            continue
        # orphan OCR fragments ("J*", "L", "f") in the opening zone;
        # roman-numeral chapter markers stay (authentic literary structure)
        if i < ORPHAN_ZONE and len(line) <= 2 and not ROMAN_RE.match(line):
            dropped += 1
            continue
        if line_quality(line) < line_floor:
            dropped += 1
            continue
        kept.append(line)

    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    total = len(cleaned) or 1
    alpha = sum(1 for ch in cleaned if ch.isalpha() or ch.isspace())
    # early-corruption signal measured on what actually SURVIVES cleaning:
    # severe docs have garbage fused into kept lines (corpus-qa dLib audit);
    # recoverable docs lose their noise with the dropped lines
    early_noise = sum(1 for ch in cleaned[:1000] if ch in NOISE_CHARS)
    metrics = {
        "alpha_ratio": round(alpha / total, 4),
        "dropped_lines": dropped,
        "kept_lines": sum(1 for k in kept if k),
        "n_chars": len(cleaned),
        "early_noise": early_noise,
    }
    return cleaned, metrics
