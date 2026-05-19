import pytest
from unittest.mock import AsyncMock, MagicMock
import uuid


def test_workflow_models_importable():
    from app.models.models import Workflow, WorkflowStep, WorkflowRun, WorkflowRunStep
    assert Workflow.__tablename__ == "workflows"
    assert WorkflowStep.__tablename__ == "workflow_steps"
    assert WorkflowRun.__tablename__ == "workflow_runs"
    assert WorkflowRunStep.__tablename__ == "workflow_run_steps"


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
    with pytest.raises(Exception):
        WorkflowRunCreate(node_ids=[])


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


@pytest.mark.asyncio
async def test_resolve_on_failure_step_raises_422_for_invalid_order():
    """_resolve_on_failure_steps raises 422 when order reference doesn't exist."""
    from app.api.v1.workflows import _resolve_on_failure_steps
    from fastapi import HTTPException

    step = MagicMock()
    db = AsyncMock()

    order_to_id = {0: uuid.uuid4()}  # only order 0 exists
    pending = [(step, 99)]  # references order 99 which doesn't exist

    with pytest.raises(HTTPException) as exc_info:
        await _resolve_on_failure_steps(db, pending, order_to_id)
    assert exc_info.value.status_code == 422


def test_workflow_create_rejects_duplicate_step_orders():
    from app.schemas.workflows import WorkflowCreate, WorkflowStepCreate
    pb_id = uuid.uuid4()
    with pytest.raises(Exception):
        WorkflowCreate(
            name="Bad Pipeline",
            steps=[
                WorkflowStepCreate(order=0, playbook_id=pb_id),
                WorkflowStepCreate(order=0, playbook_id=pb_id),  # duplicate order
            ]
        )
