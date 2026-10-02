from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import Candidate, CandidateSource, ResumeArtifact
from app.resume_parser import build_search_blob

DEMO_PROFILES = [
    ("Arjun Mehta", "arjun.mehta@example.com", "Bengaluru", 14, "java, spring boot, kafka, keycloak, microservices", "naukri"),
    ("Kavya Reddy", "kavya.reddy@example.com", "Hyderabad", 10, "java, spring, postgres, redis, aws", "naukri"),
    ("Rohan Desai", "rohan.desai@example.com", "Pune", 12, "java, kafka, kubernetes, docker, terraform", "shine"),
    ("Ananya Iyer", "ananya.iyer@example.com", "Chennai", 9, "python, fastapi, django, postgres, aws", "indeed"),
    ("Vikram Singh", "vikram.singh@example.com", "Gurgaon", 15, "java, spring, oracle, microservices, leadership", "naukri"),
    ("Meera Nair", "meera.nair@example.com", "Kochi", 8, "react, typescript, node.js, aws", "instahyre"),
    ("Sanjay Patel", "sanjay.patel@example.com", "Ahmedabad", 11, "java, spring boot, hibernate, mysql", "naukri"),
    ("Divya Krishnan", "divya.krishnan@example.com", "Bengaluru", 7, "data engineering, spark, python, airflow", "naukri"),
    ("Imran Khan", "imran.khan@example.com", "Mumbai", 13, "java, kafka, keycloak, spring security", "naukri"),
    ("Pooja Gupta", "pooja.gupta@example.com", "Noida", 6, "angular, typescript, java, rest", "shine"),
    ("Harish Rao", "harish.rao@example.com", "Hyderabad", 16, "java, architecture, kafka, aws, team lead", "naukri"),
    ("Lakshmi Venkat", "lakshmi.venkat@example.com", "Chennai", 10, "spring, microservices, docker, ci/cd", "naukri"),
    ("Aditya Joshi", "aditya.joshi@example.com", "Pune", 5, "python, fastapi, postgres, redis", "indeed"),
    ("Neha Kapoor", "neha.kapoor@example.com", "Delhi", 12, "java, spring ai, gemini, kafka", "naukri"),
    ("Karthik B", "karthik.b@example.com", "Bengaluru", 14, "java, payments, kafka, keycloak, spring", "naukri"),
]


def seed_demo_candidates(db: Session) -> int:
    if db.query(Candidate).count() > 0:
        return 0
    now = datetime.now(timezone.utc)
    created = 0
    for i, (name, email, city, years, skills, portal) in enumerate(DEMO_PROFILES):
        summary = f"{name} — {years}+ years in India IT. Skills: {skills}."
        extracted = summary + " Open to senior backend and platform roles."
        search_blob = build_search_blob(name, skills, city, extracted, summary)
        candidate = Candidate(
            name=name,
            email=email,
            phone=f"+91-90000{10000 + i}",
            city=city,
            years_experience=years,
            skills=skills,
            source=CandidateSource.DEMO.value,
            source_portal=portal,
            last_active_at=now - timedelta(days=i * 2),
            created_at=now,
            consent=True,
            profile_summary=summary,
            search_blob=search_blob,
        )
        db.add(candidate)
        db.flush()
        db.add(
            ResumeArtifact(
                candidate_id=candidate.id,
                extracted_text=extracted,
            )
        )
        created += 1
    db.commit()
    return created
