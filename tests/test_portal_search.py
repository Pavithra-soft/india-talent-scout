import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import COOKIE_NAME, create_session_token
from app.database import get_db
from app.main import app
from app.models import Base
from app.portal_connectors import LicensedApiConnector, MockPortalConnector, PortalProfile
from app.portal_results import dedupe_profiles, profile_filename
from app.search_plan import build_search_plan, portal_queries

JD = "Backend engineer, Bengaluru\n\nMust-have: Java, Spring Boot, Kafka\nExperience: 5-9 years\nLocation: Bengaluru\n"


def test_search_plan_lists_skills_titles_and_portal_queries():
    plan = build_search_plan(JD)
    skills = [entry["skill"] for entry in plan["must_have"]]
    assert "java" in skills
    assert "spring boot" in skills
    assert plan["min_years"] == 5
    assert "Bengaluru" in plan["locations"]
    assert "Backend engineer" in plan["titles"]
    queries = portal_queries(plan)
    assert "java" in queries["naukri"]
    assert "AND" in queries["linkedin"]
    assert "Bengaluru" in queries["indeed"]


def test_dedupe_collapses_same_email_and_same_name_company():
    first = PortalProfile("mock", "1", "Ananya Rao", "ananya.rao@example.com", "", "Infosys", skills="java")
    second = PortalProfile("other", "2", "Ananya Rao", "ananya.rao@example.com", "+919876543210", "Infosys", skills="java, kafka")
    third = PortalProfile("mock", "3", "Ananya Rao", "", "", "Infosys", skills="java")
    merged = dedupe_profiles([first, second, third])
    assert len(merged) == 1
    assert merged[0].phone == "+919876543210"
    assert "kafka" in merged[0].skills


def test_profile_filename_uses_rank_name_portal_and_date():
    when = datetime(2026, 10, 18, tzinfo=timezone.utc)
    assert profile_filename(3, "Ananya Rao", "mock", when) == "03_AnanyaRao_mock_20261018.txt"


def test_mock_connector_filters_on_the_plan():
    plan = build_search_plan(JD)
    found = MockPortalConnector().search(plan)
    names = [profile.name for profile in found]
    assert "Ananya Rao" in names
    assert "Rahul Menon" not in names


def test_licensed_connector_reads_partner_json():
    payload = {"quota_remaining": 7, "profiles": [{"id": "p1", "name": "Kavya Nair", "skills": "java", "location": "Bengaluru"}]}
    response = MagicMock(status_code=200)
    response.json.return_value = payload
    client = MagicMock()
    client.__enter__.return_value.get.return_value = response
    with patch("app.portal_connectors.httpx.Client", return_value=client):
        connector = LicensedApiConnector("https://partner.example", "secret")
        found = connector.search({"queries": {"generic": "java"}})
    assert connector.quota_remaining() == 7
    assert found[0].name == "Kavya Nair"
    assert found[0].portal == "licensed_api"


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def override():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    with TestClient(app) as test_client:
        test_client.cookies.set(COOKIE_NAME, create_session_token())
        yield test_client
    app.dependency_overrides.clear()


def test_search_rank_select_and_download(client):
    ranked = client.post("/recruit/jd/rank", data={"jd_text": JD, "confirm_replace": "0"})
    assert ranked.status_code == 200
    plan = client.post("/recruit/jd/portals/plan", data={"jd_text": JD})
    assert plan.status_code == 200
    body = plan.json()["plan"]
    assert "java" in body["queries"]["generic"]

    searched = client.post(
        "/recruit/jd/portals/search",
        data={"plan_json": json.dumps(body), "connectors": "mock", "approved": "1", "jd_text": JD},
        headers={"accept": "application/json"},
    )
    assert searched.status_code == 200
    assert searched.json()["saved"] >= 2

    page = client.get("/recruit/jd/portals", params={"locations": "Bengaluru"})
    assert page.status_code == 200
    assert page.text.count("Ananya Rao") == 1
    assert "Rahul Menon" not in page.text
    assert "quota remaining" in page.text

    blocked = client.post(
        "/recruit/jd/portals/search",
        data={"plan_json": json.dumps(body), "connectors": "mock", "approved": "0"},
        headers={"accept": "application/json"},
    )
    assert blocked.status_code == 400

    hits_page = client.get("/recruit/jd/portals")
    start = hits_page.text.find('name="hit_ids"')
    assert start > 0
    value = hits_page.text[start:].split('value="', 1)[1].split('"', 1)[0]

    first = client.post("/recruit/jd/portals/download", data={"hit_ids": value, "force": "0"})
    assert first.status_code == 200
    file_row = first.json()["files"][0]
    assert file_row["name"].endswith(".txt")
    assert "Ananya" in file_row["name"] or file_row["content"]

    second = client.post("/recruit/jd/portals/download", data={"hit_ids": value, "force": "0"})
    assert second.json()["log"][0]["status"] == "skipped"
    assert second.json()["files"] == []

    analysed = client.post("/recruit/jd/portals/to-analysis", data={"hit_ids": value}, follow_redirects=False)
    assert analysed.status_code == 303
    match_page = client.get("/recruit/jd")
    assert "1 profiles loaded" in match_page.text or "profiles loaded" in match_page.text
