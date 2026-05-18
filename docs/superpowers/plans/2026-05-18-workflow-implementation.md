# Workflow Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Workflow feature that chains multiple Ansible playbooks into a sequential, optionally-branching pipeline executed on a shared set of nodes.

**Architecture:** A `run_workflow` Celery orchestrator task drives step execution by creating a `Job` per step, polling the DB until the Job reaches a terminal state, then deciding whether to continue, branch, or stop. The existing `run_job` task is reused without modification. Four new DB tables (`workflows`, `workflow_steps`, `workflow_runs`, `workflow_run_steps`) hold definitions and execution state. A new Redis pub/sub channel and WebSocket endpoint notify clients of step transitions.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic, Celery 5, Redis pub/sub, PostgreSQL (UUID, ARRAY, JSONB), pytest + pytest-asyncio + httpx

---

## File Map

| File | Action |
|------|--------|
| `backend/requirements.txt` | Add `pytest`, `pytest-asyncio`, `anyio[trio]` |
| `backend/app/models/models.py` | Add `Workflow`, `WorkflowStep`, `WorkflowRun`, `WorkflowRunStep` |
| `backend/alembic/versions/0003_add_workflow_tables.py` | New migration |
| `backend/app/schemas/workflows.py` | New — all Pydantic schemas |
| `backend/app/api/v1/workflows.py` | New — CRUD + run endpoints |
| `backend/app/api/v1/router.py` | Register workflows router |
| `backend/app/worker/tasks/workflow_runner.py` | New — `run_workflow` Celery task |
| `backend/app/worker/celery_app.py` | Add `workflow_runner` to `include`, add stale-sweep beat task |
| `backend/app/ws/workflow_runs.py` | New — WebSocket handler |
| `backend/app/main.py` | Register new WebSocket route |
| `backend/tests/conftest.py` | New — pytest fixtures |
| `backend/tests/test_workflows_api.py` | New — API tests |
| `backend/tests/test_workflow_runner.py` | New — orchestrator unit tests |

---

### Task 1: Test infrastructure setup

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`

- [ ] **Step 1: Add test dependencies to requirements.txt**

Append these lines to `backend/requirements.txt`:
```
pytest==8.3.4
pytest-asyncio==0.24.0
anyio==4.7.0
```

- [ ] **Step 2: Create tests package**

Create `backend/tests/__init__.py` as an empty file.

- [ ] **Step 3: Write conftest.py**

Create `backend/tests/conftest.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
from datetime import datetime, timezone


def make_user(role="operator"):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.role = role
    return user


def make_workflow(name="Test Workflow", steps=None):
    wf = MagicMock()
    wf.id = uuid.uuid4()
    wf.name = name
    wf.description = None
    wf.created_at = datetime.now(timezone.utc)
    wf.updated_at = datetime.now(timezone.utc)
    wf.steps = steps or []
    return wf


def make_workflow_step(workflow_id=None, order=0, playbook_id=None, on_failure_step_id=None):
    step = MagicMock()
    step.id = uuid.uuid4()
    step.workflow_id = workflow_id or uuid.uuid4()
    step.order = order
    step.playbook_id = playbook_id or uuid.uuid4()
    step.on_failure_step_id = on_failure_step_id
    return step


def make_workflow_run(workflow_id=None, status="pending", node_ids=None):
    run = MagicMock()
    run.id = uuid.uuid4()
    run.workflow_id = workflow_id or uuid.uuid4()
    run.status = status
    run.node_ids = node_ids or [uuid.uuid4()]
    run.extra_vars = {}
    run.created_by = uuid.uuid4()
    run.started_at = None
    run.finished_at = None
    run.created_at = datetime.now(timezone.utc)
    run.workflow_run_steps = []
    return run


def make_workflow_run_step(run_id=None, step_id=None, status="pending", job_id=None):
    rs = MagicMock()
    rs.id = uuid.uuid4()
    rs.workflow_run_id = run_id or uuid.uuid4()
    rs.workflow_step_id = step_id or uuid.uuid4()
    rs.job_id = job_id
    rs.status = status
    rs.started_at = None
    rs.finished_at = None
    return rs
```

- [ ] **Step 4: Install test dependencies**

```bash
cd backend && .venv/bin/pip install pytest==8.3.4 pytest-asyncio==0.24.0 anyio==4.7.0
```

Expected: Successfully installed with no errors.

- [ ] **Step 5: Verify pytest can be found**

```bash
cd backend && .venv/bin/pytest --version
```

Expected output: `pytest 8.3.4`

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt backend/tests/
git commit -m "chore: add test infrastructure for workflow feature"
```

---

### Task 2: SQLAlchemy models

**Files:**
- Modify: `backend/app/models/models.py`

- [ ] **Step 1: Write the failing model import test**

Create `backend/tests/test_workflows_api.py`:
```python
def test_workflow_models_importable():
    from app.models.models import Workflow, WorkflowStep, WorkflowRun, WorkflowRunStep
    assert Workflow.__tablename__ == "workflows"
    assert WorkflowStep.__tablename__ == "workflow_steps"
    assert WorkflowRun.__tablename__ == "workflow_runs"
    assert WorkflowRunStep.__tablename__ == "workflow_run_steps"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && .venv/bin/pytest tests/test_workflows_api.py::test_workflow_models_importable -v
```

Expected: `ImportError` — models not defined yet.

- [ ] **Step 3: Add models to models.py**

