"""add workflow tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

workflow_run_status = postgresql.ENUM(
    "pending", "running", "success", "failed", "cancelled",
    name="workflow_run_status", create_type=False
)
workflow_run_step_status = postgresql.ENUM(
    "pending", "running", "success", "failed", "skipped",
    name="workflow_run_step_status", create_type=False
)


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE workflow_run_status AS ENUM
                ('pending', 'running', 'success', 'failed', 'cancelled');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE workflow_run_step_status AS ENUM
                ('pending', 'running', 'success', 'failed', 'skipped');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)

    op.create_table(
        "workflows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )

    op.create_table(
        "workflow_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("playbook_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("playbooks.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("on_failure_step_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workflow_steps.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("workflow_id", "order", name="uq_workflow_steps_workflow_order"),
    )
    op.create_index("ix_workflow_steps_workflow_id", "workflow_steps", ["workflow_id"])

    op.create_table(
        "workflow_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workflows.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", workflow_run_status, nullable=False, server_default="pending"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("node_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False),
        sa.Column("extra_vars", postgresql.JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_workflow_runs_workflow_id", "workflow_runs", ["workflow_id"])
    op.create_index("ix_workflow_runs_status", "workflow_runs", ["status"])

    op.create_table(
        "workflow_run_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workflow_step_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workflow_steps.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", workflow_run_step_status, nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_workflow_run_steps_run_id", "workflow_run_steps", ["workflow_run_id"])


def downgrade() -> None:
    op.drop_table("workflow_run_steps")
    op.drop_table("workflow_runs")
    op.drop_table("workflow_steps")
    op.drop_table("workflows")
    op.execute("DROP TYPE IF EXISTS workflow_run_step_status")
    op.execute("DROP TYPE IF EXISTS workflow_run_status")
