from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import JobApplication, JobPosting
from app.profile_fields import normalize_email, normalize_notice_period, normalize_phone
from app.profile_parse import fields_from_resume_text
from app.resume_parser import extract_text_from_bytes, heuristic_skills

_EMAIL_RE = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.IGNORECASE)


def create_job_posting(db: Session, *, title: str, jd_text: str) -> JobPosting:
    title = title.strip()
    jd_text = jd_text.strip()
    if not title:
        raise ValueError("Job title is required.")
    if not jd_text:
        raise ValueError("Job description is required.")
    now = datetime.now(timezone.utc)
    posting = JobPosting(
        title=title,
        jd_text=jd_text,
        share_token=secrets.token_urlsafe(16),
        is_active=True,
        created_at=now,
    )
    db.add(posting)
    db.commit()
    db.refresh(posting)
    return posting


def get_posting_by_token(db: Session, token: str) -> JobPosting | None:
    return db.query(JobPosting).filter(JobPosting.share_token == token).first()


def get_posting(db: Session, posting_id: int) -> JobPosting | None:
    return db.query(JobPosting).filter(JobPosting.id == posting_id).first()


def submit_application(
    db: Session,
    posting: JobPosting,
    *,
    name: str,
    email: str,
    phone: str,
    years_experience: int | None,
    notice_period: str,
    skills: str | None,
    additional_notes: str | None,
    file_content: bytes | None,
    filename: str | None,
    content_type: str | None,
) -> JobApplication:
    if not posting.is_active:
        raise ValueError("This job is no longer accepting applications.")

    notice_period = (notice_period or "").strip()
    if not notice_period:
        raise ValueError("Notice period is required.")
    if not file_content:
        raise ValueError("Resume upload is required.")

    extracted = extract_text_from_bytes(file_content, filename or "resume.txt", content_type)
    if not (extracted or "").strip():
        raise ValueError("Could not read text from the resume. Try PDF, DOCX, or TXT.")

    parsed = fields_from_resume_text(extracted)

    name = (name or "").strip() or (parsed.get("name") or "").strip()
    email_raw = (email or "").strip().lower()
    if email_raw:
        if not _EMAIL_RE.match(email_raw):
            raise ValueError("Enter a valid email address or leave it blank to use the one on your resume.")
        email_stored = normalize_email(email_raw) or email_raw
    else:
        email_stored = normalize_email(parsed.get("email") or "") or (parsed.get("email") or "").strip().lower()

    phone_raw = (phone or "").strip()
    if phone_raw:
        phone_stored = normalize_phone(phone_raw) or phone_raw
    else:
        phone_stored = normalize_phone(parsed.get("phone") or "") or (parsed.get("phone") or "").strip()

    years = years_experience
    if years is None:
        years = parsed.get("years_experience")
    if years is not None and (years < 0 or years > 50):
        raise ValueError("Years of experience must be between 0 and 50.")

    notice_raw, notice_days = normalize_notice_period(notice_period)

    settings = get_settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(filename or "upload.txt").suffix or ".txt"
    stored_name = f"jobapp_{uuid.uuid4().hex}{ext}"
    path = settings.storage_dir / stored_name
    path.write_bytes(file_content)
    stored_path = str(path)
    original_filename = filename

    skill_text = heuristic_skills(extracted, skills or "")
    if not skill_text and parsed.get("skills"):
        skill_text = parsed.get("skills") or ""

    application = JobApplication(
        posting_id=posting.id,
        name=name,
        email=email_stored,
        phone=phone_stored,
        years_experience=years,
        skills=skill_text,
        notice_raw=notice_raw or notice_period,
        notice_days=notice_days,
        additional_notes=(additional_notes or "").strip(),
        applied_at=datetime.now(timezone.utc),
        resume_stored_path=stored_path,
        resume_content_type=content_type,
        resume_original_filename=original_filename,
        resume_extracted_text=extracted,
    )
    db.add(application)
    db.commit()
    db.refresh(application)
    return application


def delete_application_resume(db: Session, application: JobApplication) -> None:
    _remove_resume_file(application.resume_stored_path)
    application.resume_stored_path = None
    application.resume_content_type = None
    application.resume_original_filename = None
    application.resume_extracted_text = ""
    db.commit()


def delete_application(db: Session, application: JobApplication) -> None:
    _remove_resume_file(application.resume_stored_path)
    db.delete(application)
    db.commit()


def _remove_resume_file(stored_path: str | None) -> None:
    if not stored_path:
        return
    path = Path(stored_path)
    if path.is_file():
        path.unlink(missing_ok=True)