Append to the bottom of `backend/app/models/models.py`:
```python
# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------
class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    steps: Mapped[list["WorkflowStep"]] = relationship(
        "WorkflowStep", back_populates="workflow",
        order_by="WorkflowStep.order", cascade="all, delete-orphan"
    )
    runs: Mapped[list["WorkflowRun"]] = relationship("WorkflowRun", back_populates="workflow")


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    order: Mapped[int] = mapped_column(Integer, nullable=False)
    playbook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("playbooks.id", ondelete="RESTRICT"), nullable=False
    )
    on_failure_step_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_steps.id", ondelete="SET NULL"), nullable=True
    )

    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="steps")
    playbook: Mapped["Playbook"] = relationship("Playbook")
    on_failure_step: Mapped[Optional["WorkflowStep"]] = relationship(
        "WorkflowStep", remote_side="WorkflowStep.id", foreign_keys="WorkflowStep.on_failure_step_id"
    )


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Enum("pending", "running", "success", "failed", "cancelled", name="workflow_run_status"),
        nullable=False,
        default="pending",
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    node_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False)
    extra_vars: Mapped[Optional[dict]] = mapped_column(
        __import__("sqlalchemy").dialects.postgresql.JSONB, nullable=True
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="runs")
    creator: Mapped[Optional["User"]] = relationship("User")
    workflow_run_steps: Mapped[list["WorkflowRunStep"]] = relationship(
        "WorkflowRunStep", back_populates="workflow_run",
        order_by="WorkflowRunStep.workflow_step_id", cascade="all, delete-orphan"
    )


class WorkflowRunStep(Base):
    __tablename__ = "workflow_run_steps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    workflow_step_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_steps.id", ondelete="RESTRICT"), nullable=False
    )
    job_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        Enum("pending", "running", "success", "failed", "skipped", name="workflow_run_step_status"),
        nullable=False,
        default="pending",
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    workflow_run: Mapped["WorkflowRun"] = relationship("WorkflowRun", back_populates="workflow_run_steps")
    workflow_step: Mapped["WorkflowStep"] = relationship("WorkflowStep")
    job: Mapped[Optional["Job"]] = relationship("Job")
```

Note: Replace the `extra_vars` column with a cleaner import. The JSONB import should use the already-imported `sqlalchemy.dialects.postgresql` at the top of the file. Add `JSONB` to the existing postgresql imports at the top of `models.py`:
```python
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
```
Then use `JSONB` directly in the `WorkflowRun.extra_vars` column:
```python
    extra_vars: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && .venv/bin/pytest tests/test_workflows_api.py::test_workflow_models_importable -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/models.py backend/tests/test_workflows_api.py
git commit -m "feat: add Workflow, WorkflowStep, WorkflowRun, WorkflowRunStep models"
```

---

### Task 3: Alembic migration

**Files:**
- Create: `backend/alembic/versions/0003_add_workflow_tables.py`

- [ ] **Step 1: Write the migration file**

Create `backend/alembic/versions/0003_add_workflow_tables.py`:
```python
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
```

- [ ] **Step 2: Verify migration syntax is valid**

```bash
cd backend && .venv/bin/python -c "import alembic.versions.0003_add_workflow_tables" 2>&1 || \
  .venv/bin/python -c "
import importlib.util, sys
spec = importlib.util.spec_from_file_location('m', 'alembic/versions/0003_add_workflow_tables.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
print('revision:', m.revision, 'down_revision:', m.down_revision)
"
```

Expected output: `revision: 0003 down_revision: 0002`

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/0003_add_workflow_tables.py
git commit -m "feat: add alembic migration for workflow tables (0003)"
```

---

### Task 4: Pydantic schemas

**Files:**
- Create: `backend/app/schemas/workflows.py`

- [ ] **Step 1: Write the failing schema test**

Add to `backend/tests/test_workflows_api.py`:
```python
def test_workflow_schemas_importable():
    from app.schemas.workflows import (
        WorkflowStepCreate,
        WorkflowCreate,
        WorkflowUpdate,
        WorkflowStepResponse,
        WorkflowResponse,
        WorkflowRunCreate,
        WorkflowRunStepResponse,
        WorkflowRunResponse,
    )
    assert WorkflowCreate.__name__ == "WorkflowCreate"


def test_workflow_create_validates_steps():
    from app.schemas.workflows import WorkflowCreate, WorkflowStepCreate
    import uuid
    wf = WorkflowCreate(
        name="My Pipeline",
        steps=[
            WorkflowStepCreate(order=0, playbook_id=uuid.uuid4(), on_failure_step_order=None),
        ]
    )
    assert len(wf.steps) == 1


def test_workflow_run_create_requires_node_ids():
    from app.schemas.workflows import WorkflowRunCreate
    import pytest as pt
    with pt.raises(Exception):
        WorkflowRunCreate(node_ids=[])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && .venv/bin/pytest tests/test_workflows_api.py::test_workflow_schemas_importable tests/test_workflows_api.py::test_workflow_create_validates_steps tests/test_workflows_api.py::test_workflow_run_create_requires_node_ids -v
```

Expected: `ImportError` on all three.

- [ ] **Step 3: Create schemas/workflows.py**

Create `backend/app/schemas/workflows.py`:
```python
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class WorkflowStepCreate(BaseModel):
    order: int = Field(..., ge=0)
    playbook_id: uuid.UUID
    on_failure_step_order: Optional[int] = Field(
        None, ge=0,
        description="order index of the fallback step within this workflow; resolved to FK after creation"
    )


class WorkflowCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    steps: list[WorkflowStepCreate] = Field(..., min_length=1)


class WorkflowUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None


