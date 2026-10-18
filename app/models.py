from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CandidateSource(str, enum.Enum):
    OPT_IN = "OPT_IN"
    CSV = "CSV"
    DEMO = "DEMO"
    PORTAL = "PORTAL"


class ShortlistStatus(str, enum.Enum):
    NEW = "NEW"
    CONTACTED = "CONTACTED"
    REJECTED = "REJECTED"


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    years_experience: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    skills: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default=CandidateSource.OPT_IN.value)
    source_portal: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    profile_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    search_blob: Mapped[str] = mapped_column(Text, nullable=False, default="")

    resume: Mapped[Optional["ResumeArtifact"]] = relationship(
        back_populates="candidate", uselist=False, cascade="all, delete-orphan"
    )
    shortlists: Mapped[list["Shortlist"]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan"
    )


class ResumeArtifact(Base):
    __tablename__ = "resume_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), unique=True)
    stored_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    original_filename: Mapped[Optional[str]] = mapped_column(String(260), nullable=True)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    candidate: Mapped["Candidate"] = relationship(back_populates="resume")


class Shortlist(Base):
    __tablename__ = "shortlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ShortlistStatus.NEW.value)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    candidate: Mapped["Candidate"] = relationship(back_populates="shortlists")


class JobPortal(Base):
    __tablename__ = "job_portals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    login_url: Mapped[str] = mapped_column(String(500), nullable=False)
    recruiter_home_url: Mapped[str] = mapped_column(String(500), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    credential: Mapped[Optional["PortalCredential"]] = relationship(
        back_populates="portal", uselist=False, cascade="all, delete-orphan"
    )


class PortalCredential(Base):
    __tablename__ = "portal_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portal_id: Mapped[int] = mapped_column(ForeignKey("job_portals.id", ondelete="CASCADE"), unique=True)
    username_enc: Mapped[str] = mapped_column(Text, nullable=False)
    password_enc: Mapped[str] = mapped_column(Text, nullable=False)
    authenticated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    portal: Mapped["JobPortal"] = relationship(back_populates="credential")


class JdWorkspace(Base):
    __tablename__ = "jd_workspaces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    jd_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    weights_json: Mapped[str] = mapped_column(Text, nullable=False, default="")
    filter_json: Mapped[str] = mapped_column(Text, nullable=False, default="")

    profiles: Mapped[list["JdProfile"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    search_plans: Mapped[list["PortalSearchPlan"]] = relationship(
        cascade="all, delete-orphan"
    )
    portal_hits: Mapped[list["PortalHit"]] = relationship(
        cascade="all, delete-orphan"
    )


class JdProfile(Base):
    __tablename__ = "jd_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("jd_workspaces.id", ondelete="CASCADE"), index=True)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(260), nullable=False, default="")
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    location: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    skills: Mapped[str] = mapped_column(Text, nullable=False, default="")
    matching_skills: Mapped[str] = mapped_column(Text, nullable=False, default="")
    missing_skills: Mapped[str] = mapped_column(Text, nullable=False, default="")
    company: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    notice_raw: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    notice_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    years_experience: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")

    workspace: Mapped["JdWorkspace"] = relationship(back_populates="profiles")


class PortalSearchPlan(Base):
    __tablename__ = "portal_search_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("jd_workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="Search plan")
    plan_json: Mapped[str] = mapped_column(Text, nullable=False, default="")
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PortalHit(Base):
    __tablename__ = "portal_hits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("jd_workspaces.id", ondelete="CASCADE"), index=True)
    portal: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    portal_profile_id: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    company: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    location: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    skills: Mapped[str] = mapped_column(Text, nullable=False, default="")
    years_experience: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notice_raw: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    notice_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    snippet: Mapped[str] = mapped_column(Text, nullable=False, default="")
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    matching_skills: Mapped[str] = mapped_column(Text, nullable=False, default="")
    missing_skills: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    downloaded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PortalApiConfig(Base):
    __tablename__ = "portal_api_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    base_url: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    api_key_enc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class RecruitAudit(Base):
    __tablename__ = "recruit_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    detail: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MailConnection(Base):
    __tablename__ = "mail_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    account_email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    access_token_enc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    refresh_token_enc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
