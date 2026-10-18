"""Per-recruiter temporary JD workspace. Rows expire and are not the talent pool."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.jd_rank import JobNeeds, default_weights, parse_job_description, score_profile
from app.models import JdProfile, JdWorkspace
from app.profile_parse import ParsedProfile

MAX_PROFILES = 500


class ReplaceRequired(Exception):
    pass


def purge_expired(db: Session, now: datetime | None = None) -> None:
    moment = now or datetime.now(timezone.utc)
    expired = db.query(JdWorkspace).filter(JdWorkspace.expires_at < moment).all()
    for workspace in expired:
        db.delete(workspace)
    if expired:
        db.commit()


def get_workspace(db: Session, owner_key: str) -> JdWorkspace | None:
    purge_expired(db)
    return db.query(JdWorkspace).filter(JdWorkspace.owner_key == owner_key).one_or_none()


def ensure_workspace(db: Session, owner_key: str) -> JdWorkspace:
    workspace = get_workspace(db, owner_key)
    if workspace:
        return workspace
    now = datetime.now(timezone.utc)
    workspace = JdWorkspace(
        owner_key=owner_key,
        created_at=now,
        expires_at=now + timedelta(hours=get_settings().jd_ttl_hours),
        jd_text="",
        weights_json=json.dumps(default_weights()),
        filter_json="{}",
    )
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return workspace


def clear_workspace(db: Session, owner_key: str) -> None:
    workspace = get_workspace(db, owner_key)
    if workspace:
        db.delete(workspace)
        db.commit()


def add_profiles(
    db: Session,
    owner_key: str,
    parsed: list[ParsedProfile],
    *,
    confirm_replace: bool,
    replace: bool,
) -> tuple[int, int, list[str]]:
    workspace = get_workspace(db, owner_key)
    existing = list(workspace.profiles) if workspace else []
    if existing and replace and not confirm_replace:
        raise ReplaceRequired()
    if existing and replace and confirm_replace:
        clear_workspace(db, owner_key)
        workspace = None
        existing = []
    workspace = workspace or ensure_workspace(db, owner_key)
    known = {row.file_hash for row in workspace.profiles}
    added = 0
    skipped = 0
    notes: list[str] = []
    for profile in parsed:
        if profile.file_hash in known:
            skipped += 1
            notes.append(f"{profile.filename}: duplicate skipped.")
            continue
        if len(workspace.profiles) >= MAX_PROFILES:
            notes.append(f"Stopped at {MAX_PROFILES} profiles.")
            break
        db.add(
            JdProfile(
                workspace=workspace,
                file_hash=profile.file_hash,
                filename=profile.filename,
                name=profile.name,
                email=profile.email,
                phone=profile.phone,
                location=profile.location,
                skills=profile.skills,
                company=profile.company,
                notice_raw=profile.notice_raw,
                notice_days=profile.notice_days,
                years_experience=profile.years_experience,
                matching_skills="",
                missing_skills="",
                score=None,
                rationale="",
            )
        )
        known.add(profile.file_hash)
        added += 1
    if added and workspace.jd_text:
        db.flush()
        rank_workspace(db, workspace, workspace.jd_text, _weights(workspace), confirm_replace=True)
    db.commit()
    return added, skipped, notes


def rank_workspace(
    db: Session,
    workspace: JdWorkspace,
    jd_text: str,
    weights: dict[str, int],
    *,
    confirm_replace: bool,
) -> JobNeeds:
    if workspace.jd_text and workspace.jd_text.strip() != jd_text.strip() and not confirm_replace:
        raise ReplaceRequired()
    job = parse_job_description(jd_text)
    workspace.jd_text = jd_text
    workspace.weights_json = json.dumps(weights)
    for profile in workspace.profiles:
        breakdown = score_profile(
            profile.skills,
            profile.years_experience,
            profile.location,
            job,
            weights,
        )
        profile.score = breakdown.score
        profile.matching_skills = ", ".join(breakdown.matching)
        profile.missing_skills = ", ".join(breakdown.missing)
        profile.rationale = breakdown.rationale
    db.commit()
    return job


def save_filters(db: Session, workspace: JdWorkspace, filters: dict) -> None:
    workspace.filter_json = json.dumps(filters)
    db.commit()


def load_filters(workspace: JdWorkspace | None) -> dict:
    if not workspace or not workspace.filter_json:
        return {}
    try:
        data = json.loads(workspace.filter_json)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def filter_profiles(profiles: list[JdProfile], filters: dict) -> list[JdProfile]:
    rows = list(profiles)
    notice = (filters.get("notice") or "any").lower()
    if notice == "immediate":
        rows = [row for row in rows if row.notice_days == 0 or "serving notice" in (row.notice_raw or "").lower()]
    elif notice in {"15", "30", "60", "90"}:
        limit = int(notice)
        rows = [row for row in rows if row.notice_days is not None and row.notice_days <= limit]
    elif notice == "custom":
        rows = [row for row in rows if _in_notice_range(row.notice_days, filters.get("notice_min"), filters.get("notice_max"))]

    locations = [item.lower() for item in filters.get("locations") or [] if item]
    if locations:
        rows = [row for row in rows if (row.location or "").lower() in locations]

    rows = _contains(rows, "name", filters.get("name"))
    rows = _contains(rows, "email", filters.get("email"))
    rows = _contains(rows, "phone", filters.get("phone"))
    rows = _contains(rows, "skills", filters.get("skills"))
    rows = _contains(rows, "matching_skills", filters.get("matching"))
    rows = _contains(rows, "missing_skills", filters.get("missing"))
    rows = _contains(rows, "company", filters.get("company"))

    score_min = _optional_int(filters.get("score_min"))
    score_max = _optional_int(filters.get("score_max"))
    if score_min is not None:
        rows = [row for row in rows if row.score is not None and row.score >= score_min]
    if score_max is not None:
        rows = [row for row in rows if row.score is not None and row.score <= score_max]
    return _sort_rows(rows, filters.get("sort") or "score", filters.get("direction") or "desc")


def locations_in(profiles: list[JdProfile]) -> list[str]:
    found = sorted({row.location for row in profiles if row.location})
    return found


def _weights(workspace: JdWorkspace) -> dict[str, int]:
    try:
        data = json.loads(workspace.weights_json or "{}")
    except json.JSONDecodeError:
        data = {}
    weights = default_weights()
    weights.update({key: int(value) for key, value in data.items() if key in weights})
    return weights


def _contains(rows: list[JdProfile], attr: str, query: str | None) -> list[JdProfile]:
    needle = (query or "").strip().lower()
    if not needle:
        return rows
    return [row for row in rows if needle in (getattr(row, attr) or "").lower()]


def _optional_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _in_notice_range(days: int | None, minimum, maximum) -> bool:
    if days is None:
        return False
    low = _optional_int(minimum)
    high = _optional_int(maximum)
    if low is not None and days < low:
        return False
    if high is not None and days > high:
        return False
    return True


def _sort_rows(rows: list[JdProfile], sort_key: str, direction: str) -> list[JdProfile]:
    allowed = {
        "score",
        "name",
        "email",
        "phone",
        "location",
        "skills",
        "matching_skills",
        "missing_skills",
        "company",
        "notice_days",
    }
    key = sort_key if sort_key in allowed else "score"
    reverse = direction != "asc"

    def value(row: JdProfile):
        raw = getattr(row, key)
        if raw is None:
            return (1, "")
        if isinstance(raw, str):
            return (0, raw.lower())
        return (0, raw)

    return sorted(rows, key=value, reverse=reverse)
