"""JD match workspace: upload resumes, rank, filter, export, and save mail drafts."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import require_recruiter, session_owner_key
from app.config import get_settings
from app.database import get_db
from app.jd_rank import default_weights
from app.jd_store import (
    ReplaceRequired,
    add_profiles,
    clear_workspace,
    ensure_workspace,
    filter_profiles,
    get_workspace,
    load_filters,
    locations_in,
    rank_workspace,
    save_filters,
)
from app.mail_drafts import (
    MailError,
    MailNotConfigured,
    authorization_url,
    connections_for,
    create_draft,
    disconnect,
    exchange_code,
    google_ready,
    microsoft_ready,
    owner_from_state,
    recent_messages,
    render_reply,
)
from app.profile_parse import parse_upload
from app.excel_export import profiles_to_xlsx
from app.resume_parser import extract_text_from_bytes

router = APIRouter(prefix="/recruit/jd", tags=["jd-match"])
BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

_UPLOAD_HITS: dict[str, list[float]] = {}


def _guard(request: Request) -> str:
    require_recruiter(request)
    return session_owner_key(request)


def _limit(owner_key: str) -> None:
    now = time.time()
    recent = [stamp for stamp in _UPLOAD_HITS.get(owner_key, []) if now - stamp < 60]
    if len(recent) >= 40:
        raise HTTPException(status_code=429, detail="Too many uploads. Wait a minute and try again.")
    recent.append(now)
    _UPLOAD_HITS[owner_key] = recent


def _filters_from_query(
    notice: str = "any",
    notice_min: str = "",
    notice_max: str = "",
    locations: list[str] | None = None,
    name: str = "",
    email: str = "",
    phone: str = "",
    skills: str = "",
    matching: str = "",
    missing: str = "",
    company: str = "",
    score_min: str = "",
    score_max: str = "",
    sort: str = "score",
    direction: str = "desc",
) -> dict:
    return {
        "notice": notice or "any",
        "notice_min": notice_min,
        "notice_max": notice_max,
        "locations": locations or [],
        "name": name,
        "email": email,
        "phone": phone,
        "skills": skills,
        "matching": matching,
        "missing": missing,
        "company": company,
        "score_min": score_min,
        "score_max": score_max,
        "sort": sort or "score",
        "direction": direction or "desc",
    }


@router.get("", response_class=HTMLResponse)
def jd_page(
    request: Request,
    db: Session = Depends(get_db),
    notice: str = "any",
    notice_min: str = "",
    notice_max: str = "",
    locations: list[str] = Query(default=[]),
    name: str = "",
    email: str = "",
    phone: str = "",
    skills: str = "",
    matching: str = "",
    missing: str = "",
    company: str = "",
    score_min: str = "",
    score_max: str = "",
    sort: str = "score",
    direction: str = "desc",
    mail_status: str = "",
):
    owner_key = _guard(request)
    workspace = get_workspace(db, owner_key)
    filters = _filters_from_query(
        notice, notice_min, notice_max, locations, name, email, phone,
        skills, matching, missing, company, score_min, score_max, sort, direction,
    )
    profiles = list(workspace.profiles) if workspace else []
    filter_keys = {
        "notice", "notice_min", "notice_max", "locations", "name", "email", "phone",
        "skills", "matching", "missing", "company", "score_min", "score_max", "sort", "direction",
    }
    if workspace and any(key in request.query_params for key in filter_keys):
        save_filters(db, workspace, filters)
    elif workspace:
        filters = {**_filters_from_query(), **load_filters(workspace)}
    visible = filter_profiles(profiles, filters) if profiles else []
    weights = default_weights()
    if workspace and workspace.weights_json:
        import json

        try:
            weights.update(json.loads(workspace.weights_json))
        except json.JSONDecodeError:
            pass
    return templates.TemplateResponse(
        request,
        "recruit/jd_match.html",
        {
            "page": "recruit",
            "workspace": workspace,
            "profiles": visible,
            "profile_count": len(profiles),
            "locations": locations_in(profiles),
            "filters": filters,
            "weights": weights,
            "connections": connections_for(db, owner_key),
            "google_ready": google_ready(),
            "microsoft_ready": microsoft_ready(),
            "llm_enabled": bool(get_settings().gemini_api_key),
            "mail_status": mail_status,
            "export_query": request.url.query,
        },
    )


@router.post("/upload")
async def upload_profiles(
    request: Request,
    db: Session = Depends(get_db),
    files: list[UploadFile] = File(default=[]),
    confirm_replace: str = Form("0"),
    replace: str = Form("0"),
):
    owner_key = _guard(request)
    _limit(owner_key)
    parsed = []
    errors: list[str] = []
    for upload in files:
        content = await upload.read()
        batch = parse_upload(upload.filename or "resume", content)
        parsed.extend(batch.profiles)
        errors.extend(batch.errors)
    try:
        added, skipped, notes = add_profiles(
            db,
            owner_key,
            parsed,
            confirm_replace=confirm_replace == "1",
            replace=replace == "1",
        )
    except ReplaceRequired:
        return JSONResponse(
            status_code=409,
            content={"need_confirm": True, "message": "A profile set is already loaded. Replace it?"},
        )
    return {"added": added, "skipped": skipped, "errors": errors + notes, "count": added}


@router.post("/rank")
async def rank_profiles(
    request: Request,
    db: Session = Depends(get_db),
    jd_text: str = Form(""),
    jd_file: Optional[UploadFile] = File(default=None),
    confirm_replace: str = Form("0"),
    weight_must: int = Form(60),
    weight_nice: int = Form(20),
    weight_experience: int = Form(10),
    weight_location: int = Form(10),
):
    owner_key = _guard(request)
    text = (jd_text or "").strip()
    if jd_file and jd_file.filename:
        content = await jd_file.read()
        try:
            text = extract_text_from_bytes(content, jd_file.filename, jd_file.content_type).strip()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not text:
        raise HTTPException(status_code=400, detail="Paste or upload a job description.")
    workspace = ensure_workspace(db, owner_key)
    weights = {
        "must": weight_must,
        "nice": weight_nice,
        "experience": weight_experience,
        "location": weight_location,
    }
    try:
        job = rank_workspace(db, workspace, text, weights, confirm_replace=confirm_replace == "1")
    except ReplaceRequired:
        return JSONResponse(
            status_code=409,
            content={"need_confirm": True, "message": "Replace the current job description and scores?"},
        )
    return {
        "scored": len(workspace.profiles),
        "must_have": job.must_have,
        "nice_to_have": job.nice_to_have,
    }


@router.get("/export.xlsx")
def export_xlsx(
    request: Request,
    db: Session = Depends(get_db),
    scope: str = "filtered",
    notice: str = "any",
    notice_min: str = "",
    notice_max: str = "",
    locations: list[str] = Query(default=[]),
    name: str = "",
    email: str = "",
    phone: str = "",
    skills: str = "",
    matching: str = "",
    missing: str = "",
    company: str = "",
    score_min: str = "",
    score_max: str = "",
    sort: str = "score",
    direction: str = "desc",
):
    owner_key = _guard(request)
    workspace = get_workspace(db, owner_key)
    profiles = list(workspace.profiles) if workspace else []
    if scope != "all":
        filters = _filters_from_query(
            notice, notice_min, notice_max, locations, name, email, phone,
            skills, matching, missing, company, score_min, score_max, sort, direction,
        )
        profiles = filter_profiles(profiles, filters)
    content = profiles_to_xlsx(profiles)
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="ranked-profiles.xlsx"'},
    )


@router.post("/clear")
def clear_data(request: Request, db: Session = Depends(get_db)):
    owner_key = _guard(request)
    clear_workspace(db, owner_key)
    return RedirectResponse(url="/recruit/jd", status_code=303)


@router.get("/mail/{provider}")
def mail_connect(provider: str, request: Request):
    owner_key = _guard(request)
    if provider not in {"google", "microsoft"}:
        raise HTTPException(status_code=404, detail="Unknown mailbox.")
    try:
        return RedirectResponse(authorization_url(provider, owner_key), status_code=303)
    except MailNotConfigured as exc:
        return RedirectResponse(url=f"/recruit/jd?mail_status={quote(str(exc))}", status_code=303)


@router.get("/mail/{provider}/callback")
def mail_callback(provider: str, request: Request, db: Session = Depends(get_db), code: str = "", state: str = ""):
    _guard(request)
    try:
        owner_key = owner_from_state(state, provider)
        if owner_key != session_owner_key(request):
            raise MailError("This mailbox connection was started in a different session.")
        exchange_code(db, provider, owner_key, code)
    except (MailError, MailNotConfigured) as exc:
        return RedirectResponse(url=f"/recruit/jd?mail_status={quote(str(exc))}", status_code=303)
    return RedirectResponse(url=f"/recruit/jd?mail_status={quote('Mailbox connected.')}", status_code=303)


@router.post("/mail/{provider}/disconnect")
def mail_disconnect(provider: str, request: Request, db: Session = Depends(get_db)):
    owner_key = _guard(request)
    disconnect(db, owner_key, provider)
    return RedirectResponse(url=f"/recruit/jd?mail_status={quote('Mailbox disconnected.')}", status_code=303)


@router.post("/drafts")
def save_draft(
    request: Request,
    db: Session = Depends(get_db),
    profile_id: int = Form(...),
    tone: str = Form("formal"),
    template_key: str = Form("interest"),
    reply_context: str = Form(""),
    subject: str = Form(""),
    body: str = Form(""),
):
    owner_key = _guard(request)
    workspace = get_workspace(db, owner_key)
    profile = next((row for row in (workspace.profiles if workspace else []) if row.id == profile_id), None)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile is not in the current temporary set.")
    if not subject.strip() or not body.strip():
        subject, body = render_reply(profile, tone, template_key, reply_context)
    try:
        mailbox = create_draft(db, owner_key, profile, subject.strip(), body.strip())
    except MailNotConfigured as exc:
        return RedirectResponse(url=f"/recruit/jd?mail_status={quote(str(exc))}", status_code=303)
    except MailError as exc:
        return RedirectResponse(url=f"/recruit/jd?mail_status={quote(str(exc))}", status_code=303)
    return RedirectResponse(url=f"/recruit/jd?mail_status={quote('Draft saved in ' + mailbox + '.')}", status_code=303)


@router.get("/replies")
def load_replies(request: Request, db: Session = Depends(get_db), profile_id: int = 0):
    owner_key = _guard(request)
    workspace = get_workspace(db, owner_key)
    profile = next((row for row in (workspace.profiles if workspace else []) if row.id == profile_id), None)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile is not in the current temporary set.")
    try:
        messages = recent_messages(db, owner_key, profile.email)
    except (MailError, MailNotConfigured) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"messages": messages}
