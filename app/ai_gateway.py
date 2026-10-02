from __future__ import annotations

import json
import logging
import re

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)


def extract_resume_insights(text: str) -> tuple[str, str]:
    """Returns (skills_csv, summary). Falls back to heuristics on failure."""
    settings = get_settings()
    if not settings.gemini_api_key or not text.strip():
        from app.resume_parser import heuristic_skills

        return heuristic_skills(text, None), _heuristic_summary(text)

    prompt = (
        "Extract skills (comma-separated lowercase) and a 2-sentence summary from this resume. "
        'Reply JSON only: {"skills":"...","summary":"..."}\n\n'
        f"Resume:\n{text[:8000]}"
    )
    try:
        raw = _gemini_generate(prompt)
        data = _parse_json_object(raw)
        skills = (data.get("skills") or "").strip()
        summary = (data.get("summary") or "").strip()
        if not skills:
            from app.resume_parser import heuristic_skills

            skills = heuristic_skills(text, None)
        if not summary:
            summary = _heuristic_summary(text)
        return skills, summary
    except Exception as e:
        log.warning("Gemini resume extract failed: %s", e)
        from app.resume_parser import heuristic_skills

        return heuristic_skills(text, None), _heuristic_summary(text)


def rerank_candidates(job_brief: str, candidates: list[dict]) -> list[int]:
    """Returns ordered candidate ids. On failure, returns original order."""
    if not candidates:
        return []
    settings = get_settings()
    if not settings.gemini_api_key:
        return [c["id"] for c in candidates]

    lines = []
    for c in candidates[:20]:
        lines.append(
            f"id={c['id']}; skills={c.get('skills','')}; "
            f"years={c.get('years_experience')}; snippet={c.get('snippet','')[:400]}"
        )
    prompt = (
        "Rank these candidates for the job brief. Reply JSON only: "
        '{"ordered_ids":[1,2,...]}\n\n'
        f"Job brief:\n{job_brief[:2000]}\n\nCandidates:\n" + "\n".join(lines)
    )
    try:
        raw = _gemini_generate(prompt)
        data = _parse_json_object(raw)
        ordered = data.get("ordered_ids") or []
        valid = [int(x) for x in ordered if isinstance(x, (int, float, str)) and str(x).isdigit()]
        seen = set()
        result = []
        for cid in valid:
            if cid not in seen:
                seen.add(cid)
                result.append(cid)
        for c in candidates:
            if c["id"] not in seen:
                result.append(c["id"])
        return result
    except Exception as e:
        log.warning("Gemini rerank failed: %s", e)
        return [c["id"] for c in candidates]


def _heuristic_summary(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return "Profile submitted."
    return " ".join(lines[:3])[:500]


def _gemini_generate(prompt: str) -> str:
    settings = get_settings()
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.gemini_model}:generateContent?key={settings.gemini_api_key}"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2},
    }
    with httpx.Client(timeout=45.0) as client:
        resp = client.post(url, json=body)
        resp.raise_for_status()
        data = resp.json()
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts)


def _parse_json_object(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)
