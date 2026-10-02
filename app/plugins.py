from __future__ import annotations

"""Future commercial portal integrations (Resdex, Mustakbil, etc.)."""

from dataclasses import dataclass
from typing import Protocol


@dataclass
class SearchCriteria:
    skills: list[str]
    city: str | None
    min_years: int | None
    max_years: int | None
    active_days: int


@dataclass
class ExternalCandidate:
    name: str
    email: str
    skills: str
    city: str | None
    years_experience: int | None
    source_portal: str


class CandidateSourceProvider(Protocol):
    def search(self, criteria: SearchCriteria) -> list[ExternalCandidate]:
        ...


class NoOpCandidateSourceProvider:
    """Placeholder until a paid portal API is wired in."""

    def search(self, criteria: SearchCriteria) -> list[ExternalCandidate]:
        return []