class WorkflowStepResponse(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    order: int
    playbook_id: uuid.UUID
    on_failure_step_id: Optional[uuid.UUID]

    model_config = {"from_attributes": True}


class WorkflowResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime
    steps: list[WorkflowStepResponse]

    model_config = {"from_attributes": True}


class WorkflowRunCreate(BaseModel):
    node_ids: list[uuid.UUID] = Field(..., min_length=1)
    extra_vars: Optional[dict] = None


class WorkflowRunStepResponse(BaseModel):
    id: uuid.UUID
    workflow_run_id: uuid.UUID
    workflow_step_id: uuid.UUID
    job_id: Optional[uuid.UUID]
    status: str
    started_at: Optional[datetime]
    finished_at: Optional[datetime]

    model_config = {"from_attributes": True}


class WorkflowRunResponse(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    status: str
    created_by: Optional[uuid.UUID]
    node_ids: list[uuid.UUID]
    extra_vars: Optional[dict]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    created_at: datetime
    workflow_run_steps: list[WorkflowRunStepResponse]

    model_config = {"from_attributes": True}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && .venv/bin/pytest tests/test_workflows_api.py::test_workflow_schemas_importable tests/test_workflows_api.py::test_workflow_create_validates_steps tests/test_workflows_api.py::test_workflow_run_create_requires_node_ids -v
```

Expected: all three `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/workflows.py backend/tests/test_workflows_api.py
git commit -m "feat: add Pydantic schemas for workflows"
```

---

### Task 5: API endpoints

**Files:**
- Create: `backend/app/api/v1/workflows.py`
- Modify: `backend/app/api/v1/router.py`

- [ ] **Step 1: Write failing API unit tests**

Add to `backend/tests/test_workflows_api.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import uuid


def _make_db_result(obj):
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    result.scalars.return_value.all.return_value = [obj] if obj else []
    return result


def test_on_failure_step_order_resolution():
    """on_failure_step_order integer is resolved to a UUID FK after step creation."""
    from app.schemas.workflows import WorkflowStepCreate
    step = WorkflowStepCreate(order=1, playbook_id=uuid.uuid4(), on_failure_step_order=0)
    assert step.on_failure_step_order == 0


@pytest.mark.asyncio
async def test_create_workflow_resolves_on_failure_step():
    """POST /workflows creates steps then resolves on_failure_step_id FKs."""
    from app.api.v1.workflows import _resolve_on_failure_steps
    step_a = MagicMock()
    step_a.id = uuid.uuid4()
    step_a.order = 0

    step_b = MagicMock()
    step_b.id = uuid.uuid4()
    step_b.order = 1
    step_b.on_failure_step_id = None

    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()

    order_to_id = {0: step_a.id, 1: step_b.id}

    pending = [(step_b, 0)]  # step_b has on_failure_step_order=0

    await _resolve_on_failure_steps(db, pending, order_to_id)

    assert step_b.on_failure_step_id == step_a.id
    db.commit.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && .venv/bin/pytest tests/test_workflows_api.py::test_on_failure_step_order_resolution tests/test_workflows_api.py::test_create_workflow_resolves_on_failure_step -v
```

Expected: `ImportError` or `AttributeError`.

- [ ] **Step 3: Create api/v1/workflows.py**

Create `backend/app/api/v1/workflows.py`:
```python
"""
Workflow CRUD and run API.

Routes:
  GET    /api/v1/workflows
  POST   /api/v1/workflows
  GET    /api/v1/workflows/{id}
  PATCH  /api/v1/workflows/{id}
  DELETE /api/v1/workflows/{id}
  POST   /api/v1/workflows/{id}/runs
  GET    /api/v1/workflows/{id}/runs
  GET    /api/v1/workflow-runs/{run_id}
  POST   /api/v1/workflow-runs/{run_id}/cancel
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.models import (
    Node, Playbook, User,
    Workflow, WorkflowRun, WorkflowRunStep, WorkflowStep,
)
from app.schemas.workflows import (
    WorkflowCreate, WorkflowResponse, WorkflowRunCreate,
    WorkflowRunResponse, WorkflowUpdate,
)

router = APIRouter(tags=["workflows"])

WORKFLOW_RUN_STEPS_OPTION = selectinload(WorkflowRun.workflow_run_steps)
WORKFLOW_STEPS_OPTION = selectinload(Workflow.steps)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_workflow_or_404(db: AsyncSession, workflow_id: uuid.UUID) -> Workflow:
    result = await db.execute(
        select(Workflow).where(Workflow.id == workflow_id).options(WORKFLOW_STEPS_OPTION)
    )
    wf = result.scalar_one_or_none()
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return wf


async def _get_run_or_404(db: AsyncSession, run_id: uuid.UUID) -> WorkflowRun:
    result = await db.execute(
        select(WorkflowRun).where(WorkflowRun.id == run_id).options(WORKFLOW_RUN_STEPS_OPTION)
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="WorkflowRun not found")
    return run


async def _resolve_on_failure_steps(
    db: AsyncSession,
    pending: list[tuple["WorkflowStep", int]],
    order_to_id: dict[int, uuid.UUID],
) -> None:
    """Set on_failure_step_id on steps that had an on_failure_step_order reference."""
    for step, target_order in pending:
        if target_order not in order_to_id:
            raise HTTPException(
                status_code=422,
                detail=f"on_failure_step_order {target_order} does not match any step order in this workflow",
            )
        step.on_failure_step_id = order_to_id[target_order]
    await db.commit()


# ---------------------------------------------------------------------------
# Workflow definition CRUD
# ---------------------------------------------------------------------------

@router.get("/workflows", response_model=list[WorkflowResponse])
async def list_workflows(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[Workflow]:
    result = await db.execute(
        select(Workflow).options(WORKFLOW_STEPS_OPTION).order_by(Workflow.created_at)
    )
    return list(result.scalars().all())


@router.post("/workflows", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    payload: WorkflowCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Workflow:
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # Validate all referenced playbooks exist
    playbook_ids = {s.playbook_id for s in payload.steps}
    pb_result = await db.execute(select(Playbook).where(Playbook.id.in_(playbook_ids)))
    found_pbs = {pb.id for pb in pb_result.scalars().all()}
    missing = playbook_ids - found_pbs
    if missing:
        raise HTTPException(status_code=404, detail=f"Playbooks not found: {[str(m) for m in missing]}")

    wf = Workflow(name=payload.name, description=payload.description)
    db.add(wf)
    await db.flush()

    # Create steps; collect on_failure references for second-pass resolution
    order_to_step: dict[int, WorkflowStep] = {}
    pending_resolution: list[tuple[WorkflowStep, int]] = []

    for step_in in payload.steps:
        step = WorkflowStep(
            workflow_id=wf.id,
            order=step_in.order,
            playbook_id=step_in.playbook_id,
        )
        db.add(step)
        await db.flush()
        order_to_step[step_in.order] = step
        if step_in.on_failure_step_order is not None:
            pending_resolution.append((step, step_in.on_failure_step_order))

    order_to_id = {order: s.id for order, s in order_to_step.items()}
    await _resolve_on_failure_steps(db, pending_resolution, order_to_id)

    await db.refresh(wf)
    result = await db.execute(
        select(Workflow).where(Workflow.id == wf.id).options(WORKFLOW_STEPS_OPTION)
    )
    return result.scalar_one()


@router.get("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> Workflow:
    return await _get_workflow_or_404(db, workflow_id)


@router.patch("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: uuid.UUID,
    payload: WorkflowUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Workflow:
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    wf = await _get_workflow_or_404(db, workflow_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(wf, field, value)
    await db.commit()
    await db.refresh(wf)
    result = await db.execute(
        select(Workflow).where(Workflow.id == wf.id).options(WORKFLOW_STEPS_OPTION)
    )
    return result.scalar_one()


@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    wf = await _get_workflow_or_404(db, workflow_id)
    await db.delete(wf)
    await db.commit()


# ---------------------------------------------------------------------------
# Workflow runs
# ---------------------------------------------------------------------------

@router.post("/workflows/{workflow_id}/runs", response_model=WorkflowRunResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow_run(
    workflow_id: uuid.UUID,
    payload: WorkflowRunCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowRun:
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    wf = await _get_workflow_or_404(db, workflow_id)
    if not wf.steps:
        raise HTTPException(status_code=422, detail="Workflow has no steps")

    node_ids = list(dict.fromkeys(payload.node_ids))
    node_result = await db.execute(select(Node).where(Node.id.in_(node_ids)))
    found_nodes = {n.id for n in node_result.scalars().all()}
    missing = [nid for nid in node_ids if nid not in found_nodes]
    if missing:
        raise HTTPException(status_code=404, detail=f"Nodes not found: {missing}")

    run = WorkflowRun(
        workflow_id=wf.id,
        created_by=current_user.id,
        status="pending",
        node_ids=node_ids,
        extra_vars=payload.extra_vars or {},
    )
    db.add(run)
    await db.flush()

    # Pre-create all WorkflowRunStep records with status=pending
    for step in sorted(wf.steps, key=lambda s: s.order):
        db.add(WorkflowRunStep(
            workflow_run_id=run.id,
            workflow_step_id=step.id,
            status="pending",
        ))

    await db.commit()

    result = await db.execute(
        select(WorkflowRun).where(WorkflowRun.id == run.id).options(WORKFLOW_RUN_STEPS_OPTION)
    )
    run = result.scalar_one()

    # Dispatch orchestrator task
    from app.worker.tasks.workflow_runner import run_workflow  # avoid circular import
    run_workflow.delay(str(run.id))

    return run


@router.get("/workflows/{workflow_id}/runs", response_model=list[WorkflowRunResponse])
async def list_workflow_runs(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[WorkflowRun]:
    await _get_workflow_or_404(db, workflow_id)
    result = await db.execute(
        select(WorkflowRun)
        .where(WorkflowRun.workflow_id == workflow_id)
        .options(WORKFLOW_RUN_STEPS_OPTION)
        .order_by(WorkflowRun.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/workflow-runs/{run_id}", response_model=WorkflowRunResponse)
async def get_workflow_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> WorkflowRun:
    return await _get_run_or_404(db, run_id)


@router.post("/workflow-runs/{run_id}/cancel", response_model=WorkflowRunResponse)
async def cancel_workflow_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowRun:
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    run = await _get_run_or_404(db, run_id)
    if run.status not in ("pending", "running"):
        raise HTTPException(status_code=409, detail=f"Cannot cancel run in status '{run.status}'")
    run.status = "cancelled"
    await db.commit()
    await db.refresh(run)
    result = await db.execute(
        select(WorkflowRun).where(WorkflowRun.id == run_id).options(WORKFLOW_RUN_STEPS_OPTION)
    )
    return result.scalar_one()
```

- [ ] **Step 4: Register router in router.py**

Edit `backend/app/api/v1/router.py`:
```python
from fastapi import APIRouter

from app.api.v1 import auth, credentials, jobs, nodes, playbooks, workflows

router = APIRouter(prefix="/api/v1")

router.include_router(auth.router)
router.include_router(credentials.router)
router.include_router(nodes.router)
router.include_router(playbooks.router)
router.include_router(jobs.router)
router.include_router(workflows.router)
```

- [ ] **Step 5: Run API tests**

```bash
cd backend && .venv/bin/pytest tests/test_workflows_api.py::test_on_failure_step_order_resolution tests/test_workflows_api.py::test_create_workflow_resolves_on_failure_step -v
```

Expected: both `PASSED`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/workflows.py backend/app/api/v1/router.py backend/tests/test_workflows_api.py
git commit -m "feat: add workflow CRUD and run API endpoints"
```

---

### Task 6: Celery orchestrator task

**Files:**
- Create: `backend/app/worker/tasks/workflow_runner.py`
- Modify: `backend/app/worker/celery_app.py`

- [ ] **Step 1: Write failing orchestrator tests**

Create `backend/tests/test_workflow_runner.py`:
```python
import asyncio
import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import datetime, timezone


def _make_job(status="success"):
    job = MagicMock()
    job.id = uuid.uuid4()
    job.status = status
    return job


def _make_run_step(step_id=None, status="pending"):
    rs = MagicMock()
    rs.id = uuid.uuid4()
    rs.workflow_step_id = step_id or uuid.uuid4()
    rs.job_id = None
    rs.status = status
    rs.started_at = None
    rs.finished_at = None
    return rs


def _make_wf_step(order=0, playbook_id=None, on_failure_step_id=None):
    s = MagicMock()
    s.id = uuid.uuid4()
    s.order = order
    s.playbook_id = playbook_id or uuid.uuid4()
    s.on_failure_step_id = on_failure_step_id
    return s


def _make_run(status="pending", node_ids=None):
    run = MagicMock()
    run.id = uuid.uuid4()
    run.status = status
    run.node_ids = node_ids or [uuid.uuid4()]
    run.extra_vars = {}
    run.created_by = uuid.uuid4()
    run.workflow_id = uuid.uuid4()
    return run


@pytest.mark.asyncio
async def test_orchestrator_success_single_step():
    """A single-step workflow that succeeds marks the run as success."""
    from app.worker.tasks.workflow_runner import _execute_workflow

    wf_step = _make_wf_step(order=0)
    run = _make_run()
    run_step = _make_run_step(step_id=wf_step.id)

    job = _make_job(status="success")

    with patch("app.worker.tasks.workflow_runner._load_run_context") as mock_ctx, \
         patch("app.worker.tasks.workflow_runner._create_job_for_step", return_value=job) as mock_create, \
         patch("app.worker.tasks.workflow_runner._poll_until_done", return_value="success") as mock_poll, \
         patch("app.worker.tasks.workflow_runner._update_run_step") as mock_update_step, \
         patch("app.worker.tasks.workflow_runner._update_run") as mock_update_run, \
         patch("app.worker.tasks.workflow_runner._publish_event") as mock_pub:

        mock_ctx.return_value = (run, [wf_step], {wf_step.id: run_step})

        await _execute_workflow(str(run.id))

        mock_update_run.assert_any_call(run, "running", started_at=pytest.approx(datetime.now(timezone.utc), abs=2))
        mock_update_run.assert_any_call(run, "success", finished_at=pytest.approx(datetime.now(timezone.utc), abs=2))


@pytest.mark.asyncio
async def test_orchestrator_step_failure_no_fallback_fails_run():
    """A failed step with no on_failure_step_id marks the run as failed."""
    from app.worker.tasks.workflow_runner import _execute_workflow

    wf_step = _make_wf_step(order=0, on_failure_step_id=None)
    run = _make_run()
    run_step = _make_run_step(step_id=wf_step.id)
    job = _make_job(status="failed")

    with patch("app.worker.tasks.workflow_runner._load_run_context") as mock_ctx, \
         patch("app.worker.tasks.workflow_runner._create_job_for_step", return_value=job), \
         patch("app.worker.tasks.workflow_runner._poll_until_done", return_value="failed"), \
         patch("app.worker.tasks.workflow_runner._update_run_step"), \
         patch("app.worker.tasks.workflow_runner._update_run") as mock_update_run, \
         patch("app.worker.tasks.workflow_runner._publish_event"):

        mock_ctx.return_value = (run, [wf_step], {wf_step.id: run_step})

        await _execute_workflow(str(run.id))

        final_calls = [c for c in mock_update_run.call_args_list if "failed" in c.args]
        assert len(final_calls) >= 1


@pytest.mark.asyncio
async def test_orchestrator_step_failure_with_fallback_jumps():
    """A failed step with on_failure_step_id causes the orchestrator to execute the fallback step."""
    from app.worker.tasks.workflow_runner import _execute_workflow

    fallback_step = _make_wf_step(order=1, on_failure_step_id=None)
    wf_step = _make_wf_step(order=0, on_failure_step_id=fallback_step.id)

    run = _make_run()
    run_step_0 = _make_run_step(step_id=wf_step.id)
    run_step_1 = _make_run_step(step_id=fallback_step.id)

    call_count = {"n": 0}

    def poll_side_effect(*args, **kwargs):
        call_count["n"] += 1
        return "failed" if call_count["n"] == 1 else "success"

    with patch("app.worker.tasks.workflow_runner._load_run_context") as mock_ctx, \
         patch("app.worker.tasks.workflow_runner._create_job_for_step", return_value=_make_job()), \
         patch("app.worker.tasks.workflow_runner._poll_until_done", side_effect=poll_side_effect), \
         patch("app.worker.tasks.workflow_runner._update_run_step"), \
         patch("app.worker.tasks.workflow_runner._update_run") as mock_update_run, \
         patch("app.worker.tasks.workflow_runner._publish_event"):

        mock_ctx.return_value = (
            run,
            [wf_step, fallback_step],
            {wf_step.id: run_step_0, fallback_step.id: run_step_1},
        )

        await _execute_workflow(str(run.id))

        assert call_count["n"] == 2  # both steps were executed
        final_calls = [c for c in mock_update_run.call_args_list if "success" in c.args]
        assert len(final_calls) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && .venv/bin/pytest tests/test_workflow_runner.py -v
```

Expected: `ImportError` — `workflow_runner` not created yet.

- [ ] **Step 3: Create workflow_runner.py**

Create `backend/app/worker/tasks/workflow_runner.py`:
```python
"""
Celery task: orchestrate a multi-step workflow run.

One `run_workflow` task drives the entire WorkflowRun sequentially:
  1. Mark the run as "running"
  2. For each step (ordered by `order` ASC):
     a. Create a Job + JobNodes and dispatch per-node run_job tasks
     b. Update the pre-created WorkflowRunStep to "running"
     c. Publish step_started event to Redis
     d. Poll DB every 5s until Job reaches a terminal state
     e. On cancel: cancel current job, mark run cancelled, exit
     f. On success: update run_step to success, continue to next step
     g. On failure: update run_step to failed
        - if on_failure_step_id set: jump to that step
        - else: mark run failed, exit
  3. Mark remaining pending run_steps as "skipped" on failure/cancel exit
  4. Publish workflow_done event to Redis
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.session import async_session_factory
from app.models.models import Job, JobNode, Node, WorkflowRun, WorkflowRunStep, WorkflowStep
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

POLL_INTERVAL = 5  # seconds between DB polls
WF_CHANNEL_TPL = "workflow:{run_id}:events"


# ---------------------------------------------------------------------------
# Internal helpers (pure async, testable without Celery)
# ---------------------------------------------------------------------------

async def _load_run_context(
    run_id: str,
) -> tuple[WorkflowRun, list[WorkflowStep], dict[uuid.UUID, WorkflowRunStep]]:
    async with async_session_factory() as session:
        run_res = await session.execute(
            select(WorkflowRun)
            .where(WorkflowRun.id == uuid.UUID(run_id))
            .options(selectinload(WorkflowRun.workflow_run_steps))
        )
        run = run_res.scalar_one_or_none()
        if run is None:
            raise ValueError(f"WorkflowRun {run_id} not found")

        steps_res = await session.execute(
            select(WorkflowStep)
            .where(WorkflowStep.workflow_id == run.workflow_id)
            .order_by(WorkflowStep.order)
        )
        steps = list(steps_res.scalars().all())

        step_map: dict[uuid.UUID, WorkflowRunStep] = {
            rs.workflow_step_id: rs for rs in run.workflow_run_steps
        }
        return run, steps, step_map


async def _update_run(
    run: WorkflowRun,
    new_status: str,
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
) -> None:
    async with async_session_factory() as session:
        res = await session.execute(
            select(WorkflowRun).where(WorkflowRun.id == run.id)
        )
        db_run = res.scalar_one()
        db_run.status = new_status
        if started_at:
            db_run.started_at = started_at
        if finished_at:
            db_run.finished_at = finished_at
        await session.commit()
    run.status = new_status


async def _update_run_step(
    run_step: WorkflowRunStep,
    new_status: str,
    job_id: Optional[uuid.UUID] = None,
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
) -> None:
    async with async_session_factory() as session:
        res = await session.execute(
            select(WorkflowRunStep).where(WorkflowRunStep.id == run_step.id)
        )
        db_rs = res.scalar_one()
        db_rs.status = new_status
        if job_id:
            db_rs.job_id = job_id
        if started_at:
            db_rs.started_at = started_at
        if finished_at:
            db_rs.finished_at = finished_at
        await session.commit()


async def _create_job_for_step(
    run: WorkflowRun,
    step: WorkflowStep,
) -> Job:
    async with async_session_factory() as session:
        job = Job(
            playbook_id=step.playbook_id,
            created_by=run.created_by,
            status="pending",
        )
        session.add(job)
        await session.flush()
        for node_id in run.node_ids:
            session.add(JobNode(job_id=job.id, node_id=node_id, status="pending"))
        await session.commit()
        await session.refresh(job)

    from app.worker.tasks.job_runner import run_job
    for node_id in run.node_ids:
        run_job.delay(
            job_id=str(job.id),
            playbook_id=str(step.playbook_id),
            node_id=str(node_id),
            extra_vars=run.extra_vars or {},
        )

    return job


async def _poll_until_done(
    run: WorkflowRun,
    job: Job,
    redis_client: aioredis.Redis,
    run_id_str: str,
) -> str:
    """Poll DB every POLL_INTERVAL seconds until job reaches a terminal state.

    Also checks WorkflowRun.status each cycle — if it becomes 'cancelled',
    cancels the current job and returns 'cancelled'.
    Returns the terminal job status: 'success', 'failed', or 'cancelled'.
    """
    while True:
        await asyncio.sleep(POLL_INTERVAL)

        async with async_session_factory() as session:
            run_res = await session.execute(
                select(WorkflowRun).where(WorkflowRun.id == run.id)
            )
            db_run = run_res.scalar_one_or_none()
            if db_run and db_run.status == "cancelled":
                # Cancel the current job
                job_res = await session.execute(select(Job).where(Job.id == job.id))
                db_job = job_res.scalar_one_or_none()
                if db_job and db_job.status in ("pending", "running"):
                    db_job.status = "cancelled"
                    await session.commit()
                return "cancelled"

            job_res = await session.execute(select(Job).where(Job.id == job.id))
            db_job = job_res.scalar_one_or_none()
            if db_job and db_job.status in ("success", "failed", "cancelled"):
                return db_job.status


async def _publish_event(redis_client: aioredis.Redis, run_id: str, event: dict) -> None:
    channel = WF_CHANNEL_TPL.format(run_id=run_id)
    try:
        await redis_client.publish(channel, json.dumps(event))
    except Exception as exc:
        logger.warning("workflow event publish failed run=%s: %s", run_id, exc)


async def _mark_remaining_skipped(
    step_map: dict[uuid.UUID, WorkflowRunStep],
    executed_step_ids: set[uuid.UUID],
) -> None:
    pending_ids = [
        rs.id for step_id, rs in step_map.items()
        if step_id not in executed_step_ids
    ]
    if not pending_ids:
        return
    async with async_session_factory() as session:
        for rs_id in pending_ids:
            res = await session.execute(
                select(WorkflowRunStep).where(WorkflowRunStep.id == rs_id)
            )
            db_rs = res.scalar_one_or_none()
            if db_rs and db_rs.status == "pending":
                db_rs.status = "skipped"
        await session.commit()


async def _execute_workflow(run_id: str) -> None:
    run, steps, step_map = await _load_run_context(run_id)

    redis_client = aioredis.from_url(settings.REDIS_URL)
    now = datetime.now(timezone.utc)
    await _update_run(run, "running", started_at=now)

    step_index: dict[uuid.UUID, WorkflowStep] = {s.id: s for s in steps}
    executed: set[uuid.UUID] = set()

    current_step: Optional[WorkflowStep] = steps[0] if steps else None

    try:
        while current_step is not None:
            executed.add(current_step.id)
            run_step = step_map.get(current_step.id)

            job = await _create_job_for_step(run, current_step)

            step_now = datetime.now(timezone.utc)
            if run_step:
                await _update_run_step(run_step, "running", job_id=job.id, started_at=step_now)

            await _publish_event(redis_client, run_id, {
                "type": "step_started",
                "step_id": str(current_step.id),
                "job_id": str(job.id),
                "order": current_step.order,
            })

            terminal_status = await _poll_until_done(run, job, redis_client, run_id)
            step_done = datetime.now(timezone.utc)

            if terminal_status == "cancelled":
                if run_step:
                    await _update_run_step(run_step, "failed", finished_at=step_done)
                await _publish_event(redis_client, run_id, {
                    "type": "step_finished", "step_id": str(current_step.id), "status": "failed",
                })
                await _update_run(run, "cancelled", finished_at=step_done)
                await _publish_event(redis_client, run_id, {
                    "type": "workflow_done", "status": "cancelled",
                })
                current_step = None

            elif terminal_status == "success":
                if run_step:
                    await _update_run_step(run_step, "success", finished_at=step_done)
                await _publish_event(redis_client, run_id, {
                    "type": "step_finished", "step_id": str(current_step.id), "status": "success",
                })
                # Advance to next step by order
                next_steps = [s for s in steps if s.order > current_step.order]
                if next_steps:
                    current_step = min(next_steps, key=lambda s: s.order)
                else:
                    await _update_run(run, "success", finished_at=step_done)
                    await _publish_event(redis_client, run_id, {
                        "type": "workflow_done", "status": "success",
                    })
                    current_step = None

            else:  # failed
                if run_step:
                    await _update_run_step(run_step, "failed", finished_at=step_done)
                await _publish_event(redis_client, run_id, {
                    "type": "step_finished", "step_id": str(current_step.id), "status": "failed",
                })
                if current_step.on_failure_step_id:
                    current_step = step_index.get(current_step.on_failure_step_id)
                else:
                    await _update_run(run, "failed", finished_at=step_done)
                    await _publish_event(redis_client, run_id, {
                        "type": "workflow_done", "status": "failed",
                    })
                    current_step = None

    finally:
        await _mark_remaining_skipped(step_map, executed)
        try:
            await redis_client.aclose()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

@celery_app.task(name="app.worker.tasks.workflow_runner.run_workflow", bind=False)
def run_workflow(workflow_run_id: str) -> dict:
    """Orchestrate a WorkflowRun by sequentially dispatching per-step Jobs."""
    logger.info("run_workflow: run=%s", workflow_run_id)
    try:
        asyncio.run(_execute_workflow(workflow_run_id))
        return {"status": "done", "run_id": workflow_run_id}
    except Exception as exc:
        logger.exception("run_workflow: unhandled error run=%s: %s", workflow_run_id, exc)
        return {"status": "error", "error": str(exc)}
```

- [ ] **Step 4: Add stale sweep beat task to celery_app.py**

Edit `backend/app/worker/celery_app.py`:
```python
from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "nodelinker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.worker.tasks.health_probe",
        "app.worker.tasks.job_runner",
        "app.worker.tasks.workflow_runner",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "probe-all-nodes": {
            "task": "app.worker.tasks.health_probe.probe_all_nodes",
            "schedule": 30.0,
        },
        "sweep-stale-workflow-runs": {
            "task": "app.worker.tasks.workflow_runner.sweep_stale_runs",
            "schedule": 300.0,  # every 5 minutes
        },
    },
)
```

Then add the sweep task to the bottom of `workflow_runner.py`:
```python
STALE_RUN_THRESHOLD_MINUTES = 60


