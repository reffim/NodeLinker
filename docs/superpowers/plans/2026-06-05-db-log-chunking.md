# DB Log Chunking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Redis pub/sub + gzip file log storage with a `job_log_chunks` PostgreSQL table; frontend polls a REST endpoint every 2 seconds instead of using a WebSocket.

**Architecture:** The Celery worker buffers log lines in memory and flushes a single DB row every 1.5 seconds (`job_log_chunks`). The FastAPI `GET /jobs/{id}/logs/chunks?after={id}` endpoint serves incremental chunks. The frontend `useJobLogsPoll` hook polls that endpoint and accumulates lines for display, replacing both `useJobLogsWS` and the archived gzip fallback in `LogPanel`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, Alembic, aiofiles, Celery, React 19, TypeScript, TanStack Query v5

---

## File Map

| Action | Path |
|--------|------|
| Create | `backend/alembic/versions/0005_add_job_log_chunks.py` |
| Modify | `backend/app/models/models.py` |
| Modify | `backend/app/schemas/jobs.py` |
| Modify | `backend/app/api/v1/jobs.py` |
| Modify | `backend/app/worker/tasks/job_runner.py` |
| Delete | `backend/app/ws/jobs.py` |
| Modify | `backend/app/main.py` |
| Modify | `backend/tests/conftest.py` |
| Create | `backend/tests/test_job_log_chunks_api.py` |
| Modify | `frontend/src/types/index.ts` |
| Modify | `frontend/src/api/jobs.ts` |
| Create | `frontend/src/hooks/useJobLogsPoll.ts` |
| Delete | `frontend/src/hooks/useJobLogsWS.ts` |
| Modify | `frontend/src/components/LogPanel.tsx` |

---

## Task 1: Alembic Migration

**Files:**
- Create: `backend/alembic/versions/0005_add_job_log_chunks.py`

- [ ] **Step 1: Write the migration file**

```python
# backend/alembic/versions/0005_add_job_log_chunks.py
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
```

- [ ] **Step 2: Run the migration**

```bash
docker exec nodelinker-backend-1 alembic upgrade head
```

Expected output ends with:
```
INFO  [alembic.runtime.migration] Running upgrade 0004 -> 0005, add job_log_chunks table, drop log_file_url
```

- [ ] **Step 3: Verify the table exists**

```bash
docker exec nodelinker-db-1 psql -U nodelinker -d nodelinker -c "\d job_log_chunks"
```

Expected: table with columns `id, job_id, node_id, chunk_seq, content, created_at`.

```bash
docker exec nodelinker-db-1 psql -U nodelinker -d nodelinker -c "\d job_nodes"
```

Expected: `log_file_url` column is gone.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/0005_add_job_log_chunks.py
git commit -m "feat: migration 0005 — add job_log_chunks, drop log_file_url"
```

---

## Task 2: SQLAlchemy Model

**Files:**
- Modify: `backend/app/models/models.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_job_log_chunks_api.py  (create file)
def test_job_log_chunk_model_importable():
    from app.models.models import JobLogChunk
    assert JobLogChunk.__tablename__ == "job_log_chunks"


def test_job_node_has_no_log_file_url():
    from app.models.models import JobNode
    assert not hasattr(JobNode, "log_file_url")
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd /home/reffim/workspace/project_minerva/backend && .venv/bin/pytest tests/test_job_log_chunks_api.py::test_job_log_chunk_model_importable -v
```

Expected: `FAILED` — `cannot import name 'JobLogChunk'`

- [ ] **Step 3: Add `JobLogChunk` and update `JobNode` in `models.py`**

Replace the entire `JobNode` class and the comment above it (lines 173–198 in the original file) with:

```python
# ---------------------------------------------------------------------------
# Job-Node mapping
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

    job: Mapped["Job"] = relationship("Job", back_populates="job_nodes")
    node: Mapped[Optional["Node"]] = relationship("Node", back_populates="job_nodes")


# ---------------------------------------------------------------------------
# Job log chunks
# Logs are buffered in memory during job execution and flushed every 1.5 s
# as a single row. The frontend polls GET /jobs/{id}/logs/chunks?after={id}.
# ---------------------------------------------------------------------------
class JobLogChunk(Base):
    __tablename__ = "job_log_chunks"

    id: Mapped[int] = mapped_column(
        sa.BigInteger, primary_key=True, autoincrement=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False
    )
    chunk_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

