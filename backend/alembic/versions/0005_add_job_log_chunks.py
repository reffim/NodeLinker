"""add job_log_chunks table, drop log_file_url

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_log_chunks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_seq", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id", "node_id", "chunk_seq",
            name="uq_job_log_chunks_job_node_seq",
        ),
    )
    op.create_index(
        "ix_job_log_chunks_job_node_seq",
        "job_log_chunks",
        ["job_id", "node_id", "chunk_seq"],
    )
    op.drop_column("job_nodes", "log_file_url")


def downgrade() -> None:
    op.drop_index("ix_job_log_chunks_job_node_seq", table_name="job_log_chunks")
    op.drop_table("job_log_chunks")
    op.add_column(
        "job_nodes",
        sa.Column("log_file_url", sa.String(length=1024), nullable=True),
    )
