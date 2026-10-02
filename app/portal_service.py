from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session, joinedload

from app.models import Candidate, CandidateSource, JobPortal, PortalCredential, ResumeArtifact
from app.plugins import ExternalCandidate, SearchCriteria
from app.portal_registry import DEFAULT_PORTALS
from app.portals.base import get_connector
from app.resume_parser import build_search_blob
from app.crypto_service import decrypt_text, encrypt_text


@dataclass
class PortalSyncReport:
    messages: list[str] = field(default_factory=list)
    total_imported: int = 0


def ensure_portals(db: Session) -> None:
    existing = {p.key for p in db.query(JobPortal).all()}
    for definition in DEFAULT_PORTALS:
        if definition.key in existing:
            continue
        db.add(
            JobPortal(
                key=definition.key,
                name=definition.name,
                login_url=definition.login_url,
                recruiter_home_url=definition.recruiter_home_url,
                notes=definition.notes,
                enabled=True,
            )
        )
    db.commit()


def list_portals(db: Session) -> list[JobPortal]:
    ensure_portals(db)
    return db.query(JobPortal).options(joinedload(JobPortal.credential)).order_by(JobPortal.name).all()


def save_portal_credentials(db: Session, portal_key: str, username: str, password: str) -> tuple[JobPortal, str]:
    ensure_portals(db)
    portal = db.query(JobPortal).filter(JobPortal.key == portal_key).one()
    enc_user = encrypt_text(username.strip())
    enc_pass = encrypt_text(password)
    if portal.credential:
        portal.credential.username_enc = enc_user
        portal.credential.password_enc = enc_pass
        portal.credential.last_error = None
    else:
        db.add(
            PortalCredential(
                portal_id=portal.id,
                username_enc=enc_user,
                password_enc=enc_pass,
                enabled=True,
            )
        )
    db.commit()
    db.refresh(portal)
    connector = get_connector(portal_key)
    if not connector:
        return portal, "Unknown portal connector."
    username_plain = username.strip()
    auth = connector.authenticate(username_plain, password)
    cred = portal.credential
    if cred and auth.ok:
        cred.authenticated_at = datetime.now(timezone.utc)
        cred.last_error = None
    elif cred:
        cred.authenticated_at = None
        cred.last_error = auth.message
    db.commit()
    return portal, auth.message


def test_portal_connection(db: Session, portal_key: str) -> str:
    portal = db.query(JobPortal).filter(JobPortal.key == portal_key).first()
    if not portal or not portal.credential:
        return "Save credentials first."
    connector = get_connector(portal_key)
    if not connector:
        return "No connector for this portal."
    username = decrypt_text(portal.credential.username_enc)
    password = decrypt_text(portal.credential.password_enc)
    auth = connector.authenticate(username, password)
    cred = portal.credential
    if auth.ok:
        cred.authenticated_at = datetime.now(timezone.utc)
        cred.last_error = None
    else:
        cred.authenticated_at = None
        cred.last_error = auth.message
    db.commit()
    return auth.message


def _upsert_external(db: Session, external: ExternalCandidate) -> bool:
    existing = (
        db.query(Candidate)
        .filter(Candidate.email == external.email.lower(), Candidate.source_portal == external.source_portal)
        .first()
    )
    now = datetime.now(timezone.utc)
    summary = f"Pulled from {external.source_portal}: {external.skills}"
    extracted = summary
    blob = build_search_blob(external.name, external.skills, external.city, extracted, summary)
    if existing:
        existing.name = external.name
        existing.skills = external.skills
        existing.city = external.city
        existing.years_experience = external.years_experience
        existing.last_active_at = now
        existing.search_blob = blob
        existing.profile_summary = summary
        if existing.resume:
            existing.resume.extracted_text = extracted
        return False
    candidate = Candidate(
        name=external.name,
        email=external.email.lower(),
        city=external.city,
        years_experience=external.years_experience,
        skills=external.skills,
        source=CandidateSource.PORTAL.value,
        source_portal=external.source_portal,
        last_active_at=now,
        created_at=now,
        consent=True,
        profile_summary=summary,
        search_blob=blob,
    )
    db.add(candidate)
    db.flush()
    db.add(ResumeArtifact(candidate_id=candidate.id, extracted_text=extracted))
    return True


def pull_from_portals(db: Session, portal_keys: list[str], criteria: SearchCriteria) -> PortalSyncReport:
    report = PortalSyncReport()
    ensure_portals(db)
    for key in portal_keys:
        portal = db.query(JobPortal).filter(JobPortal.key == key, JobPortal.enabled.is_(True)).first()
        if not portal:
            report.messages.append(f"{key}: portal not found.")
            continue
        if not portal.credential or not portal.credential.enabled:
            report.messages.append(f"{portal.name}: add username/password on Portals page.")
            continue
        connector = get_connector(key)
        if not connector:
            report.messages.append(f"{portal.name}: connector not implemented.")
            continue
        username = decrypt_text(portal.credential.username_enc)
        password = decrypt_text(portal.credential.password_enc)
        auth = connector.authenticate(username, password)
        if not auth.ok:
            portal.credential.last_error = auth.message
            report.messages.append(f"{portal.name}: {auth.message}")
            db.commit()
            continue
        portal.credential.authenticated_at = datetime.now(timezone.utc)
        portal.credential.last_error = None
        pulled = connector.search_resumes(username, password, criteria)
        imported = 0
        for ext in pulled:
            if _upsert_external(db, ext):
                imported += 1
        portal.credential.last_sync_at = datetime.now(timezone.utc)
        report.total_imported += imported
        report.messages.append(f"{portal.name}: synced {len(pulled)} profile(s), {imported} new.")
    db.commit()
    return report
