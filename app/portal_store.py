"""Save search plans and portal hits in the recruiter's temporary workspace."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.crypto_service import decrypt_text, encrypt_text
from app.jd_store import ensure_workspace, filter_profiles, get_workspace
from app.models import PortalApiConfig, PortalHit, PortalSearchPlan, RecruitAudit
from app.portal_connectors import (
    ConnectorError,
    PortalProfile,
    available_connectors,
    connector_by_key,
)
from app.portal_results import dedupe_profiles, profile_filename, rank_hits, similar_plan
from app.profile_parse import parse_upload
from app.search_plan import normalize_plan

MAX_HITS = 200


def remember_last_plan(db: Session, owner_key: str, plan: dict) -> PortalSearchPlan:
    for row in list_plans(db, owner_key):
        if row.name == "Last search":
            row.plan_json = json.dumps(normalize_plan(plan))
            row.approved = True
            db.commit()
            return row
    return save_plan(db, owner_key, "Last search", plan, True)


def save_plan(db: Session, owner_key: str, name: str, plan: dict, approved: bool) -> PortalSearchPlan:
    workspace = ensure_workspace(db, owner_key)
    row = PortalSearchPlan(
        workspace_id=workspace.id,
        name=(name or "Search plan").strip()[:120] or "Search plan",
        plan_json=json.dumps(normalize_plan(plan)),
        approved=bool(approved),
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_plans(db: Session, owner_key: str) -> list[PortalSearchPlan]:
    workspace = get_workspace(db, owner_key)
    if not workspace:
        return []
    return (
        db.query(PortalSearchPlan)
        .filter(PortalSearchPlan.workspace_id == workspace.id)
        .order_by(PortalSearchPlan.id.desc())
        .all()
    )


def run_search(db: Session, owner_key: str, plan: dict, connector_keys: list[str]) -> dict:
    workspace = ensure_workspace(db, owner_key)
    if not (workspace.jd_text or "").strip():
        raise ValueError("Add a job description on the JD match page before searching.")
    clean = normalize_plan(plan)
    collected: list[PortalProfile] = []
    notes: list[str] = []
    quotas: list[dict] = []
    api_base, api_key = api_credentials(db, owner_key)
    for key in connector_keys:
        connector = connector_by_key(key, api_base, api_key)
        if connector is None or key == "csv_import":
            continue
        if not connector.enabled():
            notes.append(f"{connector.label} is off until a licensed API base URL and key are saved.")
            quotas.append({"key": connector.key, "label": connector.label, "enabled": False, "quota": None})
            continue
        try:
            found = connector.search(clean)
        except ConnectorError as exc:
            notes.append(str(exc))
            found = []
        collected.extend(found)
        quotas.append(
            {
                "key": connector.key,
                "label": connector.label,
                "enabled": True,
                "quota": connector.quota_remaining(),
            }
        )
    merged = dedupe_profiles(collected)
    ranked = rank_hits(workspace.jd_text, merged)
    saved = _upsert_hits(db, workspace.id, ranked)
    _audit(db, owner_key, "portal_search", f"portals={','.join(connector_keys)[:80]} hits={saved}")
    db.commit()
    return {"saved": saved, "notes": notes, "quotas": quotas}


def find_similar(db: Session, owner_key: str, hit_id: int) -> dict:
    hit = _owned_hit(db, owner_key, hit_id)
    if hit is None:
        raise ValueError("That profile is not in this workspace.")
    profile = _profile_from_hit(hit)
    plan = similar_plan(profile)
    result = run_search(db, owner_key, plan, ["mock"])
    result["notes"].insert(0, f"Similar search used skills from {hit.name}.")
    return result


def list_hits(db: Session, owner_key: str, filters: dict) -> list[PortalHit]:
    workspace = get_workspace(db, owner_key)
    if not workspace:
        return []
    rows = list(workspace.portal_hits)
    rows = filter_profiles(rows, filters)
    years_min = _optional_int(filters.get("years_min"))
    years_max = _optional_int(filters.get("years_max"))
    if years_min is not None:
        rows = [row for row in rows if row.years_experience is not None and row.years_experience >= years_min]
    if years_max is not None:
        rows = [row for row in rows if row.years_experience is not None and row.years_experience <= years_max]
    return rows


def import_profiles(db: Session, owner_key: str, profiles: list[dict], source: str) -> int:
    workspace = ensure_workspace(db, owner_key)
    if not (workspace.jd_text or "").strip():
        raise ValueError("Add a job description on the JD match page before importing.")
    built = []
    for index, raw in enumerate(profiles, start=1):
        if not isinstance(raw, dict):
            continue
        if any(key in raw for key in ("cookie", "cookies", "password", "authorization")):
            continue
        built.append(
            PortalProfile(
                portal=str(raw.get("portal") or source)[:40],
                portal_id=str(raw.get("portal_id") or f"{source}-{index}")[:80],
                name=str(raw.get("name") or "")[:200],
                email=str(raw.get("email") or "")[:320],
                phone=str(raw.get("phone") or "")[:40],
                company=str(raw.get("company") or "")[:200],
                location=str(raw.get("location") or "")[:120],
                skills=str(raw.get("skills") or "")[:500],
                years_experience=_optional_int(raw.get("years_experience")),
                notice_raw=str(raw.get("notice") or "")[:80],
                snippet=str(raw.get("snippet") or "")[:500],
            )
        )
    ranked = rank_hits(workspace.jd_text, dedupe_profiles(built))
    saved = _upsert_hits(db, workspace.id, ranked)
    _audit(db, owner_key, "portal_import", f"source={source} hits={saved}")
    db.commit()
    return saved


def download_payload(db: Session, owner_key: str, hit_ids: list[int], *, force: bool, per_jd_folder: bool) -> dict:
    workspace = get_workspace(db, owner_key)
    if not workspace:
        return {"directory": "", "files": [], "log": []}
    wanted = {int(item) for item in hit_ids}
    rows = [row for row in workspace.portal_hits if row.id in wanted]
    rows.sort(key=lambda row: (-(row.score or 0), row.name.lower()))
    directory = _folder_name(workspace.jd_text) if per_jd_folder else ""
    when = datetime.now(timezone.utc)
    files = []
    log = []
    for rank, row in enumerate(rows, start=1):
        filename = profile_filename(rank, row.name, row.portal, when)
        if row.downloaded and not force:
            log.append({"id": row.id, "file": filename, "status": "skipped", "detail": "Already downloaded."})
            continue
        try:
            content = _profile_from_hit(row).resume_text()
        except Exception:
            log.append({"id": row.id, "file": filename, "status": "failed", "detail": "Could not build the file."})
            continue
        row.downloaded = True
        files.append({"id": row.id, "name": filename, "content": content})
        log.append({"id": row.id, "file": filename, "status": "saved", "detail": ""})
    _audit(db, owner_key, "portal_download", f"saved={len(files)} skipped={sum(1 for item in log if item['status']=='skipped')}")
    db.commit()
    return {"directory": directory, "files": files, "log": log}


def send_to_analysis(db: Session, owner_key: str, hit_ids: list[int]) -> dict:
    from app.jd_store import add_profiles

    workspace = get_workspace(db, owner_key)
    if not workspace:
        return {"added": 0, "skipped": 0, "notes": ["Nothing to send."]}
    wanted = {int(item) for item in hit_ids}
    parsed = []
    notes = []
    when = datetime.now(timezone.utc)
    for rank, row in enumerate(sorted(workspace.portal_hits, key=lambda item: -(item.score or 0)), start=1):
        if row.id not in wanted:
            continue
        filename = profile_filename(rank, row.name, row.portal, when)
        batch = parse_upload(filename, _profile_from_hit(row).resume_text().encode("utf-8"))
        notes.extend(batch.errors)
        parsed.extend(profile for profile in batch.profiles if not profile.error)
    added, skipped, extra = add_profiles(db, owner_key, parsed, confirm_replace=True, replace=False)
    notes.extend(extra)
    _audit(db, owner_key, "portal_to_analysis", f"added={added}")
    db.commit()
    return {"added": added, "skipped": skipped, "notes": notes}


def save_api_config(db: Session, owner_key: str, base_url: str, api_key: str, enabled: bool) -> None:
    row = db.query(PortalApiConfig).filter(PortalApiConfig.owner_key == owner_key).one_or_none()
    if row is None:
        row = PortalApiConfig(owner_key=owner_key, base_url="", api_key_enc="", enabled=True)
        db.add(row)
    row.base_url = (base_url or "").strip()[:300]
    if api_key:
        row.api_key_enc = encrypt_text(api_key.strip())
    row.enabled = bool(enabled)
    db.commit()


def api_credentials(db: Session, owner_key: str) -> tuple[str, str]:
    row = db.query(PortalApiConfig).filter(PortalApiConfig.owner_key == owner_key).one_or_none()
    if row and row.enabled and row.base_url and row.api_key_enc:
        return row.base_url, decrypt_text(row.api_key_enc)
    return "", ""


def connector_status(db: Session, owner_key: str) -> list[dict]:
    base, key = api_credentials(db, owner_key)
    status = []
    for connector in available_connectors(base, key):
        status.append(
            {
                "key": connector.key,
                "label": connector.label,
                "enabled": connector.enabled() and (connector.key != "licensed_api" or bool(base and key)),
                "quota": connector.quota_remaining() if connector.enabled() else None,
            }
        )
    return status


def _upsert_hits(db: Session, workspace_id: int, ranked: list[dict]) -> int:
    existing = {
        (row.portal, row.portal_profile_id): row
        for row in db.query(PortalHit).filter(PortalHit.workspace_id == workspace_id).all()
    }
    saved = 0
    for item in ranked:
        if not item["name"] and not item["email"]:
            continue
        key = (item["portal"], item["portal_id"])
        row = existing.get(key)
        if row is None:
            if len(existing) >= MAX_HITS:
                break
            row = PortalHit(workspace_id=workspace_id, portal=item["portal"], portal_profile_id=item["portal_id"])
            db.add(row)
            existing[key] = row
        row.name = item["name"]
        row.email = item["email"]
        row.phone = item["phone"]
        row.company = item["company"]
        row.location = item["location"]
        row.skills = item["skills"]
        row.years_experience = item["years_experience"]
        row.notice_raw = item["notice_raw"]
        row.notice_days = item["notice_days"]
        row.snippet = item["snippet"]
        row.score = item["score"]
        row.matching_skills = item["matching_skills"]
        row.missing_skills = item["missing_skills"]
        row.rationale = item["rationale"]
        saved += 1
    return saved


def _owned_hit(db: Session, owner_key: str, hit_id: int) -> PortalHit | None:
    workspace = get_workspace(db, owner_key)
    if not workspace:
        return None
    return (
        db.query(PortalHit)
        .filter(PortalHit.workspace_id == workspace.id, PortalHit.id == hit_id)
        .one_or_none()
    )


def _profile_from_hit(row: PortalHit) -> PortalProfile:
    return PortalProfile(
        portal=row.portal,
        portal_id=row.portal_profile_id,
        name=row.name,
        email=row.email,
        phone=row.phone,
        company=row.company,
        location=row.location,
        skills=row.skills,
        years_experience=row.years_experience,
        notice_raw=row.notice_raw,
        notice_days=row.notice_days,
        snippet=row.snippet,
    )


def _audit(db: Session, owner_key: str, action: str, detail: str) -> None:
    db.add(
        RecruitAudit(
            owner_key=owner_key,
            action=action[:40],
            detail=detail[:300],
            created_at=datetime.now(timezone.utc),
        )
    )


def _folder_name(jd_text: str) -> str:
    first = ""
    for line in (jd_text or "").splitlines():
        if line.strip():
            first = line.strip()
            break
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", first).strip("-")
    return (cleaned or "jd")[:40]


def _optional_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
