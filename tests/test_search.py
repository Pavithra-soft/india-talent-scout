from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Candidate, CandidateSource, ResumeArtifact
from app.resume_parser import build_search_blob
from app.search_service import SearchParams, parse_skill_tokens, score_candidate, search_candidates


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _add_candidate(db, name, skills, city="Bengaluru", years=10, days_ago=5):
    now = datetime.now(timezone.utc)
    extracted = f"{name} profile with {skills}"
    blob = build_search_blob(name, skills, city, extracted, extracted)
    c = Candidate(
        name=name,
        email=f"{name.replace(' ', '.').lower()}@example.com",
        city=city,
        years_experience=years,
        skills=skills,
        source=CandidateSource.DEMO.value,
        last_active_at=now - timedelta(days=days_ago),
        created_at=now,
        consent=True,
        search_blob=blob,
    )
    db.add(c)
    db.flush()
    db.add(ResumeArtifact(candidate_id=c.id, extracted_text=extracted))
    db.commit()
    return c


def test_parse_skill_tokens():
    assert parse_skill_tokens("Java, Kafka,  spring") == ["java", "kafka", "spring"]


def test_score_candidate_matches_skills():
    now = datetime.now(timezone.utc)
    c = Candidate(
        name="Test",
        email="t@e.com",
        skills="java, kafka",
        last_active_at=now,
        created_at=now,
        consent=True,
        search_blob="java kafka spring",
    )
    scored = score_candidate(c, ["java", "kafka"], now - timedelta(days=30))
    assert scored.score >= 20
    assert set(scored.matched_skills) == {"java", "kafka"}


def test_search_filters_active_window(db):
    _add_candidate(db, "Active Dev", "java, kafka", days_ago=3)
    _add_candidate(db, "Stale Dev", "java, kafka", days_ago=90)
    results, _ = search_candidates(
        db,
        SearchParams(skills="java", city=None, min_years=None, max_years=None, active_days=30, source=None, job_brief=None),
    )
    names = [r.candidate.name for r in results]
    assert "Active Dev" in names
    assert "Stale Dev" not in names


def test_search_skill_keyword(db):
    _add_candidate(db, "Java Lead", "java, spring")
    _add_candidate(db, "Frontend", "react, typescript")
    results, _ = search_candidates(
        db,
        SearchParams(skills="kafka, java", city=None, min_years=None, max_years=None, active_days=30, source=None, job_brief=None),
    )
    assert len(results) == 1
    assert results[0].candidate.name == "Java Lead"
