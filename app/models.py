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