@celery_app.task(name="app.worker.tasks.workflow_runner.sweep_stale_runs", bind=False)
def sweep_stale_runs() -> dict:
    """Mark workflow runs stuck in 'running' for over STALE_RUN_THRESHOLD_MINUTES as failed."""
    async def _sweep() -> int:
        from datetime import timedelta
        from sqlalchemy import and_
        threshold = datetime.now(timezone.utc) - timedelta(minutes=STALE_RUN_THRESHOLD_MINUTES)
        async with async_session_factory() as session:
            res = await session.execute(
                select(WorkflowRun).where(
                    and_(
                        WorkflowRun.status == "running",
                        WorkflowRun.started_at < threshold,
                    )
                )
            )
            stale = res.scalars().all()
            for run in stale:
                run.status = "failed"
                run.finished_at = datetime.now(timezone.utc)
                logger.warning("sweep: marking stale workflow run %s as failed", run.id)
            await session.commit()
            return len(stale)

    count = asyncio.run(_sweep())
    return {"swept": count}
```

- [ ] **Step 5: Run orchestrator tests**

```bash
cd backend && .venv/bin/pytest tests/test_workflow_runner.py -v
```

Expected: all three tests `PASSED`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/worker/tasks/workflow_runner.py backend/app/worker/celery_app.py backend/tests/test_workflow_runner.py
git commit -m "feat: add run_workflow Celery orchestrator task and stale sweep"
```

