"""Portal search plans and hits

Revision ID: 004
Revises: 003
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "portal_search_plans",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("plan_json", sa.Text(), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["jd_workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_portal_search_plans_workspace_id", "portal_search_plans", ["workspace_id"])
    op.create_table(
        "portal_hits",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("portal", sa.String(length=40), nullable=False),
        sa.Column("portal_profile_id", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("company", sa.String(length=200), nullable=False),
        sa.Column("location", sa.String(length=120), nullable=False),
        sa.Column("skills", sa.Text(), nullable=False),
        sa.Column("years_experience", sa.Integer(), nullable=True),
        sa.Column("notice_raw", sa.String(length=80), nullable=False),
        sa.Column("notice_days", sa.Integer(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("matching_skills", sa.Text(), nullable=False),
        sa.Column("missing_skills", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("downloaded", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["jd_workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_portal_hits_workspace_id", "portal_hits", ["workspace_id"])
    op.create_table(
        "portal_api_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_key", sa.String(length=64), nullable=False),
        sa.Column("base_url", sa.String(length=300), nullable=False),
        sa.Column("api_key_enc", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_portal_api_configs_owner_key", "portal_api_configs", ["owner_key"], unique=True)
    op.create_table(
        "recruit_audit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_key", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("detail", sa.String(length=300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recruit_audit_owner_key", "recruit_audit", ["owner_key"])


def downgrade() -> None:
    op.drop_index("ix_recruit_audit_owner_key", table_name="recruit_audit")
    op.drop_table("recruit_audit")
    op.drop_index("ix_portal_api_configs_owner_key", table_name="portal_api_configs")
    op.drop_table("portal_api_configs")
    op.drop_index("ix_portal_hits_workspace_id", table_name="portal_hits")
    op.drop_table("portal_hits")
    op.drop_index("ix_portal_search_plans_workspace_id", table_name="portal_search_plans")
    op.drop_table("portal_search_plans")
