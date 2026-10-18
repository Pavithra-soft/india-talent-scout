"""Approved search plans, portal hits, and browser-side downloads."""

from __future__ import annotations

import csv
import io
import time
import zipfile
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session

from app.auth import require_recruiter, session_owner_key
from app.config import get_settings
from app.database import get_db
from app.jd_store import ReplaceRequired, ensure_workspace, get_workspace
from app.portal_connectors import CsvImportConnector
from app.portal_store import (
    connector_status,
    download_payload,
    find_similar,
    import_profiles,
    list_hits,
    list_plans,
    run_search,
    save_api_config,
    remember_last_plan,
    save_plan,
    send_to_analysis,
)
from app.search_plan import build_search_plan, normalize_plan

router = APIRouter(prefix="/recruit/jd/portals", tags=["portal-search"])
BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
_SEARCH_HITS: dict[str, list[float]] = {}


def _guard(request: Request) -> str:
    require_recruiter(request)
    return session_owner_key(request)


def _limit(owner_key: str) -> None:
    now = time.time()
    recent = [stamp for stamp in _SEARCH_HITS.get(owner_key, []) if now - stamp < 60]
    if len(recent) >= 20:
        raise HTTPException(status_code=429, detail="Too many portal searches. Wait a minute and try again.")
    recent.append(now)
    _SEARCH_HITS[owner_key] = recent


def _filters(
    notice: str = "any",
    locations: List[str] = Query(default=[]),
    skills: str = "",
    company: str = "",
    score_min: str = "",
    years_min: str = "",
    years_max: str = "",
) -> dict:
    return {
        "notice": notice or "any",
        "locations": locations or [],
        "skills": skills,
        "company": company,
        "score_min": score_min,
        "years_min": years_min,
        "years_max": years_max,
        "sort": "score",
        "direction": "desc",
    }


def _remember_jd(db: Session, owner_key: str, jd_text: str, confirm: bool) -> None:
    workspace = ensure_workspace(db, owner_key)
    text = (jd_text or "").strip()
    if not text:
        return
    if workspace.jd_text and text != workspace.jd_text and workspace.portal_hits and not confirm:
        raise ReplaceRequired()
    if workspace.jd_text and text != workspace.jd_text and confirm:
        for hit in list(workspace.portal_hits):
            db.delete(hit)
        for plan in list(workspace.search_plans):
            db.delete(plan)
    workspace.jd_text = text
    db.commit()


@router.get("", response_class=HTMLResponse)
def portal_page(
    request: Request,
    db: Session = Depends(get_db),
    notice: str = "any",
    locations: List[str] = Query(default=[]),
    skills: str = "",
    company: str = "",
    score_min: str = "",
    years_min: str = "",
    years_max: str = "",
    message: str = "",
):
    owner_key = _guard(request)
    workspace = get_workspace(db, owner_key)
    filters = _filters(notice, locations, skills, company, score_min, years_min, years_max)
    hits = list_hits(db, owner_key, filters)
    places = sorted({row.location for row in (workspace.portal_hits if workspace else []) if row.location})
    plans = list_plans(db, owner_key)
    latest = None
    if plans:
        import json

        latest = json.loads(plans[0].plan_json)
        latest["approved"] = plans[0].approved
    return templates.TemplateResponse(
        request,
        "recruit/portal_search.html",
        {
            "workspace": workspace,
            "hits": hits,
            "plans": plans,
            "latest_plan": latest,
            "connectors": connector_status(db, owner_key),
            "locations": places,
            "filters": filters,
            "message": message,
            "llm_enabled": bool(get_settings().gemini_api_key),
            "export_query": request.url.query,
        },
    )


@router.post("/plan")
async def create_plan(
    request: Request,
    db: Session = Depends(get_db),
    jd_text: str = Form(""),
    confirm_replace: str = Form("0"),
):
    owner_key = _guard(request)
    try:
        _remember_jd(db, owner_key, jd_text, confirm_replace == "1")
    except ReplaceRequired:
        return JSONResponse(status_code=409, content={"need_confirm": True, "message": "Replace the current JD and its portal results?"})
    workspace = get_workspace(db, owner_key)
    text = (jd_text or (workspace.jd_text if workspace else "") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Paste a job description first.")
    return {"plan": build_search_plan(text)}


@router.post("/plan/save")
async def store_plan(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form("Search plan"),
    approved: str = Form("0"),
    plan_json: str = Form("{}"),
):
    owner_key = _guard(request)
    import json

    try:
        raw = json.loads(plan_json or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="The search plan is not valid JSON.") from exc
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="The search plan must be an object.")
    row = save_plan(db, owner_key, name, normalize_plan(raw), approved == "1")
    return RedirectResponse(f"/recruit/jd/portals?message=Saved+plan+{row.id}", status_code=303)


