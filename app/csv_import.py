from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Candidate, CandidateSource, ResumeArtifact
from app.resume_parser import build_search_blob, heuristic_skills

CSV_HEADERS = [
    "name",
    "email",
    "phone",
    "city",
    "years_experience",
    "skills",
    "last_active_at",
    "source_portal",
    "resume_url_or_notes",
    "profile_summary",
]

TEMPLATE_ROW = {
    "name": "Priya Sharma",
    "email": "priya@example.com",
    "phone": "+91-9876543210",
    "city": "Bengaluru",
    "years_experience": "12",
    "skills": "java,spring,kafka",
    "last_active_at": "2026-03-01",
    "source_portal": "naukri",
    "resume_url_or_notes": "Exported from Resdex",
    "profile_summary": "Technical lead, payments platform",
}


@dataclass
class ImportResult:
    imported: int = 0
    errors: list[str] = field(default_factory=list)


def template_csv() -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_HEADERS)
    writer.writeheader()
    writer.writerow(TEMPLATE_ROW)
    return buf.getvalue()


def import_csv(db: Session, content: str) -> ImportResult:
    result = ImportResult()
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        result.errors.append("Row 0: empty or invalid CSV")
        return result

    normalized_headers = {_normalize_header(h): h for h in reader.fieldnames if h}
    for idx, row in enumerate(reader, start=2):
        try:
            _import_row(db, row, normalized_headers, idx, result)
        except ValueError as e:
            result.errors.append(f"Row {idx}: {e}")
    if result.imported:
        db.commit()
    return result


def _normalize_header(h: str) -> str:
    return h.strip().lower().replace(" ", "_")


def _import_row(db: Session, row: dict, headers: dict, row_num: int, result: ImportResult) -> None:
    def col(name: str) -> str:
        key = headers.get(name)
        if not key:
            return ""
        return (row.get(key) or "").strip()

    name = col("name")
    email = col("email")
    if not name or not email:
        raise ValueError("name and email are required")

    skills_raw = col("skills")
    profile_summary = col("profile_summary") or col("resume_url_or_notes")
    years_raw = col("years_experience")
    years = int(years_raw) if years_raw.isdigit() else None

    last_active = _parse_date(col("last_active_at")) or datetime.now(timezone.utc)
    skills = heuristic_skills(profile_summary, skills_raw)
    if not skills and skills_raw:
        skills = skills_raw.lower()

    extracted = profile_summary or ""
    search_blob = build_search_blob(name, skills, col("city") or None, extracted, profile_summary)

    candidate = Candidate(
        name=name,
        email=email,
        phone=col("phone") or None,
        city=col("city") or None,
        years_experience=years,
        skills=skills,
        source=CandidateSource.CSV.value,
        source_portal=col("source_portal") or None,
        last_active_at=last_active,
        created_at=datetime.now(timezone.utc),
        consent=True,
        profile_summary=profile_summary or None,
        search_blob=search_blob,
    )
    db.add(candidate)
    db.flush()
    db.add(
        ResumeArtifact(
            candidate_id=candidate.id,
            stored_path=None,
            content_type=None,
            original_filename=None,
            extracted_text=extracted,
        )
    )
    result.imported += 1


def _parse_date(raw: str) -> datetime | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(raw.replace("Z", "+0000"), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None
