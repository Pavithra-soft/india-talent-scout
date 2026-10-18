import hashlib

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from fastapi import HTTPException, Request, status

from app.config import get_settings

COOKIE_NAME = "recruiter_session"
MAX_AGE_SECONDS = 60 * 60 * 12


def _serializer() -> URLSafeTimedSerializer:
    settings = get_settings()
    return URLSafeTimedSerializer(settings.session_secret, salt="recruiter-auth")


def create_session_token() -> str:
    return _serializer().dumps({"role": "recruiter"})


def verify_session_token(token: str) -> bool:
    try:
        data = _serializer().loads(token, max_age=MAX_AGE_SECONDS)
        return data.get("role") == "recruiter"
    except (BadSignature, SignatureExpired):
        return False


def is_recruiter_authenticated(request: Request) -> bool:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return False
    return verify_session_token(token)


def require_recruiter(request: Request) -> None:
    if not is_recruiter_authenticated(request):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Recruiter login required")


def session_owner_key(request: Request) -> str:
    token = request.cookies.get(COOKIE_NAME) or ""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def check_password(password: str) -> bool:
    settings = get_settings()
    return password == settings.recruiter_password
