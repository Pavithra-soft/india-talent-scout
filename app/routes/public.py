from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.candidate_service import create_opt_in_candidate
from app.database import get_db

router = APIRouter(tags=["public"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return templates.TemplateResponse(request, "index.html", {"page": "home"})


@router.get("/join", response_class=HTMLResponse)
def join_form(request: Request, success: str = ""):
    return templates.TemplateResponse(
        request,
        "join.html",
        {"page": "join", "error": None, "success": success == "1"},
    )


@router.post("/join")
async def join_submit(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(""),
    city: str = Form(""),
    years_experience: str = Form(""),
    skills: str = Form(""),
    consent: str = Form(""),
    resume: Optional[UploadFile] = None,
    db: Session = Depends(get_db),
):
    years = int(years_experience) if years_experience.strip().isdigit() else None
    content = None
    filename = None
    content_type = None
    if resume and resume.filename:
        content = await resume.read()
        filename = resume.filename
        content_type = resume.content_type

    try:
        create_opt_in_candidate(
            db,
            name=name,
            email=email,
            phone=phone or None,
            city=city or None,
            years_experience=years,
            manual_skills=skills or None,
            consent=consent == "yes",
            file_content=content,
            filename=filename,
            content_type=content_type,
        )
    except ValueError as e:
        return templates.TemplateResponse(
            request,
            "join.html",
            {"page": "join", "error": str(e)},
            status_code=400,
        )
    except Exception as e:
        return templates.TemplateResponse(
            request,
            "join.html",
            {"page": "join", "error": f"Could not process profile: {e}"},
            status_code=400,
        )

    return RedirectResponse(url="/join?success=1", status_code=303)
