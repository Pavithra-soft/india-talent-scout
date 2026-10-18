"""Turn one resume file into structured fields. Original bytes are not stored."""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass, field

from app.profile_fields import (
    email_in_text,
    find_company,
    find_email,
    find_location,
    find_name,
    find_notice_period,
    find_phone,
    find_years,
    normalize_email,
    normalize_phone,
    phone_digits_in_text,
    skill_set,
)
from app.resume_parser import extract_text_from_bytes, heuristic_skills

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_ZIP_FILES = 500
MAX_ZIP_UNCOMPRESSED = 50 * 1024 * 1024
ALLOWED_SUFFIXES = {".pdf", ".docx", ".doc", ".txt", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".zip"}


@dataclass
class ParsedProfile:
    filename: str
    file_hash: str
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    skills: str = ""
    company: str = ""
    notice_raw: str = ""
    notice_days: int | None = None
    years_experience: int | None = None
    error: str = ""


@dataclass
class BatchResult:
    profiles: list[ParsedProfile] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def parse_upload(filename: str, content: bytes) -> BatchResult:
    result = BatchResult()
    safe_name = _safe_name(filename)
    suffix = _suffix(safe_name)
    if suffix not in ALLOWED_SUFFIXES:
        result.errors.append(f"{safe_name}: unsupported file type.")
        return result
    if len(content) > MAX_FILE_BYTES and suffix != ".zip":
        result.errors.append(f"{safe_name}: file is larger than 8 MB.")
        return result
    if _looks_like_executable(content):
        result.errors.append(f"{safe_name}: file was rejected by the upload check.")
        return result
    if suffix == ".zip":
        return _parse_zip(safe_name, content)
    profile = _parse_one(safe_name, content)
    if profile.error:
        result.errors.append(f"{safe_name}: {profile.error}")
    else:
        result.profiles.append(profile)
    return result


def _parse_zip(filename: str, content: bytes) -> BatchResult:
    result = BatchResult()
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        result.errors.append(f"{filename}: zip file is unreadable.")
        return result
    total = 0
    count = 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        count += 1
        if count > MAX_ZIP_FILES:
            result.errors.append(f"{filename}: zip has more than {MAX_ZIP_FILES} files.")
            break
        total += info.file_size
        if total > MAX_ZIP_UNCOMPRESSED:
            result.errors.append(f"{filename}: zip expands beyond the size limit.")
            break
        inner_name = _safe_name(info.filename)
        if _suffix(inner_name) == ".zip":
            result.errors.append(f"{inner_name}: nested zip files are skipped.")
            continue
        if _suffix(inner_name) not in ALLOWED_SUFFIXES:
            result.errors.append(f"{inner_name}: unsupported file type.")
            continue
        if info.file_size > MAX_FILE_BYTES:
            result.errors.append(f"{inner_name}: file is larger than 8 MB.")
            continue
        extracted = archive.read(info)
        if _looks_like_executable(extracted):
            result.errors.append(f"{inner_name}: file was rejected by the upload check.")
            continue
        profile = _parse_one(inner_name, extracted)
        if profile.error:
            result.errors.append(f"{inner_name}: {profile.error}")
        else:
            result.profiles.append(profile)
    return result


def _parse_one(filename: str, content: bytes) -> ParsedProfile:
    profile = ParsedProfile(filename=filename, file_hash=file_hash(content))
    try:
        text = _extract_text(filename, content)
    except Exception as exc:
        profile.error = str(exc) or "could not read this file."
        return profile
    text = (text or "").strip()
    if not text:
        profile.error = "no text could be read from this file."
        return profile
    fields = _fields_from_text(text)
    profile.name = fields["name"]
    profile.email = fields["email"]
    profile.phone = fields["phone"]
    profile.location = fields["location"]
    profile.skills = fields["skills"]
    profile.company = fields["company"]
    profile.notice_raw = fields["notice_raw"]
    profile.notice_days = fields["notice_days"]
    profile.years_experience = fields["years_experience"]
    return profile