Also add `import sqlalchemy as sa` to the existing imports at the top of `models.py` (it's not there yet — add after `from sqlalchemy.orm import ...`):

```python
import sqlalchemy as sa
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/reffim/workspace/project_minerva/backend && .venv/bin/pytest tests/test_job_log_chunks_api.py::test_job_log_chunk_model_importable tests/test_job_log_chunks_api.py::test_job_node_has_no_log_file_url -v
```

Expected: both `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/models.py backend/tests/test_job_log_chunks_api.py
git commit -m "feat: add JobLogChunk model, remove log_file_url from JobNode"
```

---

## Task 3: Pydantic Schemas

**Files:**
- Modify: `backend/app/schemas/jobs.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_job_log_chunks_api.py`:

```python
def test_job_log_chunk_response_schema():
    from app.schemas.jobs import JobLogChunkResponse
    import uuid
    from datetime import datetime, timezone
    chunk = JobLogChunkResponse(
        id=1,
        job_id=uuid.uuid4(),
        node_id=uuid.uuid4(),
        chunk_seq=0,
        content="line one\nline two",
        created_at=datetime.now(timezone.utc),
    )
    assert chunk.chunk_seq == 0


def test_job_node_response_has_no_log_file_url():
    from app.schemas.jobs import JobNodeResponse
    import uuid
    jn = JobNodeResponse(node_id=uuid.uuid4(), status="pending", exit_code=None)
    assert not hasattr(jn, "log_file_url")
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /home/reffim/workspace/project_minerva/backend && .venv/bin/pytest tests/test_job_log_chunks_api.py::test_job_log_chunk_response_schema tests/test_job_log_chunks_api.py::test_job_node_response_has_no_log_file_url -v
```

Expected: `FAILED`

- [ ] **Step 3: Replace `backend/app/schemas/jobs.py` entirely**

```python
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class JobCreate(BaseModel):
    playbook_id: uuid.UUID
    node_ids: list[uuid.UUID] = Field(..., min_length=1, description="One or more target node IDs")
    extra_vars: Optional[dict] = Field(None, description="Extra variables passed to ansible-runner")


class JobNodeResponse(BaseModel):
    node_id: uuid.UUID
    status: str
    exit_code: Optional[int]

    model_config = {"from_attributes": True}


class JobResponse(BaseModel):
    id: uuid.UUID
    playbook_id: uuid.UUID
    status: str
    created_by: Optional[uuid.UUID]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    exclusive_lock_key: Optional[str]
    created_at: datetime
    job_nodes: list[JobNodeResponse]

    model_config = {"from_attributes": True}


class JobLogChunkResponse(BaseModel):
    id: int
    job_id: uuid.UUID
    node_id: uuid.UUID
    chunk_seq: int
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/reffim/workspace/project_minerva/backend && .venv/bin/pytest tests/test_job_log_chunks_api.py -v
```

Expected: all 4 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/jobs.py backend/tests/test_job_log_chunks_api.py
git commit -m "feat: add JobLogChunkResponse schema, remove log_file_url from JobNodeResponse"
```

---

## Task 4: API Endpoint

**Files:**
- Modify: `backend/app/api/v1/jobs.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_job_log_chunks_api.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_scalar_result(obj):
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    result.scalars.return_value.all.return_value = [obj] if obj else []
    return result


def _make_scalars_result(objs):
    result = MagicMock()
    result.scalars.return_value.all.return_value = objs
    return result


@pytest.mark.asyncio
async def test_get_job_log_chunks_returns_chunks():
    from app.api.v1.jobs import get_job_log_chunks
    from app.schemas.jobs import JobLogChunkResponse
    from datetime import datetime, timezone

    job_id = uuid.uuid4()
    node_id = uuid.uuid4()

    mock_job = MagicMock()
    mock_job.id = job_id

    chunk = MagicMock()
    chunk.id = 42
    chunk.job_id = job_id
    chunk.node_id = node_id
    chunk.chunk_seq = 0
    chunk.content = "hello\nworld"
    chunk.created_at = datetime.now(timezone.utc)

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _make_scalar_result(mock_job),   # job existence check
            _make_scalars_result([chunk]),    # chunks query
        ]
    )

    user = MagicMock()
    result = await get_job_log_chunks(job_id=job_id, after=0, node_id=None, db=db, _current_user=user)
    assert len(result) == 1
    assert result[0].id == 42


