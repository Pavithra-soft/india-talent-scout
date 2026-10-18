"""Create mailbox drafts. This module never calls a send endpoint."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urlencode

import httpx
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.crypto_service import decrypt_text, encrypt_text
from app.models import JdProfile, MailConnection

GOOGLE_SCOPES = " ".join(
    [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.compose",
    ]
)
MICROSOFT_SCOPES = "offline_access Mail.Read Mail.ReadWrite"


class MailNotConfigured(Exception):
    pass


class MailError(Exception):
    pass


def google_ready() -> bool:
    settings = get_settings()
    return bool(settings.google_oauth_client_id and settings.google_oauth_client_secret)


def microsoft_ready() -> bool:
    settings = get_settings()
    return bool(settings.microsoft_oauth_client_id and settings.microsoft_oauth_client_secret)


def authorization_url(provider: str, owner_key: str) -> str:
    settings = get_settings()
    state = _serializer().dumps({"owner": owner_key, "provider": provider})
    if provider == "google":
        if not google_ready():
            raise MailNotConfigured("Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET.")
        query = urlencode(
            {
                "client_id": settings.google_oauth_client_id,
                "redirect_uri": f"{settings.oauth_redirect_base}/recruit/jd/mail/google/callback",
                "response_type": "code",
                "scope": GOOGLE_SCOPES,
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
            }
        )
        return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"
    if provider == "microsoft":
        if not microsoft_ready():
            raise MailNotConfigured("Set MICROSOFT_OAUTH_CLIENT_ID and MICROSOFT_OAUTH_CLIENT_SECRET.")
        query = urlencode(
            {
                "client_id": settings.microsoft_oauth_client_id,
                "redirect_uri": f"{settings.oauth_redirect_base}/recruit/jd/mail/microsoft/callback",
                "response_type": "code",
                "scope": MICROSOFT_SCOPES,
                "state": state,
            }
        )
        return f"https://login.microsoftonline.com/common/oauth2/v2.0/authorize?{query}"
    raise MailNotConfigured("Unknown mailbox provider.")


def owner_from_state(state: str, provider: str) -> str:
    data = _serializer().loads(state, max_age=600)
    if data.get("provider") != provider or not data.get("owner"):
        raise MailError("Mailbox connection state did not match.")
    return data["owner"]


def exchange_code(db: Session, provider: str, owner_key: str, code: str) -> MailConnection:
    if provider == "google":
        token = _google_token(code)
        email = _google_email(token["access_token"])
    else:
        token = _microsoft_token(code)
        email = _microsoft_email(token["access_token"])
    return _save_connection(db, owner_key, provider, email, token)


def disconnect(db: Session, owner_key: str, provider: str) -> None:
    row = _connection(db, owner_key, provider)
    if row:
        db.delete(row)
        db.commit()


def connections_for(db: Session, owner_key: str) -> list[MailConnection]:
    return db.query(MailConnection).filter(MailConnection.owner_key == owner_key).all()


def recent_messages(db: Session, owner_key: str, candidate_email: str) -> list[dict]:
    connection = _any_connection(db, owner_key)
    if not connection or not candidate_email:
        return []
    token = _access_token(db, connection)
    if connection.provider == "google":
        return _google_messages(token, candidate_email)
    return _microsoft_messages(token, candidate_email)


def create_draft(
    db: Session,
    owner_key: str,
    profile: JdProfile,
    subject: str,
    body: str,
) -> str:
    if not profile.email:
        raise MailError("This profile has no email address.")
    connection = _any_connection(db, owner_key)
    if not connection:
        raise MailNotConfigured("Connect Gmail or Outlook before saving a draft.")
    token = _access_token(db, connection)
    if connection.provider == "google":
        _google_draft(token, profile.email, subject, body)
    else:
        _microsoft_draft(token, profile.email, subject, body)
    return connection.account_email or connection.provider


def render_reply(profile: JdProfile, tone: str, template_key: str, reply_context: str) -> tuple[str, str]:
    name = profile.name or "there"
    if template_key == "schedule":
        subject = f"Interview availability — {name}"
        ask = "Please share two or three times that work for a first conversation."
    else:
        subject = f"Next step for your profile — {name}"
        ask = (
            "Could you confirm your notice period, current CTC, expected CTC, and the earliest date you can join?"
        )
    greeting = "Hello" if tone == "concise" else "Hello"
    closing = "Thank you." if tone == "concise" else "Thank you for your time."
    context = f"\n\nRegarding your note: {reply_context.strip()}\n" if reply_context.strip() else "\n"
    body = (
        f"{greeting} {name},{context}\n"
        f"We reviewed your profile"
        f"{' (' + profile.location + ')' if profile.location else ''}. "
        f"{ask}\n\n{closing}"
    )
    return subject, body


def _save_connection(db: Session, owner_key: str, provider: str, email: str, token: dict) -> MailConnection:
    row = _connection(db, owner_key, provider) or MailConnection(owner_key=owner_key, provider=provider)
    row.account_email = email or ""
    row.access_token_enc = encrypt_text(token.get("access_token") or "")
    if token.get("refresh_token"):
        row.refresh_token_enc = encrypt_text(token["refresh_token"])
    expires_in = int(token.get("expires_in") or 3600)
    row.expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(60, expires_in - 60))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _connection(db: Session, owner_key: str, provider: str) -> MailConnection | None:
    return (
        db.query(MailConnection)
        .filter(MailConnection.owner_key == owner_key, MailConnection.provider == provider)
        .one_or_none()
    )


def _any_connection(db: Session, owner_key: str) -> MailConnection | None:
    return db.query(MailConnection).filter(MailConnection.owner_key == owner_key).first()


def _access_token(db: Session, connection: MailConnection) -> str:
    expires = connection.expires_at
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires and expires > datetime.now(timezone.utc):
        return decrypt_text(connection.access_token_enc)
    refresh = decrypt_text(connection.refresh_token_enc)
    if not refresh:
        raise MailError("Mailbox access expired. Connect the mailbox again.")
    if connection.provider == "google":
        token = _refresh_google(refresh)
    else:
        token = _refresh_microsoft(refresh)
    connection.access_token_enc = encrypt_text(token["access_token"])
    expires_in = int(token.get("expires_in") or 3600)
    connection.expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(60, expires_in - 60))
    db.commit()
    return token["access_token"]


def _google_token(code: str) -> dict:
    settings = get_settings()
    return _form_post(
        "https://oauth2.googleapis.com/token",
        {
            "code": code,
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "redirect_uri": f"{settings.oauth_redirect_base}/recruit/jd/mail/google/callback",
            "grant_type": "authorization_code",
        },
    )


def _refresh_google(refresh_token: str) -> dict:
    settings = get_settings()
    return _form_post(
        "https://oauth2.googleapis.com/token",
        {
            "refresh_token": refresh_token,
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "grant_type": "refresh_token",
        },
    )


def _microsoft_token(code: str) -> dict:
    settings = get_settings()
    return _form_post(
        "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        {
            "code": code,
            "client_id": settings.microsoft_oauth_client_id,
            "client_secret": settings.microsoft_oauth_client_secret,
            "redirect_uri": f"{settings.oauth_redirect_base}/recruit/jd/mail/microsoft/callback",
            "grant_type": "authorization_code",
        },
    )


def _refresh_microsoft(refresh_token: str) -> dict:
    settings = get_settings()
    return _form_post(
        "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        {
            "refresh_token": refresh_token,
            "client_id": settings.microsoft_oauth_client_id,
            "client_secret": settings.microsoft_oauth_client_secret,
            "grant_type": "refresh_token",
        },
    )


def _google_email(token: str) -> str:
    data = _get_json("https://gmail.googleapis.com/gmail/v1/users/me/profile", token)
    return data.get("emailAddress") or ""


def _microsoft_email(token: str) -> str:
    data = _get_json("https://graph.microsoft.com/v1.0/me", token)
    return data.get("mail") or data.get("userPrincipalName") or ""


def _google_messages(token: str, candidate_email: str) -> list[dict]:
    query = urlencode({"q": f"from:{candidate_email}", "maxResults": 5})
    listed = _get_json(f"https://gmail.googleapis.com/gmail/v1/users/me/messages?{query}", token)
    messages = []
    for item in (listed.get("messages") or [])[:5]:
        detail = _get_json(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{item['id']}?format=metadata",
            token,
        )
        headers = {h["name"].lower(): h["value"] for h in detail.get("payload", {}).get("headers", [])}
        messages.append({"subject": headers.get("subject", ""), "from": headers.get("from", "")})
    return messages


def _google_draft(token: str, to_email: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)
    raw = message.as_bytes()
    import base64

    encoded = base64.urlsafe_b64encode(raw).decode("ascii")
    _post_json(
        "https://gmail.googleapis.com/gmail/v1/users/me/drafts",
        token,
        {"message": {"raw": encoded}},
    )


def _microsoft_messages(token: str, candidate_email: str) -> list[dict]:
    query = urlencode({"$search": f'"from:{candidate_email}"', "$top": 5})
    data = _get_json(f"https://graph.microsoft.com/v1.0/me/messages?{query}", token)
    return [
        {"subject": item.get("subject") or "", "from": ((item.get("from") or {}).get("emailAddress") or {}).get("address", "")}
        for item in data.get("value") or []
    ]


def _microsoft_draft(token: str, to_email: str, subject: str, body: str) -> None:
    _post_json(
        "https://graph.microsoft.com/v1.0/me/messages",
        token,
        {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to_email}}],
        },
    )


def _form_post(url: str, data: dict) -> dict:
    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, data=data)
    if response.status_code >= 400:
        raise MailError("Mailbox provider rejected the connection.")
    return response.json()


def _get_json(url: str, token: str) -> dict:
    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers={"Authorization": f"Bearer {token}"})
    if response.status_code >= 400:
        raise MailError("Mailbox provider rejected the read request.")
    return response.json()


def _post_json(url: str, token: str, payload: dict) -> dict:
    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, headers={"Authorization": f"Bearer {token}"}, json=payload)
    if response.status_code >= 400:
        raise MailError("Could not save the draft in the mailbox.")
    return response.json()


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().session_secret, salt="mailbox-oauth")
