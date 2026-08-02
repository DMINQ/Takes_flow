"""projects + artifacts: group media into projects, persist pipeline outputs

Adds the `projects` table (groups media from the same editing job) and the
`artifacts` table (durable, re-fetchable output of each pipeline stage, keyed
by media+kind). `media.project_id` and `upload_sessions.project_id` FK into
projects; existing rows each get their own single-media project so the
backfill is safe on a populated database.

Revision ID: 0003_projects_artifacts
Revises: 0002_direct_uploads
Create Date: 2026-08-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0003_projects_artifacts"
down_revision: Union[str, None] = "0002_direct_uploads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- projects ---
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # --- media.project_id ---
    op.add_column("media", sa.Column("project_id", sa.String(length=32), nullable=True))
    # Backfill: one project per existing media row, named after its filename,
    # so pre-existing data keeps working without a manual grouping decision.
    op.execute(
        """
        INSERT INTO projects (id, name)
        SELECT m.id, m.filename FROM media m
        """
    )
    op.execute("UPDATE media SET project_id = id WHERE project_id IS NULL")
    op.alter_column("media", "project_id", nullable=False)
    op.create_index("ix_media_project_id", "media", ["project_id"])
    op.create_foreign_key(
        "fk_media_project_id", "media", "projects", ["project_id"], ["id"], ondelete="CASCADE"
    )

    # --- upload_sessions.project_id ---
    op.add_column("upload_sessions", sa.Column("project_id", sa.String(length=32), nullable=True))
    op.execute(
        """
        UPDATE upload_sessions us SET project_id = m.project_id
        FROM media m WHERE us.media_id = m.id AND us.project_id IS NULL
        """
    )
    # Any session with no completed media yet (still INITIATED) gets its own
    # fresh project so the column can be made non-nullable.
    op.execute(
        """
        INSERT INTO projects (id, name)
        SELECT us.id, us.filename FROM upload_sessions us WHERE us.project_id IS NULL
        """
    )
    op.execute("UPDATE upload_sessions SET project_id = id WHERE project_id IS NULL")
    op.alter_column("upload_sessions", "project_id", nullable=False)
    op.create_index("ix_upload_sessions_project_id", "upload_sessions", ["project_id"])
    op.create_foreign_key(
        "fk_upload_sessions_project_id",
        "upload_sessions", "projects", ["project_id"], ["id"], ondelete="CASCADE",
    )

    # --- artifacts ---
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("media_id", sa.String(length=32), nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("artifact_metadata", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_artifacts_media_id", "artifacts", ["media_id"])
    op.create_index("ix_artifacts_job_id", "artifacts", ["job_id"])
    op.create_index("ix_artifacts_kind", "artifacts", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_artifacts_kind", table_name="artifacts")
    op.drop_index("ix_artifacts_job_id", table_name="artifacts")
    op.drop_index("ix_artifacts_media_id", table_name="artifacts")
    op.drop_table("artifacts")

    op.drop_constraint("fk_upload_sessions_project_id", "upload_sessions", type_="foreignkey")
    op.drop_index("ix_upload_sessions_project_id", table_name="upload_sessions")
    op.drop_column("upload_sessions", "project_id")

    op.drop_constraint("fk_media_project_id", "media", type_="foreignkey")
    op.drop_index("ix_media_project_id", table_name="media")
    op.drop_column("media", "project_id")

    op.drop_table("projects")