@pytest.mark.asyncio
async def test_get_job_log_chunks_404_when_job_missing():
    from app.api.v1.jobs import get_job_log_chunks
    from fastapi import HTTPException

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_scalar_result(None))

    user = MagicMock()
    with pytest.raises(HTTPException) as exc_info:
        await get_job_log_chunks(job_id=uuid.uuid4(), after=0, node_id=None, db=db, _current_user=user)
    assert exc_info.value.status_code == 404
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /home/reffim/workspace/project_minerva/backend && .venv/bin/pytest tests/test_job_log_chunks_api.py::test_get_job_log_chunks_returns_chunks tests/test_job_log_chunks_api.py::test_get_job_log_chunks_404_when_job_missing -v
```

Expected: `FAILED` — `cannot import name 'get_job_log_chunks'`

- [ ] **Step 3: Replace `backend/app/api/v1/jobs.py` entirely**

```python
"""
Job API: create a job (dispatches to Celery per node), get status, get log chunks.

Routes:
  POST  /api/v1/jobs
  GET   /api/v1/jobs/{job_id}
  GET   /api/v1/jobs/{job_id}/logs/chunks
  POST  /api/v1/jobs/{job_id}/cancel
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.models import Job, JobLogChunk, JobNode, Node, Playbook, User
from app.schemas.jobs import JobCreate, JobLogChunkResponse, JobNodeResponse, JobResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobResponse])
async def list_jobs(
    job_status: str | None = None,
    playbook_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[Job]:
    """List jobs with optional filters. Results are ordered newest-first."""
    query = select(Job).options(selectinload(Job.job_nodes)).order_by(Job.created_at.desc())
    if job_status is not None:
        query = query.where(Job.status == job_status)
    if playbook_id is not None:
        query = query.where(Job.playbook_id == playbook_id)
    query = query.offset(offset).limit(min(limit, 200))
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    payload: JobCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Job:
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    pb_result = await db.execute(select(Playbook).where(Playbook.id == payload.playbook_id))
    playbook = pb_result.scalar_one_or_none()
    if playbook is None:
        raise HTTPException(status_code=404, detail="Playbook not found")

    node_ids = list(dict.fromkeys(payload.node_ids))
    node_result = await db.execute(select(Node).where(Node.id.in_(node_ids)))
    nodes = {n.id: n for n in node_result.scalars().all()}
    missing = [nid for nid in node_ids if nid not in nodes]
    if missing:
        raise HTTPException(status_code=404, detail=f"Nodes not found: {missing}")

    exclusive_lock_key: str | None = None
    if playbook.exclusive_group:
        exclusive_lock_key = f"exclusive:{playbook.exclusive_group}"

    job = Job(
        playbook_id=payload.playbook_id,
        created_by=current_user.id,
        status="pending",
        exclusive_lock_key=exclusive_lock_key,
    )
    db.add(job)
    await db.flush()

    for node_id in node_ids:
        db.add(JobNode(job_id=job.id, node_id=node_id, status="pending"))

    await db.commit()

    result = await db.execute(
        select(Job).where(Job.id == job.id).options(selectinload(Job.job_nodes))
    )
    job = result.scalar_one()

    from app.worker.tasks.job_runner import run_job
    for node_id in node_ids:
        run_job.delay(
            job_id=str(job.id),
            playbook_id=str(payload.playbook_id),
            node_id=str(node_id),
            extra_vars=payload.extra_vars or {},
        )

    return job


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> Job:
    result = await db.execute(
        select(Job).where(Job.id == job_id).options(selectinload(Job.job_nodes))
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/{job_id}/logs/chunks", response_model=list[JobLogChunkResponse])
async def get_job_log_chunks(
    job_id: uuid.UUID,
    after: int = 0,
    node_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[JobLogChunk]:
    """
    Return log chunks for a job, in insertion order.
    Use `after` (the `id` of the last seen chunk) for incremental polling.
    """
    job_result = await db.execute(select(Job).where(Job.id == job_id))
    if job_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Job not found")

    query = (
        select(JobLogChunk)
        .where(JobLogChunk.job_id == job_id, JobLogChunk.id > after)
        .order_by(JobLogChunk.id)
    )
    if node_id is not None:
        query = query.where(JobLogChunk.node_id == node_id)

    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Job:
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    result = await db.execute(
        select(Job).where(Job.id == job_id).options(selectinload(Job.job_nodes))
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("pending", "running"):
        raise HTTPException(status_code=409, detail=f"Cannot cancel job in status '{job.status}'")
    job.status = "cancelled"
    await db.commit()
    await db.refresh(job)
    return job
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/reffim/workspace/project_minerva/backend && .venv/bin/pytest tests/test_job_log_chunks_api.py -v
```

Expected: all 6 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/jobs.py backend/tests/test_job_log_chunks_api.py
git commit -m "feat: add GET /jobs/{id}/logs/chunks endpoint, remove old log endpoints"
```

---

## Task 5: job_runner Refactor

**Files:**
- Modify: `backend/app/worker/tasks/job_runner.py`

This task replaces `_tail_and_stream` + `_save_logs_to_storage` with `_tail_and_chunk`, updates `_finish_node` to remove `log_file_url`, and removes all Redis log publishing.

- [ ] **Step 1: Replace the entire file**

```python
"""
Celery task: run an Ansible playbook on a single node via ansible-runner.

One task is dispatched per (job, node) pair. Each task:
  1. Acquires Redis exclusive lock with TTL if playbook has exclusive_group
  2. Starts a lock heartbeat coroutine to renew the TTL periodically
  3. Marks job + job_node as `running`
  4. Fetches SSH credential from HashiCorp Vault (via node.credential)
  5. Writes playbook YAML + inventory (with Vault-fetched credentials) to a temp dir
  6. Starts ansible_runner.run_async() in a thread
  7. Tails the stdout artifact with aiofiles, buffering lines and flushing to
     job_log_chunks every 1.5 s
  8. Updates job_node.status + exit_code
  9. If this is the last node to finish, updates the overall job status
 10. Cancels the heartbeat coroutine and releases the exclusive lock
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import tempfile

import aiofiles
import ansible_runner
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.vault import get_credential
from app.db.session import async_session_factory
from app.models.models import Job, JobLogChunk, JobNode, Node, Playbook
from app.services.lock_service import (
    LOCK_TTL_SECONDS,
    acquire_lock,
    extend_lock,
    release_lock,
)
from app.worker.celery_app import celery_app

