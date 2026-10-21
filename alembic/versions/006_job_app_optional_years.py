"""Make job application years_experience optional

Revision ID: 006
Revises: 005
Create Date: 2026-10-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("job_applications") as batch_op:
        batch_op.alter_column(
            "years_experience",
            existing_type=sa.Integer(),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("job_applications") as batch_op:
        batch_op.alter_column(
            "years_experience",
            existing_type=sa.Integer(),
            nullable=False,
        )
