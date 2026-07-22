"""Domain exceptions (ADR 0008).

Library code raises these; ONLY cli.py modules convert them to exit codes.
`raise SystemExit` inside importable modules is banned - it made corpus code
unusable from FastAPI (Phase 7) and untestable without process isolation.
"""

from __future__ import annotations


class CankarError(Exception):
    """Base for all domain errors."""


class CatalogPageMissingError(CankarError):
    """A Wikivir catalog page named in configuration does not exist."""


class PdGateError(CankarError):
    """Author fails the public-domain gate (died too recently)."""


class RegistryValidationError(CankarError):
    """A works registry failed collision/year validation."""

    def __init__(self, author: str, problems: list[str]):
        self.author = author
        self.problems = problems
        super().__init__(f"registry validation failed for {author}: {len(problems)} problems")


class UnknownAuthorError(CankarError):
    """A requested author slug is not in configs/corpus/authors.toml."""