LOCK_RETRY_COUNTDOWN: int = 30
LOCK_MAX_RETRIES: int = 120
HEARTBEAT_INTERVAL: int = LOCK_TTL_SECONDS // 2

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lock heartbeat
# ---------------------------------------------------------------------------

async def _lock_heartbeat(
    redis_client: aioredis.Redis,
    node_id: str,
    playbook_group: str,
    token: str,
    stop_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=HEARTBEAT_INTERVAL)
        except asyncio.TimeoutError:
            pass

        if stop_event.is_set():
            break

        ok = await extend_lock(redis_client, node_id, playbook_group, token)
        if not ok:
            logger.warning(
                "heartbeat: lock extend failed — lock may have expired node=%s group=%s job=%s",
                node_id, playbook_group, token,
            )


# ---------------------------------------------------------------------------
# Inventory & playbook helpers
# ---------------------------------------------------------------------------

async def _build_inventory(node: Any, credential_data: dict | None, private_data_dir: str) -> None:
    """Write ansible inventory file, injecting credentials from Vault."""
    inv_dir = Path(private_data_dir) / "inventory"
    inv_dir.mkdir(parents=True, exist_ok=True)
    host_vars: dict[str, str] = {
        "ansible_host": node.host,
        "ansible_port": str(node.port),
        "ansible_user": node.ssh_user,
        "ansible_remote_tmp": "/tmp",
    }
    if credential_data:
        if "private_key" in credential_data:
            key_path = Path(private_data_dir) / "ssh_key"
            key_path.write_text(credential_data["private_key"])
            key_path.chmod(0o600)
            host_vars["ansible_ssh_private_key_file"] = str(key_path)
        elif "password" in credential_data:
            host_vars["ansible_ssh_pass"] = credential_data["password"]

    vars_str = " ".join(f"{k}={v}" for k, v in host_vars.items())
    (inv_dir / "hosts").write_text(f"[targets]\n{node.name} {vars_str}\n")


def _write_playbook(content: str, private_data_dir: str, name: str = "site.yml") -> str:
    project_dir = Path(private_data_dir) / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / name).write_text(content)
    return name


def _start_runner(
    private_data_dir: str,
    playbook_name: str,
    extra_vars: dict,
) -> tuple[Any, Any]:
    runner_kwargs: dict[str, Any] = {
        "private_data_dir": private_data_dir,
        "playbook": playbook_name,
        "quiet": False,
        "rotate_artifacts": 5,
        "envvars": {
            "ANSIBLE_HOST_KEY_CHECKING": "False",
        },
    }
    if extra_vars:
        runner_kwargs["extravars"] = extra_vars
    return ansible_runner.run_async(**runner_kwargs)


# ---------------------------------------------------------------------------
# Async log-tail with DB chunking
# ---------------------------------------------------------------------------

async def _tail_and_chunk(
    private_data_dir: str,
    runner_thread: Any,
    job_id: str,
    node_id: str,
) -> None:
    """
    Tail ansible-runner stdout asynchronously.
    Buffer lines in memory and flush to job_log_chunks every 1.5 s.
    """
    # Wait up to 5 s for ansible-runner to create the stdout artifact
    stdout_path: Path | None = None
    for _ in range(50):
        artifacts = Path(private_data_dir) / "artifacts"
        if artifacts.exists():
            subdirs = [d for d in artifacts.iterdir() if d.is_dir()]
            if subdirs:
                candidate = subdirs[0] / "stdout"
                if candidate.exists():
                    stdout_path = candidate
                    break
        await asyncio.sleep(0.1)

    buffer: list[str] = []
    chunk_seq = 0
    last_flush = asyncio.get_event_loop().time()

    async def _flush() -> None:
        nonlocal chunk_seq, last_flush
        if not buffer:
            return
        async with async_session_factory() as session:
            session.add(JobLogChunk(
                job_id=uuid.UUID(job_id),
                node_id=uuid.UUID(node_id),
                chunk_seq=chunk_seq,
                content="\n".join(buffer),
            ))
            await session.commit()
        chunk_seq += 1
        buffer.clear()
        last_flush = asyncio.get_event_loop().time()

    if stdout_path:
        async with aiofiles.open(stdout_path, "r", errors="replace") as f:
            while True:
                raw = await f.readline()
                if raw:
                    buffer.append(raw.rstrip("\n"))
                    if asyncio.get_event_loop().time() - last_flush >= 1.5:
                        await _flush()
                elif not runner_thread.is_alive():
                    # Thread finished — drain any remaining bytes then flush
                    async for raw in f:
                        buffer.append(raw.rstrip("\n"))
                    await _flush()
                    break
                else:
                    if buffer and asyncio.get_event_loop().time() - last_flush >= 1.5:
                        await _flush()
                    await asyncio.sleep(0.1)
    else:
        # stdout file never appeared — just wait for the thread to finish
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, runner_thread.join)


