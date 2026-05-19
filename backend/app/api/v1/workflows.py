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
    if pending:
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

    # Commit the workflow and steps first, then resolve FK references in a second pass
    await db.commit()
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
    result = await db.execute(
        select(WorkflowRun).where(WorkflowRun.id == run_id).options(WORKFLOW_RUN_STEPS_OPTION)
    )
    return result.scalar_one()
