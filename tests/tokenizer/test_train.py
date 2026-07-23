"""Training + artifact contract tests on the mini fixture corpus."""

from __future__ import annotations

import pickle
from pathlib import Path

import pytest
import torch

from cankar.tokenizer import train
from cankar.tokenizer.vendored import SPECIAL_TOKENS

FIXTURE = Path(__file__).parent.parent / "fixtures" / "tokenizer" / "mini-corpus.jsonl"
VOCAB = 300  # tiny but > 256 + specials


@pytest.fixture(scope="module")
def enc():
    return train.train_encoding(FIXTURE, VOCAB)


def test_roundtrip_all_fixture_classes(enc) -> None:
    """Every enumerated data class (archaic prose, verse elision, drama,
    Wikipedia digits/English, OCR soft-hyphen/tabs, Greek) survives
    encode/decode byte-exact."""
    for text in train.iter_corpus_texts(FIXTURE):
        assert enc.decode(enc.encode_ordinary(text)) == text


def test_vocab_accounting(enc) -> None:
    """'300' means 291 mergeable ranks + 9 specials at the top (critique A-4)."""
    assert enc.n_vocab == VOCAB
    assert len(enc.token_byte_values()) == VOCAB - len(SPECIAL_TOKENS)
    top_ids = {enc.encode_single_token(s) for s in SPECIAL_TOKENS}
    assert top_ids == set(range(VOCAB - len(SPECIAL_TOKENS), VOCAB))


def test_token_bytes_contract(enc) -> None:
    """nanochat's base_train/loss_eval contract (critique MF-1): length is
    n_vocab, dtype int32, zeros exactly at special ids, byte length elsewhere."""
    tb = train.token_bytes_tensor(enc)
    assert tb.shape == (enc.n_vocab,)
    assert tb.dtype == torch.int32
    special_ids = {enc.encode_single_token(s) for s in SPECIAL_TOKENS}
    for tid in range(enc.n_vocab):
        if tid in special_ids:
            assert tb[tid] == 0
        else:
            assert tb[tid] == len(enc.decode_single_token_bytes(tid)) > 0


def test_save_load_through_nanochat_path(enc, tmp_path: Path) -> None:
    """The from_directory-equivalent load path (critique MF-5): pickle the
    Encoding, load it back, verify identical encoding behavior."""
    pkl, tb = train.save_artifacts(enc, tmp_path)
    with pkl.open("rb") as f:
        loaded = pickle.load(f)
    sample = "Solnce je sijalo, al' videl si ga ni."
    assert loaded.encode_ordinary(sample) == enc.encode_ordinary(sample)
    assert torch.equal(torch.load(tb), train.token_bytes_tensor(enc))


def test_determinism_fingerprint(enc) -> None:
    """rustbpe 0.1.0 trains deterministically (critique A-1) - retrain on the
    same stream yields the identical vocab."""
    assert train.verify_determinism(FIXTURE, VOCAB, enc)


def test_vocab_too_small_raises() -> None:
    from cankar.core.errors import CankarError

    with pytest.raises(CankarError):
        train.train_encoding(FIXTURE, 100)