# ---------------------------------------------------------------------------
# Async DB helpers
# ---------------------------------------------------------------------------

async def _load_context(job_id: str, node_id: str) -> tuple[Job, JobNode, Playbook, Node] | None:
    async with async_session_factory() as session:
        job_res = await session.execute(
            select(Job).where(Job.id == uuid.UUID(job_id)).options(
                selectinload(Job.playbook), selectinload(Job.job_nodes)
            )
        )
        job = job_res.scalar_one_or_none()
        if job is None:
            logger.error("run_job: job %s not found", job_id)
            return None

        jn_res = await session.execute(
            select(JobNode).where(
                JobNode.job_id == uuid.UUID(job_id),
                JobNode.node_id == uuid.UUID(node_id),
            )
        )
        job_node = jn_res.scalar_one_or_none()
        if job_node is None:
            logger.error("run_job: job_node not found job=%s node=%s", job_id, node_id)
            return None

        node_res = await session.execute(
            select(Node).where(Node.id == uuid.UUID(node_id)).options(
                selectinload(Node.credential)
            )
        )
        node = node_res.scalar_one_or_none()
        if node is None:
            logger.error("run_job: node %s not found", node_id)
            return None

        return job, job_node, job.playbook, node


async def _mark_running(job_id: str, node_id: str) -> None:
    async with async_session_factory() as session:
        job_res = await session.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
        job = job_res.scalar_one_or_none()
        if job and job.status == "pending":
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)

        jn_res = await session.execute(
            select(JobNode).where(
                JobNode.job_id == uuid.UUID(job_id),
                JobNode.node_id == uuid.UUID(node_id),
            )
        )
        jn = jn_res.scalar_one_or_none()
        if jn:
            jn.status = "running"

        await session.commit()


async def _finish_node(
    job_id: str,
    node_id: str,
    node_status: str,
    exit_code: int | None,
) -> None:
    """Update job_node status and, if all nodes finished, update the overall job status."""
    async with async_session_factory() as session:
        jn_res = await session.execute(
            select(JobNode).where(
                JobNode.job_id == uuid.UUID(job_id),
                JobNode.node_id == uuid.UUID(node_id),
            )
        )
        jn = jn_res.scalar_one_or_none()
        if jn:
            jn.status = node_status
            jn.exit_code = exit_code

        await session.flush()

        all_nodes_res = await session.execute(
            select(JobNode).where(JobNode.job_id == uuid.UUID(job_id))
        )
        all_nodes = all_nodes_res.scalars().all()
        terminal = {"success", "failed"}
        if all(n.status in terminal for n in all_nodes):
            job_res = await session.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
            job = job_res.scalar_one_or_none()
            if job and job.status not in ("cancelled",):
                overall = "success" if all(n.status == "success" for n in all_nodes) else "failed"
                job.status = overall
                job.finished_at = datetime.now(timezone.utc)

        await session.commit()


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

