"""Temporary JD match workspace

Revision ID: 003
Revises: 002
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jd_workspaces",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("jd_text", sa.Text(), nullable=False),
        sa.Column("weights_json", sa.Text(), nullable=False),
        sa.Column("filter_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jd_workspaces_owner_key", "jd_workspaces", ["owner_key"], unique=True)
    op.create_index("ix_jd_workspaces_expires_at", "jd_workspaces", ["expires_at"], unique=False)

    op.create_table(
        "jd_profiles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=260), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("location", sa.String(length=120), nullable=False),
        sa.Column("skills", sa.Text(), nullable=False),
        sa.Column("matching_skills", sa.Text(), nullable=False),
        sa.Column("missing_skills", sa.Text(), nullable=False),
        sa.Column("company", sa.String(length=200), nullable=False),
        sa.Column("notice_raw", sa.String(length=80), nullable=False),
        sa.Column("notice_days", sa.Integer(), nullable=True),
        sa.Column("years_experience", sa.Integer(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["jd_workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jd_profiles_workspace_id", "jd_profiles", ["workspace_id"], unique=False)
    op.create_index("ix_jd_profiles_file_hash", "jd_profiles", ["file_hash"], unique=False)

    op.create_table(
        "mail_connections",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_key", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("account_email", sa.String(length=320), nullable=False),
        sa.Column("access_token_enc", sa.Text(), nullable=False),
        sa.Column("refresh_token_enc", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mail_connections_owner_key", "mail_connections", ["owner_key"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_mail_connections_owner_key", table_name="mail_connections")
    op.drop_table("mail_connections")
    op.drop_index("ix_jd_profiles_file_hash", table_name="jd_profiles")
    op.drop_index("ix_jd_profiles_workspace_id", table_name="jd_profiles")
    op.drop_table("jd_profiles")
    op.drop_index("ix_jd_workspaces_expires_at", table_name="jd_workspaces")
    op.drop_index("ix_jd_workspaces_owner_key", table_name="jd_workspaces")
    op.drop_table("jd_workspaces")
