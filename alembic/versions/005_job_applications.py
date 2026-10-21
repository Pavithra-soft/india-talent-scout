"""Job postings and candidate applications

Revision ID: 005
Revises: 004
Create Date: 2026-10-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_postings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("jd_text", sa.Text(), nullable=False),
        sa.Column("share_token", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("share_token"),
    )
    op.create_index("ix_job_postings_share_token", "job_postings", ["share_token"])

    op.create_table(
        "job_applications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("posting_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("phone", sa.String(length=40), nullable=False),
        sa.Column("years_experience", sa.Integer(), nullable=False),
        sa.Column("skills", sa.Text(), nullable=False, server_default=""),
        sa.Column("notice_raw", sa.String(length=120), nullable=False),
        sa.Column("notice_days", sa.Integer(), nullable=True),
        sa.Column("additional_notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resume_stored_path", sa.String(length=500), nullable=True),
        sa.Column("resume_content_type", sa.String(length=120), nullable=True),
        sa.Column("resume_original_filename", sa.String(length=260), nullable=True),
        sa.Column("resume_extracted_text", sa.Text(), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(["posting_id"], ["job_postings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_applications_posting_id", "job_applications", ["posting_id"])
    op.create_index("ix_job_applications_email", "job_applications", ["email"])


def downgrade() -> None:
    op.drop_index("ix_job_applications_email", table_name="job_applications")
    op.drop_index("ix_job_applications_posting_id", table_name="job_applications")
    op.drop_table("job_applications")
    op.drop_index("ix_job_postings_share_token", table_name="job_postings")
    op.drop_table("job_postings")