---

### Task 7: WebSocket handler and main.py registration

**Files:**
- Create: `backend/app/ws/workflow_runs.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Write the failing import test**

Add to `backend/tests/test_workflows_api.py`:
```python
def test_workflow_ws_handler_importable():
    from app.ws.workflow_runs import workflow_run_ws
    assert callable(workflow_run_ws)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && .venv/bin/pytest tests/test_workflows_api.py::test_workflow_ws_handler_importable -v
```

Expected: `ImportError`.

- [ ] **Step 3: Create ws/workflow_runs.py**

Create `backend/app/ws/workflow_runs.py`:
```python
"""
WebSocket endpoint: /ws/workflow-runs/{run_id}

Streams workflow step-transition events to the client via Redis pub/sub.

Protocol — Server → Client (JSON):
  {"type": "step_started",  "step_id": "...", "job_id": "...", "order": N}
  {"type": "step_finished", "step_id": "...", "status": "success|failed"}
  {"type": "workflow_done", "status": "success|failed|cancelled"}
  {"type": "error",         "detail": "..."}

For already-completed runs, the server sends the current run status as a
workflow_done message and closes immediately.
"""
import asyncio
import json
import logging
import uuid

import redis.asyncio as aioredis
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.config import settings
from app.db.session import async_session_factory
from app.models.models import WorkflowRun

