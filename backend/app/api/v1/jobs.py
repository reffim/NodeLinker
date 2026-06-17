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
from app.schemas.jobs import JobCreate, JobLogChunkResponse, JobResponse

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
