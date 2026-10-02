from __future__ import annotations

import io
import re
from pathlib import Path

from docx import Document
from pypdf import PdfReader

TECH_KEYWORDS = [
    "java", "spring", "kafka", "keycloak", "python", "fastapi", "django",
    "react", "angular", "node", "typescript", "javascript", "aws", "azure",
    "gcp", "kubernetes", "docker", "postgres", "mysql", "mongodb", "redis",
    "microservices", "rest", "graphql", "scala", "kotlin", "go", "golang",
    "devops", "terraform", "ansible", "ci/cd", "spark", "hadoop", "sql",
    "oracle", "hibernate", "jpa", "spring boot", "spring ai", "gemini",
    "openai", "machine learning", "data engineering", "etl", "airflow",
]


def extract_text_from_bytes(content: bytes, filename: str, content_type: str | None) -> str:
    lower = (filename or "").lower()
    if lower.endswith(".txt") or (content_type and "text/plain" in content_type):
        return content.decode("utf-8", errors="replace")
    if lower.endswith(".pdf") or (content_type and "pdf" in content_type):
        return _pdf_text(content)
    if lower.endswith(".docx") or (content_type and "word" in (content_type or "")):
        return _docx_text(content)
    if lower.endswith(".doc"):
        raise ValueError("Legacy .doc is not supported; upload PDF, DOCX, or TXT.")
    raise ValueError("Unsupported file type. Use PDF, DOCX, or TXT.")


def extract_text_from_path(path: Path, content_type: str | None) -> str:
    return extract_text_from_bytes(path.read_bytes(), path.name, content_type)


def _pdf_text(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    parts = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _docx_text(content: bytes) -> str:
    doc = Document(io.BytesIO(content))
    return "\n".join(p.text for p in doc.paragraphs if p.text).strip()


def heuristic_skills(text: str, manual_skills: str | None = None) -> str:
    if manual_skills and manual_skills.strip():
        return _normalize_skills_list(manual_skills)
    haystack = (text or "").lower()
    found = []
    for kw in TECH_KEYWORDS:
        if kw in haystack and kw not in found:
            found.append(kw)
    return ", ".join(found[:25])


def _normalize_skills_list(raw: str) -> str:
    tokens = re.split(r"[,;/|]+", raw)
    cleaned = []
    seen = set()
    for t in tokens:
        s = t.strip().lower()
        if s and s not in seen:
            seen.add(s)
            cleaned.append(s)
    return ", ".join(cleaned)


def build_search_blob(
    name: str,
    skills: str,
    city: str | None,
    extracted_text: str,
    profile_summary: str | None,
) -> str:
    parts = [name or "", skills or "", city or "", profile_summary or "", extracted_text or ""]
    return "\n".join(parts).lower()
