"""Turn a job description into an editable portal search plan."""

from __future__ import annotations

import re

from app.jd_rank import JobNeeds, parse_job_description
from app.profile_fields import SKILL_SYNONYMS, canonicalize_skill

TITLE_HINTS = (
    ("java", "Java Developer"),
    ("python", "Python Developer"),
    ("javascript", "Frontend Engineer"),
    ("react", "Frontend Engineer"),
    ("kubernetes", "DevOps Engineer"),
    ("spring boot", "Backend Engineer"),
)


def build_search_plan(jd_text: str) -> dict:
    job = parse_job_description(jd_text or "")
    must = [_skill_entry(skill) for skill in job.must_have]
    nice = [_skill_entry(skill) for skill in job.nice_to_have]
    titles = _titles(jd_text, job)
    notice = _notice_preference(jd_text)
    plan = {
        "must_have": must,
        "nice_to_have": nice,
        "titles": titles,
        "min_years": job.min_years,
        "max_years": job.max_years,
        "locations": list(job.locations),
        "notice": notice,
        "queries": {},
    }
    plan["queries"] = portal_queries(plan)
    enriched = _llm_titles(jd_text, plan)
    if enriched:
        plan["titles"] = enriched
        plan["queries"] = portal_queries(plan)
    return plan


def portal_queries(plan: dict) -> dict[str, str]:
    must = _names(plan.get("must_have") or [])
    nice = _names(plan.get("nice_to_have") or [])
    titles = [title for title in plan.get("titles") or [] if title]
    locations = [city for city in plan.get("locations") or [] if city]
    return {
        "generic": _and_list(must or nice),
        "naukri": _comma_list(must + titles[:1] + locations[:1]),
        "linkedin": _linkedin(must, nice, titles, locations),
        "indeed": _indeed(must, titles, locations),
    }


def normalize_plan(raw: dict) -> dict:
    """Keep only the fields the UI is allowed to edit."""
    plan = {
        "must_have": _clean_entries(raw.get("must_have")),
        "nice_to_have": _clean_entries(raw.get("nice_to_have")),
        "titles": _clean_strings(raw.get("titles")),
        "min_years": _optional_year(raw.get("min_years")),
        "max_years": _optional_year(raw.get("max_years")),
        "locations": _clean_strings(raw.get("locations")),
        "notice": str(raw.get("notice") or "").strip()[:80],
        "queries": {},
    }
    supplied = raw.get("queries") if isinstance(raw.get("queries"), dict) else {}
    generated = portal_queries(plan)
    plan["queries"] = {
        key: str(supplied.get(key) or generated[key]).strip()[:500]
        for key in generated
    }
    return plan


def _skill_entry(skill: str) -> dict:
    canonical = canonicalize_skill(skill)
    variants = []
    for name, phrases in SKILL_SYNONYMS.items():
        if name == canonical or canonical in phrases:
            variants.extend(phrases)
    if canonical and canonical not in variants:
        variants.append(canonical)
    unique = []
    for variant in variants:
        if variant not in unique:
            unique.append(variant)
    return {"skill": canonical, "variants": unique}


def _titles(jd_text: str, job: JobNeeds) -> list[str]:
    found = []
    first = ""
    for line in (jd_text or "").splitlines():
        stripped = line.strip()
        if stripped:
            first = stripped[:80]
            break
    if first and not first.lower().startswith("must"):
        found.append(first.split(",")[0].strip())
    skills = set(job.must_have)
    for skill, title in TITLE_HINTS:
        if skill in skills and title not in found:
            found.append(title)
    if not found:
        found.append("Software Engineer")
    return found[:6]


def _notice_preference(text: str) -> str:
    match = re.search(r"notice(?:\s+period)?[^.\n]{0,40}", text or "", re.I)
    return match.group(0).strip()[:80] if match else ""


def _llm_titles(jd_text: str, plan: dict) -> list[str] | None:
    from app.config import get_settings

    if not get_settings().gemini_api_key or not (jd_text or "").strip():
        return None
    from app.ai_gateway import _gemini_generate, _parse_json_object

    prompt = (
        "Suggest up to 4 job titles that match this job description. "
        "Reply JSON only: {\"titles\":[\"...\"]}. Do not invent employers or people.\n\n"
        f"{jd_text[:2000]}"
    )
    try:
        data = _parse_json_object(_gemini_generate(prompt))
    except Exception:
        return None
    titles = _clean_strings(data.get("titles") if isinstance(data, dict) else None)
    return titles[:4] or plan["titles"]


def _names(entries: list) -> list[str]:
    names = []
    for entry in entries:
        if isinstance(entry, dict):
            skill = str(entry.get("skill") or "").strip()
        else:
            skill = str(entry).strip()
        if skill and skill not in names:
            names.append(skill)
    return names


def _and_list(skills: list[str]) -> str:
    return " AND ".join(skills)


def _comma_list(parts: list[str]) -> str:
    return ", ".join(part for part in parts if part)


def _or_group(skill: str, variants: list[str] | None = None) -> str:
    choices = variants or [skill]
    quoted = [f'"{item}"' if " " in item else item for item in choices]
    if len(quoted) == 1:
        return quoted[0]
    return "(" + " OR ".join(quoted) + ")"


def _linkedin(must: list[str], nice: list[str], titles: list[str], locations: list[str]) -> str:
    parts = [_or_group(skill) for skill in must[:5]]
    if titles:
        parts.append(_or_group(titles[0], titles[:3]))
    if locations:
        parts.append(locations[0])
    if nice:
        parts.append("optional " + " OR ".join(nice[:3]))
    return " AND ".join(parts)


def _indeed(must: list[str], titles: list[str], locations: list[str]) -> str:
    terms = must[:4] + titles[:1]
    query = " AND ".join(f'"{term}"' if " " in term else term for term in terms)
    if locations:
        query = f"{query} {locations[0]}".strip()
    return query


def _clean_entries(value) -> list[dict]:
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",") if part.strip()]
    if not isinstance(value, list):
        return []
    entries = []
    for item in value:
        if isinstance(item, dict):
            skill = canonicalize_skill(str(item.get("skill") or ""))
            variants = _clean_strings(item.get("variants"))
        else:
            skill = canonicalize_skill(str(item))
            variants = []
        if not skill:
            continue
        if skill not in variants:
            variants.insert(0, skill)
        entries.append({"skill": skill, "variants": variants[:8]})
    return entries[:20]


def _clean_strings(value) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"[\n,]+", value)
    if not isinstance(value, list):
        return []
    cleaned = []
    for item in value:
        text = str(item).strip()
        if text and text not in cleaned:
            cleaned.append(text[:80])
    return cleaned[:12]


def _optional_year(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    if year < 0 or year > 50:
        return None
    return year
