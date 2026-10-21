from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.application_display import application_view
from app.application_export import applications_to_xlsx, applications_to_zip
from app.auth import require_recruiter
from app.database import get_db
from app.job_application_service import (
    create_job_posting,
    delete_application,
    delete_application_resume,
    get_posting,
    get_posting_by_token,
    submit_application,
)
from app.models import JobApplication, JobPosting

router = APIRouter(tags=["job-postings"])
recruit_router = APIRouter(prefix="/recruit/jobs", tags=["recruit-jobs"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _apply_url(request: Request, token: str) -> str:
    return str(request.url_for("apply_form", token=token))


def _guard(request: Request):
    require_recruiter(request)


@router.get("/apply/{token}", response_class=HTMLResponse, name="apply_form")
def apply_form(request: Request, token: str, db: Session = Depends(get_db), success: str = ""):
    posting = get_posting_by_token(db, token)
    if not posting:
        return templates.TemplateResponse(
            request,
            "apply.html",
            {"page": "apply", "posting": None, "error": None, "success": False},
            status_code=404,
        )
    return templates.TemplateResponse(
        request,
        "apply.html",
        {
            "page": "apply",
            "posting": posting,
            "error": None,
            "success": success == "1",
            "share_url": _apply_url(request, token),
        },
    )


@router.post("/apply/{token}")
async def apply_submit(
    request: Request,
    token: str,
    name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    years_experience: str = Form(""),
    notice_period: str = Form(...),
    skills: str = Form(""),
    additional_notes: str = Form(""),
    resume: Optional[UploadFile] = None,
    db: Session = Depends(get_db),
):
    posting = get_posting_by_token(db, token)
    if not posting:
        return templates.TemplateResponse(
            request,
            "apply.html",
            {"page": "apply", "posting": None, "error": "This job link is invalid.", "success": False},
            status_code=404,
        )

    years: Optional[int] = None
    if years_experience.strip().isdigit():
        years = int(years_experience.strip())
    elif years_experience.strip():
        return templates.TemplateResponse(
            request,
            "apply.html",
            {
                "page": "apply",
                "posting": posting,
                "error": "Years of experience must be a whole number, or leave it blank.",
                "success": False,
                "share_url": _apply_url(request, token),
            },
            status_code=400,
        )
    content = None
    filename = None
    content_type = None
    if resume and resume.filename:
        content = await resume.read()
        filename = resume.filename
        content_type = resume.content_type
    if not content:
        return templates.TemplateResponse(
            request,
            "apply.html",
            {
                "page": "apply",
                "posting": posting,
                "error": "Resume upload is required.",
                "success": False,
                "share_url": _apply_url(request, token),
            },
            status_code=400,
        )

    try:
        submit_application(
            db,
            posting,
            name=name,
            email=email,
            phone=phone,
            years_experience=years,
            notice_period=notice_period,
            skills=skills or None,
            additional_notes=additional_notes or None,
            file_content=content,
            filename=filename,
            content_type=content_type,
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "apply.html",
            {
                "page": "apply",
                "posting": posting,
                "error": str(exc),
                "success": False,
                "share_url": _apply_url(request, token),
            },
            status_code=400,
        )

    return RedirectResponse(url=f"/apply/{token}?success=1", status_code=303)


@recruit_router.get("", response_class=HTMLResponse)
def jobs_list(request: Request, db: Session = Depends(get_db)):
    _guard(request)
    postings = db.query(JobPosting).order_by(JobPosting.created_at.desc()).all()
    return templates.TemplateResponse(
        request,
        "recruit/jobs.html",
        {"page": "recruit", "postings": postings, "error": None},
    )


@recruit_router.post("")
def jobs_create(
    request: Request,
    title: str = Form(...),
    jd_text: str = Form(...),
    db: Session = Depends(get_db),
):
    _guard(request)
    try:
        posting = create_job_posting(db, title=title, jd_text=jd_text)
    except ValueError as exc:
        postings = db.query(JobPosting).order_by(JobPosting.created_at.desc()).all()
        return templates.TemplateResponse(
            request,
            "recruit/jobs.html",
            {"page": "recruit", "postings": postings, "error": str(exc)},
            status_code=400,
        )
    return RedirectResponse(url=f"/recruit/jobs/{posting.id}", status_code=303)


@recruit_router.get("/{posting_id}", response_class=HTMLResponse)
def job_detail(request: Request, posting_id: int, db: Session = Depends(get_db)):
    _guard(request)
    posting = get_posting(db, posting_id)
    if not posting:
        return RedirectResponse(url="/recruit/jobs", status_code=303)
    applications = (
        db.query(JobApplication)
        .filter(JobApplication.posting_id == posting_id)
        .order_by(JobApplication.applied_at.desc())
        .all()
    )
    apply_link = _apply_url(request, posting.share_token)
    mail_subject = f"Apply: {posting.title}"
    mail_body = f"Apply for this role:\n\n{apply_link}"
    application_rows = [(app, application_view(app)) for app in applications]
    return templates.TemplateResponse(
        request,
        "recruit/job_detail.html",
        {
            "page": "recruit",
            "posting": posting,
            "application_rows": application_rows,
            "apply_link": apply_link,
            "mailto_href": f"mailto:?subject={_url_quote(mail_subject)}&body={_url_quote(mail_body)}",
        },
    )


@recruit_router.post("/{posting_id}/toggle")
def job_toggle_active(request: Request, posting_id: int, db: Session = Depends(get_db)):
    _guard(request)
    posting = get_posting(db, posting_id)
    if posting:
        posting.is_active = not posting.is_active
        db.commit()
    return RedirectResponse(url=f"/recruit/jobs/{posting_id}", status_code=303)


@recruit_router.get("/{posting_id}/export.xlsx")
def job_export_xlsx(request: Request, posting_id: int, db: Session = Depends(get_db)):
    _guard(request)
    posting = get_posting(db, posting_id)
    if not posting:
        return RedirectResponse(url="/recruit/jobs", status_code=303)
    applications = db.query(JobApplication).filter(JobApplication.posting_id == posting_id).all()
    data = applications_to_xlsx(posting, applications)
    filename = f"applications_{posting_id}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@recruit_router.get("/{posting_id}/export.zip")
def job_export_zip(request: Request, posting_id: int, db: Session = Depends(get_db)):
    _guard(request)
    posting = get_posting(db, posting_id)
    if not posting:
        return RedirectResponse(url="/recruit/jobs", status_code=303)
    applications = db.query(JobApplication).filter(JobApplication.posting_id == posting_id).all()
    data = applications_to_zip(posting, applications)
    filename = f"applications_{posting_id}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@recruit_router.get("/{posting_id}/applications/{application_id}/resume")
def application_resume_download(
    request: Request,
    posting_id: int,
    application_id: int,
    db: Session = Depends(get_db),
):
    _guard(request)
    application = _get_application(db, posting_id, application_id)
    if not application or not application.resume_stored_path:
        return RedirectResponse(url=f"/recruit/jobs/{posting_id}", status_code=303)
    path = Path(application.resume_stored_path)
    if not path.is_file():
        return RedirectResponse(url=f"/recruit/jobs/{posting_id}", status_code=303)
    return FileResponse(
        path,
        filename=application.resume_original_filename or path.name,
        media_type=application.resume_content_type or "application/octet-stream",
    )


@recruit_router.post("/{posting_id}/applications/{application_id}/delete-resume")
def application_delete_resume(
    request: Request,
    posting_id: int,
    application_id: int,
    db: Session = Depends(get_db),
):
    _guard(request)
    application = _get_application(db, posting_id, application_id)
    if application:
        delete_application_resume(db, application)
    return RedirectResponse(url=f"/recruit/jobs/{posting_id}", status_code=303)


@recruit_router.post("/{posting_id}/applications/{application_id}/delete")
def application_delete(
    request: Request,
    posting_id: int,
    application_id: int,
    db: Session = Depends(get_db),
):
    _guard(request)
    application = _get_application(db, posting_id, application_id)
    if application:
        delete_application(db, application)
    return RedirectResponse(url=f"/recruit/jobs/{posting_id}", status_code=303)


def _get_application(db: Session, posting_id: int, application_id: int) -> Optional[JobApplication]:
    return (
        db.query(JobApplication)
        .filter(JobApplication.id == application_id, JobApplication.posting_id == posting_id)
        .first()
    )


def _url_quote(text: str) -> str:
    from urllib.parse import quote

    return quote(text, safe="")
