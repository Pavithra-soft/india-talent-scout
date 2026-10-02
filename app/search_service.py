from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.ai_gateway import rerank_candidates
from app.models import Candidate, ResumeArtifact
from app.portal_service import pull_from_portals
from app.plugins import SearchCriteria


@dataclass
class SearchParams:
    skills: str
    city: str | None
    min_years: int | None
    max_years: int | None
    active_days: int
    source: str | None
    job_brief: str | None
    portal_keys: list[str] | None = None
    include_local_pool: bool = True
    sync_portals: bool = False


@dataclass
class ScoredCandidate:
    candidate: Candidate
    score: float
    matched_skills: list[str]


def parse_skill_tokens(raw: str) -> list[str]:
    if not raw or not raw.strip():
        return []
    tokens = []
    for part in raw.replace(";", ",").split(","):
        t = part.strip().lower()
        if t and t not in tokens:
            tokens.append(t)
    return tokens


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def score_candidate(candidate: Candidate, skill_tokens: list[str], active_cutoff: datetime) -> ScoredCandidate:
    skill_field = (candidate.skills or "").lower()
    blob = (candidate.search_blob or "").lower()
    matched = []
    for tok in skill_tokens:
        if tok in skill_field or tok in blob:
            matched.append(tok)
    score = float(len(matched) * 10)
    if skill_tokens and not matched:
        score = 0.0
    elif not skill_tokens:
        score = 1.0

    last_active = _as_utc(candidate.last_active_at)
    if last_active and last_active >= active_cutoff:
        score += 5.0
    elif last_active:
        days_ago = (datetime.now(timezone.utc) - last_active).days
        score += max(0.0, 3.0 - days_ago * 0.05)

    if candidate.years_experience is not None:
        score += min(candidate.years_experience, 20) * 0.1

    return ScoredCandidate(candidate=candidate, score=score, matched_skills=matched)


def search_candidates(db: Session, params: SearchParams) -> tuple[list[ScoredCandidate], list[str]]:
    sync_messages: list[str] = []
    if params.sync_portals and params.portal_keys:
        criteria = SearchCriteria(
            skills=parse_skill_tokens(params.skills),
            city=params.city,
            min_years=params.min_years,
            max_years=params.max_years,
            active_days=params.active_days,
        )
        report = pull_from_portals(db, params.portal_keys, criteria)
        sync_messages.extend(report.messages)

    if not params.include_local_pool and not params.portal_keys:
        return [], sync_messages

    skill_tokens = parse_skill_tokens(params.skills)
    active_cutoff = datetime.now(timezone.utc) - timedelta(days=max(params.active_days, 1))

    stmt: Select = select(Candidate).where(Candidate.consent.is_(True))
    stmt = stmt.where(Candidate.last_active_at >= active_cutoff)

    if params.city and params.city.strip():
        city = f"%{params.city.strip().lower()}%"
        stmt = stmt.where(func.lower(Candidate.city).like(city))

    if params.min_years is not None:
        stmt = stmt.where(Candidate.years_experience >= params.min_years)
    if params.max_years is not None:
        stmt = stmt.where(Candidate.years_experience <= params.max_years)
    if params.source and params.source.strip():
        stmt = stmt.where(Candidate.source == params.source.strip().upper())

    if params.portal_keys:
        if params.include_local_pool:
            stmt = stmt.where(
                or_(
                    Candidate.source_portal.in_(params.portal_keys),
                    Candidate.source_portal.is_(None),
                )
            )
        else:
            stmt = stmt.where(Candidate.source_portal.in_(params.portal_keys))

    if skill_tokens:
        clauses = []
        for tok in skill_tokens:
            pattern = f"%{tok}%"
            clauses.append(func.lower(Candidate.skills).like(pattern))
            clauses.append(func.lower(Candidate.search_blob).like(pattern))
        stmt = stmt.where(or_(*clauses))

    rows = db.scalars(stmt).all()
    rows = [c for c in rows if (_as_utc(c.last_active_at) or active_cutoff) >= active_cutoff]
    scored = [score_candidate(c, skill_tokens, active_cutoff) for c in rows]
    scored = [s for s in scored if s.score > 0 or not skill_tokens]
    scored.sort(key=lambda s: s.score, reverse=True)

    if params.job_brief and params.job_brief.strip() and scored:
        payload = []
        for s in scored[:20]:
            snippet = s.candidate.profile_summary or ""
            if s.candidate.resume and s.candidate.resume.extracted_text:
                snippet = s.candidate.resume.extracted_text[:600]
            payload.append(
                {
                    "id": s.candidate.id,
                    "skills": s.candidate.skills,
                    "years_experience": s.candidate.years_experience,
                    "snippet": snippet,
                }
            )
        ordered_ids = rerank_candidates(params.job_brief, payload)
        by_id = {s.candidate.id: s for s in scored}
        reranked = [by_id[i] for i in ordered_ids if i in by_id]
        tail = [s for s in scored if s.candidate.id not in ordered_ids]
        return reranked + tail, sync_messages

    return scored, sync_messages