logger = logging.getLogger(__name__)

WF_CHANNEL_TPL = "workflow:{run_id}:events"
PUBSUB_POLL_TIMEOUT = 5.0
TERMINAL_STATUSES = {"success", "failed", "cancelled"}


async def workflow_run_ws(websocket: WebSocket, run_id: uuid.UUID) -> None:
    await websocket.accept()

    channel = WF_CHANNEL_TPL.format(run_id=str(run_id))

    async with async_session_factory() as session:
        res = await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
        run = res.scalar_one_or_none()
        if run is None:
            await websocket.send_json({"type": "error", "detail": "WorkflowRun not found"})
            await websocket.close(code=4004)
            return
        already_done = run.status in TERMINAL_STATUSES
        current_status = run.status

    if already_done:
        try:
            await websocket.send_json({"type": "workflow_done", "status": current_status})
        except WebSocketDisconnect:
            pass
        await websocket.close()
        return

    redis_client = aioredis.from_url(settings.REDIS_URL)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)

    try:
        while True:
            try:
                message = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True, timeout=PUBSUB_POLL_TIMEOUT),
                    timeout=PUBSUB_POLL_TIMEOUT + 1,
                )
            except asyncio.TimeoutError:
                async with async_session_factory() as session:
                    res = await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
                    run = res.scalar_one_or_none()
                    if run and run.status in TERMINAL_STATUSES:
                        await websocket.send_json({"type": "workflow_done", "status": run.status})
                        break
                continue

            if message is None:
                continue

            try:
                data = json.loads(message["data"])
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

            try:
                await websocket.send_json(data)
            except WebSocketDisconnect:
                return

            if data.get("type") == "workflow_done":
                break

    except WebSocketDisconnect:
        logger.debug("ws/workflow-runs/%s: client disconnected", run_id)
    except Exception as exc:
        logger.exception("ws/workflow-runs/%s: error: %s", run_id, exc)
        try:
            await websocket.send_json({"type": "error", "detail": str(exc)})
        except Exception:
            pass
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
        except Exception:
            pass
        try:
            await redis_client.aclose()
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass
```

- [ ] **Step 4: Register WebSocket route in main.py**

Edit `backend/app/main.py` — add the import and route:
```python
import uuid

