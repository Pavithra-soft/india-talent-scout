from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from app.auth import (
    COOKIE_NAME,
    MAX_AGE_SECONDS,
    check_password,
    create_session_token,
    is_recruiter_authenticated,
    require_recruiter,
)
from app.csv_import import import_csv, template_csv
from app.database import get_db
from app.models import Candidate, CandidateSource, JobPortal, Shortlist, ShortlistStatus
from app.portal_service import list_portals, save_portal_credentials, test_portal_connection
from app.search_service import SearchParams, search_candidates

router = APIRouter(prefix="/recruit", tags=["recruit"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _guard(request: Request):
    require_recruiter(request)


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    if is_recruiter_authenticated(request):
        return RedirectResponse(url="/recruit", status_code=303)
    return templates.TemplateResponse(request, "recruit/login.html", {"page": "recruit", "error": None})


@router.post("/login")
def login_submit(request: Request, password: str = Form(...)):
    if not check_password(password):
        return templates.TemplateResponse(
            request,
            "recruit/login.html",
            {"page": "recruit", "error": "Invalid password."},
            status_code=401,
        )
    response = RedirectResponse(url="/recruit", status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        create_session_token(),
        httponly=True,
        samesite="lax",
        max_age=MAX_AGE_SECONDS,
    )
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


@router.get("", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    _guard(request)
    total = db.query(Candidate).count()
    shortlist_count = db.query(Shortlist).count()
    return templates.TemplateResponse(
        request,
        "recruit/dashboard.html",
        {"page": "recruit", "total": total, "shortlist_count": shortlist_count},
    )


@router.get("/portals", response_class=HTMLResponse)
def portals_page(request: Request, db: Session = Depends(get_db), saved: str = "", tested: str = ""):
    _guard(request)
    portals = list_portals(db)
    flash = None
    if saved:
        flash = f"Credentials saved for {saved}."
    if tested:
        flash = tested
    return templates.TemplateResponse(
        request,
        "recruit/portals.html",
        {"page": "recruit", "portals": portals, "flash": flash},
    )


@router.post("/portals/{portal_key}/credentials")
def portals_save_credentials(
    request: Request,
    portal_key: str,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    _guard(request)
    _portal, message = save_portal_credentials(db, portal_key, username, password)
    return templates.TemplateResponse(
        request,
        "recruit/portals.html",
        {
            "page": "recruit",
            "portals": list_portals(db),
            "flash": message,
        },
    )


@router.post("/portals/{portal_key}/test")
def portals_test(request: Request, portal_key: str, db: Session = Depends(get_db)):
    _guard(request)
    message = test_portal_connection(db, portal_key)
    return templates.TemplateResponse(
        request,
        "recruit/portals.html",
        {"page": "recruit", "portals": list_portals(db), "flash": message},
    )


@router.get("/search", response_class=HTMLResponse)
def search_form(
    request: Request,
    db: Session = Depends(get_db),
    skills: str = "",
    city: str = "",
    min_years: str = "",
    max_years: str = "",
    active_days: str = "30",
    source: str = "",
    job_brief: str = "",
    run: str = "",
    sync_portals: str = "",
    include_local: str = "1",
    portals: list[str] = Query(default=[]),
):
    _guard(request)
    portal_keys = [p for p in portals if p]
    params = SearchParams(
        skills=skills,
        city=city or None,
        min_years=int(min_years) if min_years.isdigit() else None,
        max_years=int(max_years) if max_years.isdigit() else None,
        active_days=int(active_days) if active_days.isdigit() else 30,
        source=source or None,
        job_brief=job_brief or None,
        portal_keys=portal_keys or None,
        include_local_pool=include_local == "1",
        sync_portals=sync_portals == "1",
    )
    results: list = []
    sync_messages: list[str] = []
    if run == "1":
        results, sync_messages = search_candidates(db, params)
    all_portals = list_portals(db)
    return templates.TemplateResponse(
        request,
        "recruit/search.html",
        {
            "page": "recruit",
            "params": params,
            "results": results,
            "sync_messages": sync_messages,
            "all_portals": all_portals,
            "selected_portals": set(portal_keys),
        },
    )


@router.get("/candidates/{candidate_id}", response_class=HTMLResponse)
def candidate_detail(request: Request, candidate_id: int, db: Session = Depends(get_db)):
    _guard(request)
    candidate = (
        db.query(Candidate)
        .options(joinedload(Candidate.resume), joinedload(Candidate.shortlists))
        .filter(Candidate.id == candidate_id)
        .first()
    )
    if not candidate:
        return templates.TemplateResponse(request, "error.html", {"message": "Candidate not found"}, status_code=404)
    shortlist = candidate.shortlists[0] if candidate.shortlists else None
    preview = ""
    if candidate.resume:
        preview = candidate.resume.extracted_text[:2000]
    elif candidate.profile_summary:
        preview = candidate.profile_summary
    return templates.TemplateResponse(
        request,
        "recruit/candidate_detail.html",
        {"page": "recruit", "candidate": candidate, "preview": preview, "shortlist": shortlist},
    )


@router.post("/candidates/{candidate_id}/shortlist")
def shortlist_update(
    request: Request,
    candidate_id: int,
    status: str = Form(ShortlistStatus.NEW.value),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    _guard(request)
    candidate = db.get(Candidate, candidate_id)
    if not candidate:
        return RedirectResponse(url="/recruit/search", status_code=303)
    existing = db.query(Shortlist).filter(Shortlist.candidate_id == candidate_id).first()
    now = datetime.now(timezone.utc)
    if existing:
        existing.status = status
        existing.notes = notes or None
        existing.updated_at = now
    else:
        db.add(
            Shortlist(
                candidate_id=candidate_id,
                status=status,
                notes=notes or None,
                updated_at=now,
            )
        )
    db.commit()
    return RedirectResponse(url=f"/recruit/candidates/{candidate_id}", status_code=303)


@router.get("/shortlist", response_class=HTMLResponse)
def shortlist_view(request: Request, db: Session = Depends(get_db)):
    _guard(request)
    rows = (
        db.query(Shortlist)
        .options(joinedload(Shortlist.candidate))
        .order_by(Shortlist.updated_at.desc())
        .all()
    )
    return templates.TemplateResponse(request, "recruit/shortlist.html", {"page": "recruit", "rows": rows})


@router.get("/import", response_class=HTMLResponse)
def import_form(request: Request):
    _guard(request)
    return templates.TemplateResponse(
        request,
        "recruit/import.html",
        {"page": "recruit", "result": None},
    )


@router.get("/import/template.csv")
def import_template(request: Request):
    _guard(request)
    return Response(
        content=template_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="candidates_template.csv"'},
    )


@router.post("/import", response_class=HTMLResponse)
async def import_submit(request: Request, file: UploadFile, db: Session = Depends(get_db)):
    _guard(request)
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    result = import_csv(db, raw)
    return templates.TemplateResponse(
        request,
        "recruit/import.html",
        {"page": "recruit", "result": result},
    )
