import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@lru_cache
def get_settings():
    return Settings()


class Settings:
    def __init__(self):
        raw_url = os.getenv("DATABASE_URL", "sqlite:///./data/talent.db")
        self.database_url = _normalize_database_url(raw_url)
        self.recruiter_password = os.getenv("RECRUITER_PASSWORD", "recruiter")
        self.session_secret = os.getenv("SESSION_SECRET", "dev-insecure-change-me")
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self.demo_seed = os.getenv("DEMO_SEED", "true").lower() in ("1", "true", "yes")
        storage = os.getenv("STORAGE_DIR", "./data/resumes")
        self.storage_dir = Path(storage)
        self.is_sqlite = self.database_url.startswith("sqlite")
        self.port = int(os.getenv("PORT", "8081"))
        self.portal_live_login = os.getenv("PORTAL_LIVE_LOGIN", "false").lower() in ("1", "true", "yes")
        self.jd_ttl_hours = int(os.getenv("JD_TTL_HOURS", "24"))
        self.portal_api_base = os.getenv("PORTAL_API_BASE", "").strip().rstrip("/")
        self.portal_api_key = os.getenv("PORTAL_API_KEY", "").strip()
        self.oauth_redirect_base = os.getenv("OAUTH_REDIRECT_BASE", "http://127.0.0.1:8081").rstrip("/")
        self.google_oauth_client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
        self.google_oauth_client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
        self.microsoft_oauth_client_id = os.getenv("MICROSOFT_OAUTH_CLIENT_ID", "").strip()
        self.microsoft_oauth_client_secret = os.getenv("MICROSOFT_OAUTH_CLIENT_SECRET", "").strip()


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://") and "+psycopg" not in url and "+psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url
