from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.ai_gateway import extract_resume_insights
from app.config import get_settings
from app.models import Candidate, CandidateSource, ResumeArtifact
from app.resume_parser import (
    build_search_blob,
    extract_text_from_bytes,
    heuristic_skills,
)


def create_opt_in_candidate(
    db: Session,
    *,
    name: str,
    email: str,
    phone: str | None,
    city: str | None,
    years_experience: int | None,
    manual_skills: str | None,
    consent: bool,
    file_content: bytes | None,
    filename: str | None,
    content_type: str | None,
) -> Candidate:
    if not consent:
        raise ValueError("Consent is required to join the talent pool.")

    extracted = ""
    stored_path: str | None = None
    original_filename = filename

    if file_content:
        extracted = extract_text_from_bytes(file_content, filename or "resume.txt", content_type)
        settings = get_settings()
        settings.storage_dir.mkdir(parents=True, exist_ok=True)
        ext = Path(filename or "upload.txt").suffix or ".txt"
        stored_name = f"{uuid.uuid4().hex}{ext}"
        path = settings.storage_dir / stored_name
        path.write_bytes(file_content)
        stored_path = str(path)

    ai_skills, summary = extract_resume_insights(extracted) if extracted else ("", "")
    skills = heuristic_skills(extracted, manual_skills) if manual_skills else ai_skills
    if manual_skills and manual_skills.strip():
        skills = heuristic_skills(extracted, manual_skills)
    if not skills and ai_skills:
        skills = ai_skills

    now = datetime.now(timezone.utc)
    search_blob = build_search_blob(name, skills, city, extracted, summary)

    candidate = Candidate(
        name=name.strip(),
        email=email.strip().lower(),
        phone=phone.strip() if phone else None,
        city=city.strip() if city else None,
        years_experience=years_experience,
        skills=skills,
        source=CandidateSource.OPT_IN.value,
        source_portal=None,
        last_active_at=now,
        created_at=now,
        consent=True,
        profile_summary=summary or None,
        search_blob=search_blob,
    )
    db.add(candidate)
    db.flush()
    db.add(
        ResumeArtifact(
            candidate_id=candidate.id,
            stored_path=stored_path,
            content_type=content_type,
            original_filename=original_filename,
            extracted_text=extracted,
        )
    )
    db.commit()
    db.refresh(candidate)
    return candidate
