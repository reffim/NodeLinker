"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enums
    op.execute("CREATE TYPE user_role AS ENUM ('admin', 'operator', 'viewer')")
    op.execute("CREATE TYPE node_status AS ENUM ('online', 'offline', 'unreachable', 'unknown')")
    op.execute("CREATE TYPE playbook_source AS ENUM ('local', 'git')")
    op.execute("CREATE TYPE job_status AS ENUM ('pending', 'running', 'success', 'failed', 'cancelled')")
    op.execute("CREATE TYPE job_node_status AS ENUM ('pending', 'running', 'success', 'failed')")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("oidc_sub", sa.String(255), nullable=True),
        sa.Column("oidc_provider", sa.String(64), nullable=True),
        sa.Column("role", sa.Enum("admin", "operator", "viewer", name="user_role", create_type=False), nullable=False, server_default="operator"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False, server_default="22"),
        sa.Column("ssh_user", sa.String(64), nullable=False, server_default="root"),
        sa.Column("ssh_key_path", sa.String(512), nullable=True),
        sa.Column("status", sa.Enum("online", "offline", "unreachable", "unknown", name="node_status", create_type=False), nullable=False, server_default="unknown"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "playbooks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("source_type", sa.Enum("local", "git", name="playbook_source", create_type=False), nullable=False, server_default="local"),
        sa.Column("git_url", sa.String(512), nullable=True),
        sa.Column("git_ref", sa.String(128), nullable=True),
        sa.Column("exclusive_group", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("playbook_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("playbooks.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.Enum("pending", "running", "success", "failed", "cancelled", name="job_status", create_type=False), nullable=False, server_default="pending"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exclusive_lock_key", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "job_nodes",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("status", sa.Enum("pending", "running", "success", "failed", name="job_node_status", create_type=False), nullable=False, server_default="pending"),
        sa.Column("exit_code", sa.Integer(), nullable=True),
    )

    op.create_table(
        "job_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_job_logs_job_id", "job_logs", ["job_id"])
    op.create_index("ix_job_logs_node_id", "job_logs", ["node_id"])


def downgrade() -> None:
    op.drop_table("job_logs")
    op.drop_table("job_nodes")
    op.drop_table("jobs")
    op.drop_table("playbooks")
    op.drop_table("nodes")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS job_node_status")
    op.execute("DROP TYPE IF EXISTS job_status")
    op.execute("DROP TYPE IF EXISTS playbook_source")
    op.execute("DROP TYPE IF EXISTS node_status")
    op.execute("DROP TYPE IF EXISTS user_role")
