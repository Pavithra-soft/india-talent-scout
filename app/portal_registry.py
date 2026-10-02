from dataclasses import dataclass


@dataclass(frozen=True)
class PortalDefinition:
    key: str
    name: str
    login_url: str
    recruiter_home_url: str
    notes: str


DEFAULT_PORTALS: list[PortalDefinition] = [
    PortalDefinition(
        key="naukri",
        name="Naukri Resdex",
        login_url="https://www.naukri.com/recruit/login",
        recruiter_home_url="https://resdex.naukri.com/v3/search",
        notes="Resume database (Resdex). Requires paid recruiter account.",
    ),
    PortalDefinition(
        key="shine",
        name="Shine.com",
        login_url="https://recruiter.shine.com/",
        recruiter_home_url="https://recruiter.shine.com/advancedsearch/",
        notes="Recruiter resume search (subscription).",
    ),
    PortalDefinition(
        key="indeed",
        name="Indeed India",
        login_url="https://secure.indeed.com/account/login",
        recruiter_home_url="https://employers.indeed.com/candidates",
        notes="Employer / Smart Sourcing resume search.",
    ),
    PortalDefinition(
        key="foundit",
        name="Foundit (Monster India)",
        login_url="https://recruiter.foundit.in/ire/login",
        recruiter_home_url="https://recruiter.foundit.in/search/resumes",
        notes="Formerly Monster India recruiter DB.",
    ),
    PortalDefinition(
        key="instahyre",
        name="Instahyre",
        login_url="https://www.instahyre.com/employers/login/",
        recruiter_home_url="https://www.instahyre.com/employers/candidates/",
        notes="Employer login for curated tech candidates.",
    ),
]
