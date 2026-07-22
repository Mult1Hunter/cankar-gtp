"""Ingestion orchestration: config validation, gates, domain errors (ADR 0008)."""

import pytest
from pydantic import ValidationError

from cankar.core.errors import PdGateError, RegistryValidationError, UnknownAuthorError
from cankar.corpus.ingest import AuthorConfig, ingest, ingest_author


def cfg(**overrides: object) -> AuthorConfig:
    base: dict[str, object] = {
        "name": "Testni Avtor",
        "slug": "testni",
        "category": "Kategorija:Testni Avtor",
        "index_page": "Testni Avtor",
        "death_year": 1900,
        "category_pages": 10,
    }
    base.update(overrides)
    return AuthorConfig.model_validate(base)


def test_author_config_rejects_missing_fields() -> None:
    with pytest.raises(ValidationError):
        AuthorConfig.model_validate({"name": "X", "slug": "x"})


def test_pd_gate_raises_domain_error() -> None:
    """The PD gate fires BEFORE any network access - a living author never crawls."""
    with pytest.raises(PdGateError, match="died 2001"):
        ingest_author(cfg(death_year=2001), roster=["Testni Avtor"])


def test_unknown_slug_raises_domain_error() -> None:
    with pytest.raises(UnknownAuthorError, match="no-such-author"):
        ingest(["no-such-author"])


def test_registry_validation_error_carries_problems() -> None:
    err = RegistryValidationError("Testni Avtor", ["p1", "p2"])
    assert err.problems == ["p1", "p2"]
    assert "2 problems" in str(err)