@router.post("/search")
async def search_portals(
    request: Request,
    db: Session = Depends(get_db),
    plan_json: str = Form("{}"),
    connectors: List[str] = Form(default=[]),
    jd_text: str = Form(""),
    confirm_replace: str = Form("0"),
    approved: str = Form("0"),
):
    owner_key = _guard(request)
    _limit(owner_key)
    if approved != "1":
        raise HTTPException(status_code=400, detail="Approve the search plan before searching.")
    import json

    try:
        _remember_jd(db, owner_key, jd_text, confirm_replace == "1")
    except ReplaceRequired:
        return JSONResponse(status_code=409, content={"need_confirm": True})
    try:
        plan = json.loads(plan_json or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Approve a search plan before searching.") from exc
    if not isinstance(plan, dict) or not plan:
        raise HTTPException(status_code=400, detail="Approve a search plan before searching.")
    keys = connectors or ["mock"]
    try:
        result = run_search(db, owner_key, plan, keys)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    remember_last_plan(db, owner_key, plan)
    if request.headers.get("accept", "").startswith("application/json"):
        return result
    note = " ".join(result["notes"])
    return RedirectResponse("/recruit/jd/portals?message=" + _query(f"Search saved {result['saved']} profiles. {note}"), status_code=303)


@router.post("/similar")
def similar(request: Request, db: Session = Depends(get_db), hit_id: int = Form(...)):
    owner_key = _guard(request)
    _limit(owner_key)
    try:
        find_similar(db, owner_key, hit_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse("/recruit/jd/portals?message=Similar+profiles+added", status_code=303)


@router.post("/import")
async def import_selected(request: Request, db: Session = Depends(get_db)):
    owner_key = _guard(request)
    _limit(owner_key)
    payload = await request.json()
    profiles = payload.get("profiles") if isinstance(payload, dict) else None
    if not isinstance(profiles, list):
        raise HTTPException(status_code=400, detail="Send a profiles list.")
    try:
        saved = import_profiles(db, owner_key, profiles[:100], str(payload.get("portal") or "extension")[:40])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"saved": saved}


@router.post("/csv")
async def import_csv(
    request: Request,
    db: Session = Depends(get_db),
    upload: Optional[UploadFile] = File(default=None),
):
    owner_key = _guard(request)
    if upload is None or not upload.filename:
        raise HTTPException(status_code=400, detail="Choose a CSV export.")
    text = (await upload.read()).decode("utf-8", errors="replace")
    profiles = CsvImportConnector().from_csv(text)
    try:
        saved = import_profiles(
            db,
            owner_key,
            [
                {
                    "portal": item.portal,
                    "portal_id": item.portal_id,
                    "name": item.name,
                    "email": item.email,
                    "phone": item.phone,
                    "company": item.company,
                    "location": item.location,
                    "skills": item.skills,
                    "years_experience": item.years_experience,
                    "notice": item.notice_raw,
                    "snippet": item.snippet,
                }
                for item in profiles
            ],
            "csv",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(f"/recruit/jd/portals?message=Imported+{saved}+rows", status_code=303)


@router.post("/api-config")
def save_api(
    request: Request,
    db: Session = Depends(get_db),
    base_url: str = Form(""),
    api_key: str = Form(""),
    enabled: str = Form("1"),
):
    owner_key = _guard(request)
    save_api_config(db, owner_key, base_url, api_key, enabled == "1")
    return RedirectResponse("/recruit/jd/portals?message=Licensed+API+settings+saved", status_code=303)


@router.post("/download")
def download_files(
    request: Request,
    db: Session = Depends(get_db),
    hit_ids: List[int] = Form(default=[]),
    force: str = Form("0"),
    per_jd_folder: str = Form("0"),
    top_n: str = Form(""),
):
    owner_key = _guard(request)
    ids = _selected_ids(db, owner_key, hit_ids, top_n)
    payload = download_payload(db, owner_key, ids, force=force == "1", per_jd_folder=per_jd_folder == "1")
    return payload


@router.post("/download.zip")
def download_zip(
    request: Request,
    db: Session = Depends(get_db),
    hit_ids: List[int] = Form(default=[]),
    force: str = Form("0"),
    per_jd_folder: str = Form("0"),
    top_n: str = Form(""),
):
    owner_key = _guard(request)
    ids = _selected_ids(db, owner_key, hit_ids, top_n)
    payload = download_payload(db, owner_key, ids, force=force == "1", per_jd_folder=per_jd_folder == "1")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        folder = payload["directory"]
        for item in payload["files"]:
            path = f"{folder}/{item['name']}" if folder else item["name"]
            archive.writestr(path, item["content"])
        log_buffer = io.StringIO()
        writer = csv.DictWriter(log_buffer, fieldnames=["id", "file", "status", "detail"])
        writer.writeheader()
        writer.writerows(payload["log"])
        archive.writestr(f"{folder}/download-log.csv" if folder else "download-log.csv", log_buffer.getvalue())
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=portal-profiles.zip"},
    )


@router.post("/download-log.csv")
def download_log(request: Request, db: Session = Depends(get_db), hit_ids: List[int] = Form(default=[])):
    owner_key = _guard(request)
    payload = download_payload(db, owner_key, hit_ids, force=False, per_jd_folder=False)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=["id", "file", "status", "detail"])
    writer.writeheader()
    writer.writerows(payload["log"])
    return Response(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=download-log.csv"},
    )


@router.post("/to-analysis")
def to_analysis(
    request: Request,
    db: Session = Depends(get_db),
    hit_ids: List[int] = Form(default=[]),
    top_n: str = Form(""),
):
    owner_key = _guard(request)
    ids = _selected_ids(db, owner_key, hit_ids, top_n)
    result = send_to_analysis(db, owner_key, ids)
    return RedirectResponse(f"/recruit/jd?notice=any", status_code=303) if result["added"] or result["skipped"] else RedirectResponse(
        "/recruit/jd/portals?message=Nothing+was+sent", status_code=303
    )


def _selected_ids(db: Session, owner_key: str, hit_ids: list[int], top_n: str) -> list[int]:
    if top_n.isdigit():
        rows = list_hits(db, owner_key, {"notice": "any", "sort": "score", "direction": "desc"})
        return [row.id for row in rows[: int(top_n)]]
    return hit_ids


def _query(text: str) -> str:
    from urllib.parse import quote

    return quote(text[:180])
