"""direct uploads: upload_sessions, media.storage_key

Replaces media.path (a local filesystem path) with media.storage_key (an object
key), because with S3 the bytes may never touch the API host's disk. Adds the
upload_sessions table that tracks client-direct transfers the API mediates but
never carries.

Revision ID: 0002_direct_uploads
Revises: 0001_initial
Create Date: 2026-07-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_direct_uploads"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- media: path -> storage_key ---
    op.add_column("media", sa.Column("storage_key", sa.String(length=1024), nullable=True))
    op.add_column("media", sa.Column("checksum", sa.String(length=128), nullable=True))
    # Existing rows hold absolute local paths; carry them over so nothing is lost.
    op.execute("UPDATE media SET storage_key = path WHERE storage_key IS NULL")
    op.alter_column("media", "storage_key", nullable=False)
    op.create_unique_constraint("uq_media_storage_key", "media", ["storage_key"])
    op.drop_column("media", "path")

    # --- upload_sessions ---
    op.create_table(
        "upload_sessions",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("declared_size", sa.BigInteger(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("upload_id", sa.String(length=256), nullable=True),
        sa.Column("part_size", sa.BigInteger(), nullable=True),
        sa.Column("part_count", sa.Integer(), nullable=True),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("media_id", sa.String(length=32), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_upload_sessions_storage_key", "upload_sessions", ["storage_key"])
    op.create_index("ix_upload_sessions_status", "upload_sessions", ["status"])
    # The sweeper scans exactly this predicate; a partial index keeps it cheap as
    # the table grows with completed sessions.
    op.create_index(
        "ix_upload_sessions_stale",
        "upload_sessions",
        ["expires_at"],
        postgresql_where=sa.text("status = 'initiated'"),
    )


def downgrade() -> None:
    op.drop_index("ix_upload_sessions_stale", table_name="upload_sessions")
    op.drop_index("ix_upload_sessions_status", table_name="upload_sessions")
    op.drop_index("ix_upload_sessions_storage_key", table_name="upload_sessions")
    op.drop_table("upload_sessions")

    op.add_column("media", sa.Column("path", sa.String(length=1024), nullable=True))
    op.execute("UPDATE media SET path = storage_key WHERE path IS NULL")
    op.alter_column("media", "path", nullable=False)
    op.drop_constraint("uq_media_storage_key", "media", type_="unique")
    op.drop_column("media", "checksum")
    op.drop_column("media", "storage_key")