from fastapi import WebSocket
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.v1.router import router as v1_router
from app.api.v1.nodes import node_status_ws
from app.ws.jobs import job_log_ws
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


@app.websocket("/ws/jobs/{job_id}")
async def job_log_websocket(websocket: WebSocket, job_id: uuid.UUID) -> None:
    await job_log_ws(websocket, job_id)


@app.websocket("/ws/workflow-runs/{run_id}")
async def workflow_run_websocket(websocket: WebSocket, run_id: uuid.UUID) -> None:
    await workflow_run_ws(websocket, run_id)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
```

- [ ] **Step 5: Run all tests**

```bash
cd backend && .venv/bin/pytest tests/ -v
```

Expected: all tests `PASSED`, no import errors.

- [ ] **Step 6: Commit**

```bash
git add backend/app/ws/workflow_runs.py backend/app/main.py backend/tests/test_workflows_api.py
git commit -m "feat: add workflow WebSocket handler and register route"
```

---

### Task 8: Final integration smoke test

**Files:**
- No new files — verify the whole feature composes correctly

- [ ] **Step 1: Verify the app can be imported cleanly**

```bash
cd backend && .venv/bin/python -c "
from app.main import app
from app.worker.tasks.workflow_runner import run_workflow, sweep_stale_runs
from app.ws.workflow_runs import workflow_run_ws
print('All imports OK')
print('Routes:', [r.path for r in app.routes])
"
```

Expected output includes:
```
All imports OK
Routes: [..., '/ws/workflow-runs/{run_id}', ...]
```

- [ ] **Step 2: Verify all models are included in alembic metadata**

```bash
cd backend && .venv/bin/python -c "
from app.db.session import Base
from app.models.models import Workflow, WorkflowStep, WorkflowRun, WorkflowRunStep
tables = list(Base.metadata.tables.keys())
for t in ['workflows', 'workflow_steps', 'workflow_runs', 'workflow_run_steps']:
    assert t in tables, f'Missing table: {t}'