@celery_app.task(
    name="app.worker.tasks.job_runner.run_job",
    bind=True,
    max_retries=LOCK_MAX_RETRIES,
)
def run_job(
    self,
    job_id: str,
    playbook_id: str,  # noqa: ARG001
    node_id: str,
    extra_vars: dict,
) -> dict:
    """Execute an Ansible playbook on a single node.

    - SSH credentials are fetched from HashiCorp Vault via node.credential.
    - Log lines are buffered and flushed to job_log_chunks every 1.5 s.
    - If the playbook has an exclusive_group, a Redis lock with TTL is held,
      with a heartbeat coroutine renewing it periodically to prevent deadlocks.
    """
    logger.info("run_job: job=%s node=%s", job_id, node_id)

    async def _execute() -> dict:
        redis_client = aioredis.from_url(settings.REDIS_URL)
        lock_acquired = False
        lock_node_id: str | None = None
        lock_group: str | None = None
        heartbeat_task: asyncio.Task | None = None
        stop_heartbeat = asyncio.Event()

        try:
            ctx = await _load_context(job_id, node_id)
            if ctx is None:
                return {"status": "failed", "error": "context not found"}
            job, _jn, playbook, node = ctx

            if job.status == "cancelled":
                return {"status": "cancelled"}

            # ------------------------------------------------------------------
            # Exclusive lock: acquire with TTL, start heartbeat to renew
            # ------------------------------------------------------------------
            if playbook.exclusive_group:
                lock_node_id = node_id
                lock_group = playbook.exclusive_group
                lock_acquired = await acquire_lock(
                    redis_client,
                    node_id=node_id,
                    playbook_group=playbook.exclusive_group,
                    token=job_id,
                )
                if not lock_acquired:
                    logger.info(
                        "run_job: lock held for node=%s group=%s; retrying job=%s in %ds",
                        node_id, playbook.exclusive_group, job_id, LOCK_RETRY_COUNTDOWN,
                    )
                    raise self.retry(countdown=LOCK_RETRY_COUNTDOWN)

                logger.info(
                    "run_job: lock acquired node=%s group=%s job=%s",
                    node_id, playbook.exclusive_group, job_id,
                )
                heartbeat_task = asyncio.create_task(
                    _lock_heartbeat(redis_client, node_id, lock_group, job_id, stop_heartbeat)
                )

            if not playbook.content:
                await _finish_node(job_id, node_id, "failed", None)
                return {"status": "failed", "error": "playbook has no content"}

            await _mark_running(job_id, node_id)

            # ------------------------------------------------------------------
            # Fetch SSH credential from Vault
            # ------------------------------------------------------------------
            credential_data: dict | None = None
            if node.credential:
                try:
                    credential_data = await get_credential(node.credential.vault_path)
                except Exception as exc:
                    logger.error(
                        "run_job: vault credential fetch failed node=%s: %s", node_id, exc
                    )

            rc: int | None = None
            success = False

            with tempfile.TemporaryDirectory(prefix="nodelinker_job_") as tmpdir:
                try:
                    await _build_inventory(node, credential_data, tmpdir)
                    playbook_name = _write_playbook(playbook.content, tmpdir)

                    runner_thread, runner = _start_runner(tmpdir, playbook_name, extra_vars)

                    await _tail_and_chunk(tmpdir, runner_thread, job_id, node_id)

                    rc = runner.rc
                    success = runner.status == "successful"

                except Exception as exc:
                    logger.exception("run_job: error job=%s node=%s: %s", job_id, node_id, exc)
                    rc = -1
                    success = False

            # Check cancellation during run
            async with async_session_factory() as session:
                check = await session.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
                current = check.scalar_one_or_none()
                if current and current.status == "cancelled":
                    await _finish_node(job_id, node_id, "failed", rc)
                    return {"status": "cancelled"}

            node_status = "success" if success else "failed"
            await _finish_node(job_id, node_id, node_status, rc)

            logger.info("run_job: job=%s node=%s status=%s rc=%s", job_id, node_id, node_status, rc)
            return {"status": node_status, "rc": rc}

        finally:
            stop_heartbeat.set()
            if heartbeat_task:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

            if lock_acquired and lock_node_id and lock_group:
                try:
                    await release_lock(redis_client, lock_node_id, lock_group, token=job_id)
                except Exception:
                    logger.exception(
                        "run_job: failed to release lock node=%s group=%s job=%s",
                        lock_node_id, lock_group, job_id,
                    )
            try:
                await redis_client.aclose()
            except Exception:
                pass

    return asyncio.run(_execute())
```

- [ ] **Step 2: Verify the module imports cleanly**

```bash
docker exec nodelinker-celery-worker-1 python -c "from app.worker.tasks.job_runner import run_job; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/worker/tasks/job_runner.py
git commit -m "feat: replace log streaming with DB chunking in job_runner"
```

---

## Task 6: Remove WebSocket Jobs Handler

**Files:**
- Delete: `backend/app/ws/jobs.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Delete the WS handler**

```bash
rm /home/reffim/workspace/project_minerva/backend/app/ws/jobs.py
```

- [ ] **Step 2: Update `backend/app/main.py`**

Replace the entire file with:

```python
import uuid

from fastapi import WebSocket
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.v1.router import router as v1_router
from app.api.v1.nodes import node_status_ws
from app.ws.workflow_runs import workflow_run_ws

app = FastAPI(
    title=settings.APP_NAME,
    description="NodeLinker – Infrastructure Automation Platform",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router)

app.add_api_websocket_route("/ws/nodes", node_status_ws)


@app.websocket("/ws/workflow-runs/{run_id}")
async def workflow_run_websocket(websocket: WebSocket, run_id: uuid.UUID) -> None:
    await workflow_run_ws(websocket, run_id)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
```

- [ ] **Step 3: Verify the backend starts cleanly**

```bash
docker restart nodelinker-backend-1 && sleep 4 && docker logs nodelinker-backend-1 --tail=5 2>&1
```

Expected: last line is `INFO:     Application startup complete.`

- [ ] **Step 4: Verify the old WS endpoint is gone**

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8888/ws/jobs/00000000-0000-0000-0000-000000000000
```

Expected: `426` (Upgrade Required — FastAPI's WebSocket-only rejection) or `404`. Either confirms the route is gone from HTTP.

- [ ] **Step 5: Run all backend tests**

```bash
cd /home/reffim/workspace/project_minerva/backend && .venv/bin/pytest tests/ -v
```

Expected: all tests `PASSED`

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py
git rm backend/app/ws/jobs.py
git commit -m "feat: remove WebSocket job log handler"
```

---

## Task 7: Frontend Types and API Client

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/jobs.ts`

- [ ] **Step 1: Update `frontend/src/types/index.ts`**

Remove the `JobLog` interface (lines 105–112) and add `JobLogChunk` in its place:

```typescript
export interface JobLogChunk {
  id: number
  job_id: string
  node_id: string
  chunk_seq: number
  content: string
  created_at: string
}
```

The removed block looks like:
```typescript
export interface JobLog {
  id: number
  job_id: string
  node_id: string | null
  line_number: number
  content: string
  created_at: string
}
```

- [ ] **Step 2: Update `frontend/src/api/jobs.ts`**

Replace the entire file with:

```typescript
import client from "./client"
import type { Job, JobCreate, JobLogChunk } from "../types"

