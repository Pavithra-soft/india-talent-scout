from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application_display import application_view
from app.database import get_db
from app.main import app
from app.models import Base, JobApplication
from app.job_application_service import (
    create_job_posting,
    delete_application,
    delete_application_resume,
    submit_application,
)

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_RESUME = ROOT / "samples" / "resumes" / "ananya-rao.txt"


def _client_with_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), session_factory


def test_submit_application_requires_resume_and_notice():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    posting = create_job_posting(db, title="Engineer", jd_text="Build APIs")
    resume = SAMPLE_RESUME.read_bytes()

    try:
        submit_application(
            db,
            posting,
            name="",
            email="",
            phone="",
            years_experience=None,
            notice_period="",
            skills=None,
            additional_notes=None,
            file_content=resume,
            filename="resume.txt",
            content_type="text/plain",
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "Notice period" in str(exc)

    try:
        submit_application(
            db,
            posting,
            name="",
            email="",
            phone="",
            years_experience=None,
            notice_period="30 days",
            skills=None,
            additional_notes=None,
            file_content=None,
            filename=None,
            content_type=None,
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "Resume" in str(exc)

    db.close()


def test_resume_parses_optional_fields():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    posting = create_job_posting(db, title="Engineer", jd_text="Build APIs")
    application = submit_application(
        db,
        posting,
        name="",
        email="",
        phone="",
        years_experience=None,
        notice_period="45 days",
        skills=None,
        additional_notes=None,
        file_content=SAMPLE_RESUME.read_bytes(),
        filename="ananya-rao.txt",
        content_type="text/plain",
    )
    view = application_view(application)
    assert "Ananya" in view.name
    assert "ananya.rao@example.com" in view.email
    assert view.years_experience == "8"
    assert "java" in view.skills.lower()
    assert application.notice_raw == "45 days"
    db.close()


def test_apply_flow_and_cleanup(tmp_path, monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("DEMO_SEED", "false")

    client, session_factory = _client_with_db()
    db = session_factory()
    posting = create_job_posting(db, title="QA Lead", jd_text="Test software")
    db.close()

    response = client.get(f"/apply/{posting.share_token}")
    assert response.status_code == 200
    assert "QA Lead" in response.text

    response = client.post(
        f"/apply/{posting.share_token}",
        data={"notice_period": "60 days"},
        files={"resume": ("ananya-rao.txt", SAMPLE_RESUME.read_bytes(), "text/plain")},
        follow_redirects=False,
    )
    assert response.status_code == 303

    db = session_factory()
    application = db.query(JobApplication).one()
    view = application_view(application)
    assert "Ananya" in view.name
    assert application.notice_raw == "60 days"

    delete_application_resume(db, application)
    db.refresh(application)
    assert application.resume_stored_path is None

    delete_application(db, application)
    assert db.query(JobApplication).count() == 0
    db.close()

    app.dependency_overrides.clear()
    get_settings.cache_clear()