print('All workflow tables registered in metadata:', [t for t in tables if 'workflow' in t])
"
```

Expected: `All workflow tables registered in metadata: ['workflows', 'workflow_steps', 'workflow_runs', 'workflow_run_steps']`

- [ ] **Step 3: Run full test suite**

```bash
cd backend && .venv/bin/pytest tests/ -v --tb=short
```

Expected: all tests pass.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: workflow feature complete — all tests passing"
```

---

## Self-Review Checklist

**Spec coverage:**

| Requirement | Task |
|-------------|------|
| Sequential execution | Task 6 (`_execute_workflow` loop) |
| Nodes at run time, shared across steps | Task 6 (`_create_job_for_step` uses `run.node_ids`) |
| All nodes must succeed | Inherited from existing `run_job` — Job status = success only when all JobNodes succeed |
| Failure fallback via on_failure_step_id | Task 6 (`on_failure_step_id` branch in `_execute_workflow`) |
| Per-step history with job_id | Task 4 (schemas) + Task 6 (`_update_run_step` sets `job_id`) |
| Stale run recovery | Task 6 (`sweep_stale_runs` beat task) |
| Workflow CRUD API | Task 5 |
| Workflow run API | Task 5 |
| Cancel API | Task 5 (`cancel_workflow_run`) |
| Real-time events channel | Task 6 (`_publish_event`) |
| WebSocket endpoint | Task 7 |
| DB migration | Task 3 |
| `on_failure_step_order` resolution | Task 5 (`_resolve_on_failure_steps`) |
| WorkflowRunStep pre-creation | Task 5 (`create_workflow_run`) |
| Remaining steps marked skipped | Task 6 (`_mark_remaining_skipped`) |