export interface ListJobsParams {
  job_status?: string
  playbook_id?: string
  limit?: number
  offset?: number
}

export async function listJobs(params?: ListJobsParams): Promise<Job[]> {
  const { data } = await client.get<Job[]>("/jobs", { params })
  return data
}

export async function getJob(id: string): Promise<Job> {
  const { data } = await client.get<Job>(`/jobs/${id}`)
  return data
}

export async function createJob(payload: JobCreate): Promise<Job> {
  const { data } = await client.post<Job>("/jobs", payload)
  return data
}

export async function getJobLogChunks(jobId: string, after: number): Promise<JobLogChunk[]> {
  const { data } = await client.get<JobLogChunk[]>(`/jobs/${jobId}/logs/chunks`, {
    params: { after },
  })
  return data
}

export async function cancelJob(id: string): Promise<Job> {
  const { data } = await client.post<Job>(`/jobs/${id}/cancel`)
  return data
}
```

- [ ] **Step 3: TypeScript check**

```bash
cd /home/reffim/workspace/project_minerva/frontend && npx tsc -b --noEmit 2>&1
```

Expected: no output (no errors). If there are errors about `JobLog` still being imported somewhere, fix those imports.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/jobs.ts
git commit -m "feat: add JobLogChunk type and getJobLogChunks, remove JobLog"
```

---

## Task 8: `useJobLogsPoll` Hook

**Files:**
- Create: `frontend/src/hooks/useJobLogsPoll.ts`
- Delete: `frontend/src/hooks/useJobLogsWS.ts`

- [ ] **Step 1: Create `frontend/src/hooks/useJobLogsPoll.ts`**

```typescript
import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { getJobLogChunks } from '@/api/jobs'
import type { Job } from '@/types'

interface LogLine {
  node_id: string
  content: string
}

const TERMINAL = new Set(['success', 'failed', 'cancelled'])

export function useJobLogsPoll(jobId: string | undefined): { lines: LogLine[] } {
  const [lines, setLines] = useState<LogLine[]>([])
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!jobId) return

    setLines([])

    let lastId = 0
    let active = true

    const poll = async () => {
      if (!active) return
      try {
        const chunks = await getJobLogChunks(jobId, lastId)
        if (!active) return
        if (chunks.length > 0) {
          lastId = chunks[chunks.length - 1].id
          setLines((prev) => [
            ...prev,
            ...chunks.flatMap((c) =>
              c.content.split('\n').filter(Boolean).map((line) => ({
                node_id: c.node_id,
                content: line,
              }))
            ),
          ])
          return
        }
        // Empty poll — stop if job is terminal (all chunks already received)
        const job = queryClient.getQueryData<Job>(['job', jobId])
        if (job && TERMINAL.has(job.status)) {
          active = false
        }
      } catch {
        // keep polling on transient errors
      }
    }

    poll()
    const id = setInterval(poll, 2000)
    return () => {
      active = false
      clearInterval(id)
    }
  }, [jobId, queryClient])

  return { lines }
}
```

- [ ] **Step 2: Delete the old WS hook**

```bash
rm /home/reffim/workspace/project_minerva/frontend/src/hooks/useJobLogsWS.ts
```

- [ ] **Step 3: TypeScript check**

```bash
cd /home/reffim/workspace/project_minerva/frontend && npx tsc -b --noEmit 2>&1
```

Expected: errors about `useJobLogsWS` not found — that's expected since `LogPanel` still imports it. These will be fixed in Task 9.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/hooks/useJobLogsPoll.ts
git rm frontend/src/hooks/useJobLogsWS.ts
git commit -m "feat: add useJobLogsPoll hook, remove useJobLogsWS"
```

---

## Task 9: Simplify LogPanel

**Files:**
- Modify: `frontend/src/components/LogPanel.tsx`

- [ ] **Step 1: Replace `frontend/src/components/LogPanel.tsx` entirely**

```typescript
import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getJob } from '@/api/jobs'
import { getPlaybook } from '@/api/playbooks'
import { listNodes } from '@/api/nodes'
import { useJobLogsPoll } from '@/hooks/useJobLogsPoll'
import { Badge } from '@/components/ui/badge'
import type { Job } from '@/types'

function jobStatusVariant(
  status: Job['status'],
): 'success' | 'destructive' | 'warning' | 'secondary' | 'outline' {
  switch (status) {
    case 'success': return 'success'
    case 'failed': return 'destructive'
    case 'running': return 'warning'
    case 'cancelled': return 'secondary'
    default: return 'outline'
  }
}

const TERMINAL_STATUSES = new Set(['success', 'failed', 'cancelled'])