def _extract_text(filename: str, content: bytes) -> str:
    suffix = _suffix(filename)
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        return _ocr_image(content)
    if suffix == ".doc":
        raise ValueError("legacy .doc could not be read; save it as DOCX or PDF.")
    text = extract_text_from_bytes(content, filename, None)
    if suffix == ".pdf" and not text.strip():
        ocr_text = _ocr_pdf(content)
        if ocr_text:
            return ocr_text
        raise ValueError("scanned PDF has no text. Install Tesseract and Poppler for OCR.")
    return text


def _ocr_image(content: bytes) -> str:
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise ValueError("image resumes need Pillow and Tesseract, which are not installed.") from exc
    image = Image.open(io.BytesIO(content))
    text = pytesseract.image_to_string(image) or ""
    if not text.strip():
        raise ValueError("OCR could not read text from this image.")
    return text


def _ocr_pdf(content: bytes) -> str:
    try:
        import pytesseract
        from pdf2image import convert_from_bytes
    except ImportError:
        return ""
    try:
        pages = convert_from_bytes(content, first_page=1, last_page=3)
    except Exception:
        return ""
    parts = [pytesseract.image_to_string(page) or "" for page in pages]
    return "\n".join(parts).strip()


def _fields_from_text(text: str) -> dict:
    heuristic = {
        "name": find_name(text),
        "email": find_email(text),
        "phone": find_phone(text),
        "location": find_location(text),
        "skills": heuristic_skills(text, None),
        "company": find_company(text),
        "years_experience": find_years(text),
    }
    notice_raw, notice_days = find_notice_period(text)
    heuristic["notice_raw"] = notice_raw
    heuristic["notice_days"] = notice_days
    enriched = _llm_fields(text)
    if not enriched:
        return heuristic
    return _merge_known_fields(heuristic, enriched, text)


def _llm_fields(text: str) -> dict | None:
    from app.config import get_settings

    if not get_settings().gemini_api_key:
        return None
    from app.ai_gateway import extract_structured_profile

    try:
        return extract_structured_profile(text)
    except Exception:
        return None


def _merge_known_fields(heuristic: dict, extracted: dict, text: str) -> dict:
    merged = dict(heuristic)
    name = (extracted.get("name") or "").strip()
    if name and name.lower() in text.lower():
        merged["name"] = name[:80]
    email = normalize_email(extracted.get("email") or "")
    if email and email_in_text(email, text):
        merged["email"] = email
    phone = normalize_phone(extracted.get("phone") or "")
    if phone and phone_digits_in_text(phone, text):
        merged["phone"] = phone
    location = (extracted.get("location") or "").strip()
    if location and location.lower() in text.lower():
        merged["location"] = location[:80]
    company = (extracted.get("company") or "").strip()
    if company and company.lower() in text.lower():
        merged["company"] = company[:120]
    notice_raw, notice_days = find_notice_period(str(extracted.get("notice_period") or ""))
    if notice_raw and notice_raw.lower() in text.lower():
        merged["notice_raw"] = notice_raw
        merged["notice_days"] = notice_days
    skills = extracted.get("skills") or []
    if isinstance(skills, str):
        skills = [part.strip() for part in skills.split(",")]
    kept = [skill for skill in skills if skill and skill.lower() in text.lower()]
    if kept:
        merged["skills"] = ", ".join(sorted(skill_set(kept)))
    years = extracted.get("years_experience")
    if isinstance(years, int) and 0 <= years <= 50 and str(years) in text:
        merged["years_experience"] = years
    return merged


def _safe_name(filename: str) -> str:
    name = (filename or "resume").replace("\\", "/").split("/")[-1].strip()
    name = name.replace("..", "")
    return name or "resume"


def _suffix(filename: str) -> str:
    dot = filename.rfind(".")
    if dot < 0:
        return ""
    return filename[dot:].lower()


def _looks_like_executable(content: bytes) -> bool:
    sample = content[:4]
    return sample.startswith(b"MZ") or sample.startswith(b"\x7fELF")
