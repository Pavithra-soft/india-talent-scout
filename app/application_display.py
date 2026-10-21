"""Merge application form fields with values read from the uploaded resume."""

from __future__ import annotations

from dataclasses import dataclass

from app.models import JobApplication
from app.profile_fields import normalize_email, normalize_phone
from app.profile_parse import fields_from_resume_text


@dataclass
class ApplicationView:
    name: str
    email: str
    phone: str
    years_experience: str
    skills: str
    location: str
    company: str


def application_view(application: JobApplication) -> ApplicationView:
    parsed = (
        fields_from_resume_text(application.resume_extracted_text)
        if application.resume_extracted_text
        else {}
    )
    name = _first(application.name, parsed.get("name"))
    email = _first(
        normalize_email(application.email) if application.email else "",
        parsed.get("email") or "",
    )
    phone = _first(
        normalize_phone(application.phone) if application.phone else "",
        parsed.get("phone") or "",
    )
    years = application.years_experience
    if years is None:
        years = parsed.get("years_experience")
    years_text = str(years) if years is not None else "—"
    skills = _first(application.skills, parsed.get("skills") or "")
    location = parsed.get("location") or ""
    company = parsed.get("company") or ""
    return ApplicationView(
        name=name or "—",
        email=email or "—",
        phone=phone or "—",
        years_experience=years_text,
        skills=skills or "—",
        location=location or "—",
        company=company or "—",
    )


def _first(*values: str) -> str:
    for value in values:
        text = (value or "").strip()
        if text:
            return text
    return ""