export function LogPanel({ jobId }: { jobId: string }) {
  const { lines } = useJobLogsPoll(jobId)
  const { data: job } = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => getJob(jobId),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const s = query.state.data?.status
      return !s || !TERMINAL_STATUSES.has(s) ? 2000 : false
    },
  })
  const { data: playbook } = useQuery({
    queryKey: ['playbook', job?.playbook_id],
    queryFn: () => getPlaybook(job!.playbook_id),
    enabled: !!job?.playbook_id,
  })
  const { data: allNodes = [] } = useQuery({
    queryKey: ['nodes'],
    queryFn: () => listNodes(),
  })
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines])

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-3 border-b border-border flex items-center gap-3">
        <span className="font-medium text-sm text-foreground">
          {playbook ? playbook.name : 'Job Logs'}
        </span>
        {job && <Badge variant={jobStatusVariant(job.status)}>{job.status}</Badge>}
      </div>

      {job && job.job_nodes.length > 0 && (
        <div className="px-4 py-2 border-b border-border flex gap-3 flex-wrap">
          {job.job_nodes.map((jn) => {
            const node = allNodes.find((n) => n.id === jn.node_id)
            return (
              <div
                key={jn.node_id}
                className="flex items-center gap-1.5 text-xs bg-muted/50 px-2 py-1 rounded"
              >
                <span className="font-medium text-foreground">
                  {node ? node.name : `${jn.node_id.slice(0, 8)}…`}
                </span>
                <Badge
                  variant={
                    jn.status === 'success'
                      ? 'success'
                      : jn.status === 'failed'
                      ? 'destructive'
                      : 'warning'
                  }
                  className="text-[10px] px-1 py-0 h-4"
                >
                  {jn.status}
                </Badge>
                {jn.exit_code !== null && (
                  <span className="text-muted-foreground">exit={jn.exit_code}</span>
                )}
              </div>
            )
          })}
        </div>
      )}

      <div className="flex-1 overflow-y-auto bg-gray-950 text-gray-100 font-mono text-xs p-4 space-y-0.5">
        {lines.length === 0 && (
          <p className="text-gray-500">Waiting for output…</p>
        )}
        {lines.map((line, i) => (
          <div key={i} className="leading-5">
            {line.node_id && (
              <span className="text-gray-500 mr-2">[{line.node_id.slice(0, 8)}]</span>
            )}
            <span>{line.content}</span>
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </div>
  )
}
```

- [ ] **Step 2: TypeScript check — must be clean**

```bash
cd /home/reffim/workspace/project_minerva/frontend && npx tsc -b --noEmit 2>&1
```

Expected: no output. If there are errors, fix them before proceeding.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/LogPanel.tsx
git commit -m "feat: simplify LogPanel to use useJobLogsPoll"
```

---

## Task 10: Rebuild and End-to-End Verification

- [ ] **Step 1: Restart the Celery worker to pick up job_runner changes**

```bash
docker restart nodelinker-celery-worker-1 && sleep 3 && docker logs nodelinker-celery-worker-1 --tail=5 2>&1
```

Expected: worker starts without import errors.

- [ ] **Step 2: Rebuild and redeploy nginx with new frontend**

```bash
docker compose -f /home/reffim/workspace/project_minerva/docker-compose.yml \
  -f /home/reffim/workspace/project_minerva/docker-compose.dev.yml \
  build --no-cache nginx 2>&1 | tail -5

docker compose -f /home/reffim/workspace/project_minerva/docker-compose.yml \
  -f /home/reffim/workspace/project_minerva/docker-compose.dev.yml \
  up -d nginx 2>&1 | tail -5
```

Expected: `nodelinker-nginx-1  Started`

- [ ] **Step 3: Verify the new API endpoint responds**

```bash
# Get an auth token first (use existing session cookie)
curl -s -c /tmp/cook.txt -X POST http://localhost:8888/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin1234"}' > /dev/null

# Test the chunks endpoint with a random UUID (should return 404)
curl -s -b /tmp/cook.txt \
  "http://localhost:8888/api/v1/jobs/00000000-0000-0000-0000-000000000001/logs/chunks" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('detail','OK'))"
```

Expected: `Job not found`

- [ ] **Step 4: Run a workflow from the UI and verify logs appear**

1. Open `http://localhost:8888` in the browser
2. Navigate to Workflows → select a workflow → click Run Now → select nodes → confirm
3. Navigate to the workflow run monitor
4. Wait ~5 seconds — log lines should appear in the right panel, updating every 2 seconds
5. After the workflow completes, verify logs remain visible (no "Loading archived logs…")

- [ ] **Step 5: Verify chunks in the DB during/after a run**

While or after a job runs, check the DB:

```bash
docker exec nodelinker-db-1 psql -U nodelinker -d nodelinker \
  -c "SELECT id, job_id, node_id, chunk_seq, length(content) as content_len, created_at FROM job_log_chunks ORDER BY id DESC LIMIT 10;"
```

Expected: rows with content_len > 0, chunk_seq incrementing per (job_id, node_id).

- [ ] **Step 6: Final commit**

```bash
git add -A
git status  # verify nothing unexpected is staged
git commit -m "feat: complete DB log chunking — polling replaces Redis pub/sub + WS"
```
