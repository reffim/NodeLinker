import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    oidc_sub: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    oidc_provider: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    role: Mapped[str] = mapped_column(
        Enum("admin", "operator", "viewer", name="user_role"),
        nullable=False,
        default="operator",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    jobs: Mapped[list["Job"]] = relationship("Job", back_populates="creator")
    credentials: Mapped[list["Credential"]] = relationship("Credential", back_populates="creator")


# ---------------------------------------------------------------------------
# Credentials
# Metadata only — actual secret material is stored in HashiCorp Vault.
# `vault_path` is the KV v2 path used to retrieve the secret.
# ---------------------------------------------------------------------------
class Credential(Base):
    __tablename__ = "credentials"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # type: 'ssh_key' | 'ssh_password'
    type: Mapped[str] = mapped_column(
        Enum("ssh_key", "ssh_password", name="credential_type"),
        nullable=False,
    )
    vault_path: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    creator: Mapped[Optional["User"]] = relationship("User", back_populates="credentials")
    nodes: Mapped[list["Node"]] = relationship("Node", back_populates="credential")


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=22)
    ssh_user: Mapped[str] = mapped_column(String(64), nullable=False, default="root")
    # FK to credentials table; NULL = use Ansible default key discovery
    credential_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        Enum("online", "offline", "unreachable", "unknown", name="node_status"),
        nullable=False,
        default="unknown",
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    tags: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    credential: Mapped[Optional["Credential"]] = relationship("Credential", back_populates="nodes")
    job_nodes: Mapped[list["JobNode"]] = relationship("JobNode", back_populates="node")


# ---------------------------------------------------------------------------
# Playbooks
# ---------------------------------------------------------------------------
class Playbook(Base):
    __tablename__ = "playbooks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(
        Enum("local", "git", name="playbook_source"),
        nullable=False,
        default="local",
    )
    git_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    git_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    exclusive_group: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    jobs: Mapped[list["Job"]] = relationship("Job", back_populates="playbook")


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    playbook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("playbooks.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Enum("pending", "running", "success", "failed", "cancelled", name="job_status"),
        nullable=False,
        default="pending",
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    exclusive_lock_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    playbook: Mapped["Playbook"] = relationship("Playbook", back_populates="jobs")
    creator: Mapped[Optional["User"]] = relationship("User", back_populates="jobs")
    job_nodes: Mapped[list["JobNode"]] = relationship("JobNode", back_populates="job")


# ---------------------------------------------------------------------------
# Job-Node mapping
# log_file_url: points to Object Storage (S3) or Local FS path where the
# compressed log archive is stored after the job completes.
# Real-time streaming is done via Redis pub/sub; this is the persistent record.
# ---------------------------------------------------------------------------
class JobNode(Base):
    __tablename__ = "job_nodes"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(
        Enum("pending", "running", "success", "failed", name="job_node_status"),
        nullable=False,
        default="pending",
    )
    exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    log_file_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    job: Mapped["Job"] = relationship("Job", back_populates="job_nodes")
    node: Mapped[Optional["Node"]] = relationship("Node", back_populates="job_nodes")
