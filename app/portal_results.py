"""Merge portal hits, score them with the JD ranker, and name download files."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from app.jd_rank import default_weights, parse_job_description, score_profile
from app.portal_connectors import PortalProfile
from app.profile_fields import normalize_email, normalize_phone


def profile_filename(rank: int, name: str, portal: str, when: datetime, ext: str = "txt") -> str:
    safe_name = re.sub(r"[^A-Za-z0-9]+", "", name or "") or "Candidate"
    safe_portal = re.sub(r"[^A-Za-z0-9]+", "", portal or "") or "portal"
    stamp = when.astimezone(timezone.utc).strftime("%Y%m%d")
    return f"{int(rank):02d}_{safe_name}_{safe_portal}_{stamp}.{ext}"


def identity_keys(profile: PortalProfile) -> list[str]:
    keys = []
    email = normalize_email(profile.email)
    phone = normalize_phone(profile.phone)
    if email:
        keys.append("e:" + email)
    if phone:
        keys.append("p:" + phone)
    name = _compact(profile.name)
    company = _compact(profile.company)
    if name and company:
        keys.append(f"n:{name}|{company}")
    return keys


def dedupe_profiles(profiles: list[PortalProfile]) -> list[PortalProfile]:
    kept: list[PortalProfile] = []
    seen: dict[str, int] = {}
    for profile in profiles:
        keys = identity_keys(profile)
        match_at = next((seen[key] for key in keys if key in seen), None)
        if match_at is None:
            index = len(kept)
            kept.append(profile)
        else:
            index = match_at
            if _richness(profile) > _richness(kept[index]):
                kept[index] = profile
        for key in identity_keys(kept[index]):
            seen[key] = index
    return kept


def rank_hits(jd_text: str, profiles: list[PortalProfile], weights: dict | None = None) -> list[dict]:
    job = parse_job_description(jd_text or "")
    applied = weights or default_weights()
    ranked = []
    for profile in profiles:
        text = profile.resume_text()
        skill_text = profile.skills or profile.snippet or text
        breakdown = score_profile(skill_text, profile.years_experience, profile.location, job, applied)
        ranked.append(
            {
                "portal": profile.portal,
                "portal_id": profile.portal_id,
                "name": profile.name,
                "email": normalize_email(profile.email),
                "phone": normalize_phone(profile.phone),
                "company": profile.company,
                "location": profile.location,
                "skills": profile.skills,
                "years_experience": profile.years_experience,
                "notice_raw": profile.notice_raw,
                "notice_days": profile.notice_days,
                "snippet": profile.snippet,
                "score": breakdown.score,
                "matching_skills": ", ".join(breakdown.matching),
                "missing_skills": ", ".join(breakdown.missing),
                "rationale": breakdown.rationale,
                "resume_text": text,
            }
        )
    ranked.sort(key=lambda row: (-(row["score"] or 0), row["name"].lower()))
    return ranked


def similar_plan(profile: PortalProfile) -> dict:
    skills = [part.strip() for part in (profile.skills or "").split(",") if part.strip()]
    return {
        "must_have": [{"skill": skill, "variants": [skill]} for skill in skills[:6]],
        "nice_to_have": [],
        "titles": [],
        "min_years": None,
        "max_years": None,
        "locations": [profile.location] if profile.location else [],
        "notice": "",
        "queries": {},
    }


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _richness(profile: PortalProfile) -> int:
    return sum(
        1
        for value in (
            profile.email,
            profile.phone,
            profile.skills,
            profile.company,
            profile.location,
            profile.snippet,
        )
        if value
    )

