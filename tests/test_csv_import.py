from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.csv_import import import_csv, template_csv
from app.models import Base, Candidate


def test_template_csv_has_headers():
    csv_text = template_csv()
    assert "name,email" in csv_text.replace("\r", "")
    assert "java,spring,kafka" in csv_text


def test_import_csv_success_and_validation():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    good = """name,email,skills,last_active_at,city,years_experience,source_portal,profile_summary
Ada Lovelace,ada@example.com,python java,2026-03-01,Chennai,8,naukri,Backend engineer
"""
    result = import_csv(db, good)
    assert result.imported == 1
    assert not result.errors
    assert db.query(Candidate).count() == 1

    bad = """name,email
,missing@example.com
"""
    result2 = import_csv(db, bad)
    assert result2.imported == 0
    assert any("name and email" in e for e in result2.errors)

    db.close()
