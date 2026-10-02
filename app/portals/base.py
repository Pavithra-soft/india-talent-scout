from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.config import get_settings
from app.plugins import ExternalCandidate, SearchCriteria


@dataclass
class AuthResult:
    ok: bool
    message: str


@dataclass
class PullResult:
    portal_key: str
    imported: int
    auth: AuthResult
    candidates: list[ExternalCandidate]


class PortalConnector:
    portal_key: str = ""
    login_url: str = ""

    def authenticate(self, username: str, password: str) -> AuthResult:
        if not username.strip() or not password.strip():
            return AuthResult(False, "Username and password are required.")
        settings = get_settings()
        if settings.portal_live_login:
            return self._live_authenticate(username, password)
        return AuthResult(
            True,
            "Credentials stored. Demo sync enabled — use Search with this portal selected to pull matching profiles.",
        )

    def search_resumes(self, username: str, password: str, criteria: SearchCriteria) -> list[ExternalCandidate]:
        auth = self.authenticate(username, password)
        if not auth.ok:
            return []
        return self._demo_pull(criteria)

    def _live_authenticate(self, username: str, password: str) -> AuthResult:
        try:
            with httpx.Client(timeout=20.0, follow_redirects=True) as client:
                response = client.get(self.login_url)
            if response.status_code >= 400:
                return AuthResult(False, f"Portal unreachable (HTTP {response.status_code}).")
            return AuthResult(
                False,
                "Portal reachable but automated recruiter login is blocked (CAPTCHA / no public API). "
                "Use CSV import or a licensed API integration. Credentials are saved for future connectors.",
            )
        except httpx.HTTPError as exc:
            return AuthResult(False, f"Connection failed: {exc}")

    def _demo_pull(self, criteria: SearchCriteria) -> list[ExternalCandidate]:
        skills = criteria.skills or ["java"]
        primary = skills[0]
        city = criteria.city or "Bengaluru"
        years = criteria.min_years or 8
        portal = self.portal_key
        results: list[ExternalCandidate] = []
        for i, skill in enumerate(skills[:3]):
            results.append(
                ExternalCandidate(
                    name=f"{portal.title()} {skill.title()} Candidate {i + 1}",
                    email=f"{portal}.{skill}.{i + 1}@portal-sync.example.com",
                    skills=", ".join(skills),
                    city=city,
                    years_experience=years + i,
                    source_portal=portal,
                )
            )
        if not criteria.skills:
            results.append(
                ExternalCandidate(
                    name=f"{portal.title()} Active Seeker",
                    email=f"{portal}.active@portal-sync.example.com",
                    skills=primary,
                    city=city,
                    years_experience=years,
                    source_portal=portal,
                )
            )
        return results


class NaukriConnector(PortalConnector):
    portal_key = "naukri"
    login_url = "https://www.naukri.com/recruit/login"


class ShineConnector(PortalConnector):
    portal_key = "shine"
    login_url = "https://recruiter.shine.com/"


class IndeedConnector(PortalConnector):
    portal_key = "indeed"
    login_url = "https://secure.indeed.com/account/login"


class FounditConnector(PortalConnector):
    portal_key = "foundit"
    login_url = "https://recruiter.foundit.in/ire/login"


class InstahyreConnector(PortalConnector):
    portal_key = "instahyre"
    login_url = "https://www.instahyre.com/employers/login/"


CONNECTORS: dict[str, PortalConnector] = {
    "naukri": NaukriConnector(),
    "shine": ShineConnector(),
    "indeed": IndeedConnector(),
    "foundit": FounditConnector(),
    "instahyre": InstahyreConnector(),
}


def get_connector(portal_key: str) -> PortalConnector | None:
    return CONNECTORS.get(portal_key)
