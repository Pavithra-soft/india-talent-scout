"""Portal adapters. These never log in with a stored username and password."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import get_settings
from app.profile_fields import canonicalize_skill, normalize_notice_period, normalize_phone


@dataclass
class PortalProfile:
    portal: str
    portal_id: str
    name: str
    email: str = ""
    phone: str = ""
    company: str = ""
    location: str = ""
    skills: str = ""
    years_experience: int | None = None
    notice_raw: str = ""
    notice_days: int | None = None
    snippet: str = ""

    def resume_text(self) -> str:
        lines = [
            self.name,
            self.email,
            self.phone,
            f"Location: {self.location}" if self.location else "",
            f"Company: {self.company}" if self.company else "",
            self.notice_raw,
            f"{self.years_experience} years experience" if self.years_experience is not None else "",
            f"Skills: {self.skills}" if self.skills else "",
            self.snippet,
        ]
        return "\n".join(line for line in lines if line)


class ConnectorError(Exception):
    pass


class PortalConnector:
    key = ""
    label = ""

    def enabled(self) -> bool:
        return False

    def quota_remaining(self) -> int | None:
        return None

    def search(self, plan: dict) -> list[PortalProfile]:
        return []

    def fetch_profile(self, portal_id: str) -> PortalProfile | None:
        for profile in self.search({}):
            if profile.portal_id == portal_id:
                return profile
        return None

    def download(self, profile: PortalProfile) -> tuple[str, bytes]:
        from app.portal_results import profile_filename
        from datetime import datetime, timezone

        name = profile_filename(1, profile.name, profile.portal, datetime.now(timezone.utc))
        return name, profile.resume_text().encode("utf-8")


class MockPortalConnector(PortalConnector):
    """Sample profiles so the flow can be tried without a live portal account."""

    key = "mock"
    label = "Mock portal"

    def __init__(self) -> None:
        self._profiles = [
            PortalProfile("mock", "m1", "Ananya Rao", "ananya.rao@example.com", "+919876543210", "Infosys", "Bengaluru", "java, spring boot, kafka, javascript", 8, "30 days", 30, "Backend engineer"),
            PortalProfile("mock", "m2", "Meera Iyer", "meera.iyer@example.com", "", "Wipro", "Bengaluru", "java, spring boot", 6, "2 months", 60, "Java developer"),
            PortalProfile("mock", "m3", "Rahul Menon", "rahul.menon@example.com", "+919876543211", "Tcs", "Pune", "python, django, postgresql", 4, "immediate", 0, "Python developer"),
            PortalProfile("mock", "m4", "Kavya Nair", "kavya.nair@example.com", "+919800112233", "Flipkart", "Bengaluru", "java, kafka, kubernetes", 7, "15 days", 15, "Platform engineer"),
            PortalProfile("mock", "m5", "Ananya Rao", "ananya.rao@example.com", "+919876543210", "Infosys", "Bengaluru", "java, spring boot", 8, "30 days", 30, "Duplicate of m1 from a second listing"),
        ]

    def enabled(self) -> bool:
        return True

    def quota_remaining(self) -> int | None:
        return 25

    def search(self, plan: dict) -> list[PortalProfile]:
        must = _plan_skills(plan.get("must_have"))
        locations = [item.lower() for item in plan.get("locations") or []]
        chosen = []
        for profile in self._profiles:
            skills = {canonicalize_skill(part) for part in profile.skills.split(",")}
            skill_ok = not must or bool(skills & set(must))
            place_ok = not locations or profile.location.lower() in locations
            if skill_ok and place_ok:
                chosen.append(profile)
        return chosen

    def fetch_profile(self, portal_id: str) -> PortalProfile | None:
        for profile in self._profiles:
            if profile.portal_id == portal_id:
                return profile
        return None


class LicensedApiConnector(PortalConnector):
    """Calls a licensed JSON API. Disabled until a base URL and key are configured."""

    key = "licensed_api"
    label = "Licensed API"

    def __init__(self, base_url: str = "", api_key: str = "") -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.portal_api_base).rstrip("/")
        self.api_key = api_key or settings.portal_api_key
        self._quota: int | None = None

    def enabled(self) -> bool:
        return bool(self.base_url and self.api_key)

    def quota_remaining(self) -> int | None:
        return self._quota

    def search(self, plan: dict) -> list[PortalProfile]:
        if not self.enabled():
            return []
        query = (plan.get("queries") or {}).get("generic") or ""
        url = f"{self.base_url}/v1/profiles"
        with httpx.Client(timeout=20.0) as client:
            response = client.get(
                url,
                params={"q": query[:300]},
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        if response.status_code == 429:
            raise ConnectorError("The licensed API rate limit was reached.")
        if response.status_code >= 400:
            raise ConnectorError("The licensed API rejected the search.")
        payload = response.json()
        if isinstance(payload, dict) and payload.get("quota_remaining") is not None:
            self._quota = int(payload["quota_remaining"])
        rows = payload.get("profiles", payload if isinstance(payload, list) else [])
        return [_from_api_row(row) for row in rows if isinstance(row, dict)]


class CsvImportConnector(PortalConnector):
    key = "csv_import"
    label = "CSV export"

    def enabled(self) -> bool:
        return True

    def search(self, plan: dict) -> list[PortalProfile]:
        return []

    def from_csv(self, text: str) -> list[PortalProfile]:
        import csv
        import io

        reader = csv.DictReader(io.StringIO(text or ""))
        profiles = []
        for index, row in enumerate(reader, start=1):
            lowered = { (key or "").strip().lower(): (value or "").strip() for key, value in row.items() }
            name = lowered.get("name") or ""
            if not name and not lowered.get("email"):
                continue
            phone = normalize_phone(lowered.get("phone") or "")
            years = lowered.get("years_experience") or lowered.get("years") or ""
            notice_raw, notice_days = normalize_notice_period(
                lowered.get("notice period") or lowered.get("notice") or ""
            )
            profiles.append(
                PortalProfile(
                    portal="csv",
                    portal_id=f"csv-{index}",
                    name=name,
                    email=(lowered.get("email") or "").lower(),
                    phone=phone,
                    company=lowered.get("company") or lowered.get("previous company") or "",
                    location=lowered.get("location") or lowered.get("city") or "",
                    skills=lowered.get("skills") or lowered.get("skill set") or "",
                    years_experience=int(years) if years.isdigit() else None,
                    notice_raw=notice_raw,
                    notice_days=notice_days,
                    snippet="Imported from a portal CSV export",
                )
            )
        return profiles


def available_connectors(api_base: str = "", api_key: str = "") -> list[PortalConnector]:
    return [MockPortalConnector(), LicensedApiConnector(api_base, api_key), CsvImportConnector()]


def connector_by_key(key: str, api_base: str = "", api_key: str = "") -> PortalConnector | None:
    for connector in available_connectors(api_base, api_key):
        if connector.key == key:
            return connector
    return None


def _plan_skills(entries) -> list[str]:
    skills = []
    for entry in entries or []:
        if isinstance(entry, dict):
            skill = canonicalize_skill(str(entry.get("skill") or ""))
        else:
            skill = canonicalize_skill(str(entry))
        if skill:
            skills.append(skill)
    return skills


def _from_api_row(row: dict) -> PortalProfile:
    years = row.get("years_experience")
    return PortalProfile(
        portal="licensed_api",
        portal_id=str(row.get("id") or row.get("portal_id") or ""),
        name=str(row.get("name") or ""),
        email=str(row.get("email") or "").lower(),
        phone=normalize_phone(str(row.get("phone") or "")),
        company=str(row.get("company") or ""),
        location=str(row.get("location") or row.get("city") or ""),
        skills=str(row.get("skills") or ""),
        years_experience=int(years) if isinstance(years, int) or (isinstance(years, str) and years.isdigit()) else None,
        notice_raw=str(row.get("notice_period") or ""),
        snippet=str(row.get("snippet") or "")[:500],
    )
