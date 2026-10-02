from app.models import Base, Candidate, CandidateSource
from app.portal_service import ensure_portals, pull_from_portals, save_portal_credentials
from app.plugins import SearchCriteria
from app.search_service import SearchParams, search_candidates
from tests.test_search import db  # noqa: F401 — shared fixture


def test_portal_pull_and_search(db):
    ensure_portals(db)
    save_portal_credentials(db, "naukri", "recruiter@company.com", "secret-pass")
    criteria = SearchCriteria(skills=["java"], city="Bengaluru", min_years=5, max_years=None, active_days=30)
    report = pull_from_portals(db, ["naukri"], criteria)
    assert report.total_imported >= 1
    results, messages = search_candidates(
        db,
        SearchParams(
            skills="java",
            city=None,
            min_years=None,
            max_years=None,
            active_days=30,
            source=None,
            job_brief=None,
            portal_keys=["naukri"],
            include_local_pool=False,
            sync_portals=False,
        ),
    )
    assert results
    assert any(c.candidate.source == CandidateSource.PORTAL.value for c in results)
    assert messages == []
