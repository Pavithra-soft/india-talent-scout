"""Transparent JD match scores. Weights are fractions of the total."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.profile_fields import INDIAN_CITIES, canonicalize_skill, find_location, skill_set
from app.resume_parser import TECH_KEYWORDS


@dataclass
class JobNeeds:
    must_have: list[str]
    nice_to_have: list[str]
    min_years: int | None
    max_years: int | None
    locations: list[str]
    raw: str


@dataclass
class ScoreBreakdown:
    score: int
    matching: list[str]
    missing: list[str]
    rationale: str
    must_points: float
    nice_points: float
    experience_points: float
    location_points: float


def default_weights() -> dict[str, int]:
    return {"must": 60, "nice": 20, "experience": 10, "location": 10}


def parse_job_description(text: str) -> JobNeeds:
    raw = (text or "").strip()
    must_block, nice_block = _split_skill_sections(raw)
    if must_block is None and nice_block is None:
        must = _skills_in(raw)
        nice = []
    else:
        must = _skills_in(must_block or "")
        nice = [skill for skill in _skills_in(nice_block or "") if skill not in must]
    min_years, max_years = _experience_range(raw)
    locations = _locations_in(raw)
    return JobNeeds(must, nice, min_years, max_years, locations, raw)


def score_profile(
    skills: str,
    years: int | None,
    location: str,
    job: JobNeeds,
    weights: dict[str, int] | None = None,
) -> ScoreBreakdown:
    weights = _clean_weights(weights or default_weights())
    profile_skills = skill_set(skills)
    must = [canonicalize_skill(skill) for skill in job.must_have]
    nice = [canonicalize_skill(skill) for skill in job.nice_to_have]
    must = [skill for skill in dict.fromkeys(must) if skill]
    nice = [skill for skill in dict.fromkeys(nice) if skill and skill not in must]

    matched_must = [skill for skill in must if skill in profile_skills]
    matched_nice = [skill for skill in nice if skill in profile_skills]
    missing = [skill for skill in must + nice if skill not in profile_skills]
    matching = matched_must + matched_nice

    must_ratio = (len(matched_must) / len(must)) if must else 1.0
    nice_ratio = (len(matched_nice) / len(nice)) if nice else 1.0
    exp_ratio = _experience_fit(years, job.min_years, job.max_years)
    loc_ratio = _location_fit(location, job.locations)

    total = sum(weights.values()) or 1
    must_points = weights["must"] * must_ratio
    nice_points = weights["nice"] * nice_ratio
    experience_points = weights["experience"] * exp_ratio
    location_points = weights["location"] * loc_ratio
    score = round(100 * (must_points + nice_points + experience_points + location_points) / total)

    rationale = _rationale(
        matched_must,
        must,
        years,
        job,
        location,
        loc_ratio,
    )
    return ScoreBreakdown(
        score=max(0, min(100, score)),
        matching=matching,
        missing=missing,
        rationale=rationale,
        must_points=round(must_points, 1),
        nice_points=round(nice_points, 1),
        experience_points=round(experience_points, 1),
        location_points=round(location_points, 1),
    )


def _clean_weights(weights: dict[str, int]) -> dict[str, int]:
    cleaned = default_weights()
    for key in cleaned:
        try:
            value = int(weights.get(key, cleaned[key]))
        except (TypeError, ValueError):
            value = cleaned[key]
        cleaned[key] = max(0, min(100, value))
    return cleaned


def _split_skill_sections(text: str) -> tuple[str | None, str | None]:
    must_match = re.search(
        r"(must[- ]have|required skills|requirements)\s*[:\-]?\s*(.*?)(?=nice[- ]to[- ]have|preferred|good to have|$)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    nice_match = re.search(
        r"(nice[- ]to[- ]have|preferred skills|good to have)\s*[:\-]?\s*(.*)$",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not must_match and not nice_match:
        return None, None
    return (
        must_match.group(2) if must_match else "",
        nice_match.group(2) if nice_match else "",
    )


def _skills_in(text: str) -> list[str]:
    found: list[str] = []
    haystack = f" {text.lower()} "
    phrases = []
    for canonical, aliases in (
        (skill, (skill,)) for skill in sorted(TECH_KEYWORDS, key=len, reverse=True)
    ):
        phrases.append((canonical, aliases))
    from app.profile_fields import SKILL_SYNONYMS

    for canonical, aliases in SKILL_SYNONYMS.items():
        phrases.append((canonical, aliases))
    seen = set()
    for canonical, aliases in phrases:
        for alias in sorted(aliases, key=len, reverse=True):
            if re.search(rf"(?<![a-z0-9]){re.escape(alias.lower())}(?![a-z0-9])", haystack):
                name = canonicalize_skill(canonical)
                if name and name not in seen:
                    seen.add(name)
                    found.append(name)
                break
    return [
        skill
        for skill in found
        if not any(other != skill and other.startswith(skill + " ") for other in found)
    ]


def _experience_range(text: str) -> tuple[int | None, int | None]:
    span = re.search(r"(\d{1,2})\s*(?:to|-|–)\s*(\d{1,2})\s*(?:years|yrs)", text, re.I)
    if span:
        return int(span.group(1)), int(span.group(2))
    plus = re.search(r"(\d{1,2})\s*\+\s*(?:years|yrs)", text, re.I)
    if plus:
        return int(plus.group(1)), None
    one = re.search(r"(\d{1,2})\s*(?:years|yrs)", text, re.I)
    if one:
        return int(one.group(1)), None
    return None, None


def _locations_in(text: str) -> list[str]:
    found = []
    haystack = text.lower()
    for city in INDIAN_CITIES:
        if re.search(rf"\b{re.escape(city)}\b", haystack):
            label = find_location(city)
            if label and label not in found:
                found.append(label)
    return found


def _experience_fit(years: int | None, minimum: int | None, maximum: int | None) -> float:
    if minimum is None and maximum is None:
        return 1.0
    if years is None:
        return 0.0
    if minimum is not None and years < minimum:
        return 0.4 if minimum - years <= 2 else 0.0
    if maximum is not None and years > maximum:
        return 0.4 if years - maximum <= 2 else 0.0
    return 1.0


def _location_fit(profile_location: str, job_locations: list[str]) -> float:
    if not job_locations:
        return 1.0
    if not profile_location:
        return 0.0
    profile = profile_location.lower()
    for city in job_locations:
        if city.lower() in profile or profile in city.lower():
            return 1.0
    if "remote" in profile:
        return 1.0
    return 0.0


def _rationale(
    matched_must: list[str],
    must: list[str],
    years: int | None,
    job: JobNeeds,
    location: str,
    loc_ratio: float,
) -> str:
    if must:
        skill_part = f"Covers {len(matched_must)}/{len(must)} must-have skills"
    else:
        skill_part = "No must-have skills were listed"
    if job.min_years is None and job.max_years is None:
        exp_part = "experience not specified"
    elif years is None:
        exp_part = "experience missing on the profile"
    elif _experience_fit(years, job.min_years, job.max_years) == 1.0:
        exp_part = "experience fits"
    else:
        exp_part = "experience is outside the requested range"
    if not job.locations:
        loc_part = "location not specified"
    elif loc_ratio == 1.0:
        loc_part = f"location matches ({location})"
    elif not location:
        loc_part = "location missing on the profile"
    else:
        loc_part = f"location {location} does not match"
    return f"{skill_part}; {exp_part}; {loc_part}."
