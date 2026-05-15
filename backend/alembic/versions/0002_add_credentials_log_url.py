"""add credentials table, update nodes, update job_nodes, drop job_logs

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-13

Changes:
  - CREATE TABLE credentials (SSH credential metadata; secrets in Vault)
  - ALTER TABLE nodes: DROP ssh_key_path, ADD credential_id FK
  - ALTER TABLE job_nodes: ADD log_file_url
  - DROP TABLE job_logs (logs stored in Object Storage, not RDBMS)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

credential_type = postgresql.ENUM("ssh_key", "ssh_password", name="credential_type", create_type=False)


def upgrade() -> None:
    # --- credentials enum & table ---
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE credential_type AS ENUM ('ssh_key', 'ssh_password');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)

    op.create_table(
        "credentials",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("type", credential_type, nullable=False),
        sa.Column("vault_path", sa.String(512), nullable=False, unique=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_credentials_vault_path", "credentials", ["vault_path"], unique=True)

    # --- nodes: swap ssh_key_path → credential_id ---
    op.drop_column("nodes", "ssh_key_path")
    op.add_column(
        "nodes",
        sa.Column(
            "credential_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("credentials.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_nodes_credential_id", "nodes", ["credential_id"])

    # --- job_nodes: add log_file_url ---
    op.add_column(
        "job_nodes",
        sa.Column("log_file_url", sa.String(1024), nullable=True),
    )

    # --- drop job_logs: logs are now stored in Object Storage / Local FS ---
    op.drop_index("ix_job_logs_node_id", table_name="job_logs")
    op.drop_index("ix_job_logs_job_id", table_name="job_logs")
    op.drop_table("job_logs")


def downgrade() -> None:
    # Recreate job_logs
    op.create_table(
        "job_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("nodes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_job_logs_job_id", "job_logs", ["job_id"])
    op.create_index("ix_job_logs_node_id", "job_logs", ["node_id"])

    # Revert job_nodes
    op.drop_column("job_nodes", "log_file_url")

    # Revert nodes
    op.drop_index("ix_nodes_credential_id", table_name="nodes")
    op.drop_column("nodes", "credential_id")
    op.add_column("nodes", sa.Column("ssh_key_path", sa.String(512), nullable=True))

    # Drop credentials
    op.drop_index("ix_credentials_vault_path", table_name="credentials")
    op.drop_table("credentials")
    op.execute("DROP TYPE IF EXISTS credential_type")
