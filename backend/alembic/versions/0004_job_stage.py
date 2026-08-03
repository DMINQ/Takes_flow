"""jobs: add stage column for granular progress reporting

Adds `jobs.stage` — the name of the currently running pipeline plugin (e.g.
"transcribe", "diarize"), surfaced by GET /jobs/{id} so the frontend can show
"Убираем шум...", "Транскрибируем..." instead of a bare percentage.

Revision ID: 0004_job_stage
Revises: 0003_projects_artifacts
Create Date: 2026-08-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_job_stage"
down_revision: Union[str, None] = "0003_projects_artifacts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("stage", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "stage")
