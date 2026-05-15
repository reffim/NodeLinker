"""
Job API: create a job (dispatches to Celery per node), get status, get logs.

Routes:
  POST  /api/v1/jobs
  GET   /api/v1/jobs/{job_id}
  GET   /api/v1/jobs/{job_id}/logs
  POST  /api/v1/jobs/{job_id}/cancel
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.models import Job, JobNode, Node, Playbook, User
from app.schemas.jobs import JobCreate, JobNodeResponse, JobResponse

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

    # Validate playbook exists
    pb_result = await db.execute(select(Playbook).where(Playbook.id == payload.playbook_id))
    playbook = pb_result.scalar_one_or_none()
    if playbook is None:
        raise HTTPException(status_code=404, detail="Playbook not found")

    # Validate all nodes exist (deduplicate)
    node_ids = list(dict.fromkeys(payload.node_ids))  # preserve order, dedupe
    node_result = await db.execute(select(Node).where(Node.id.in_(node_ids)))
    nodes = {n.id: n for n in node_result.scalars().all()}
    missing = [nid for nid in node_ids if nid not in nodes]
    if missing:
        raise HTTPException(status_code=404, detail=f"Nodes not found: {missing}")

    # Build exclusive_lock_key from playbook's exclusive_group (if set)
    # Format: node:{node_id}:exclusive:{group} — stored for observability; actual
    # locking is enforced inside the Celery worker via lock_service.
    # For multi-node jobs the key reflects the common group (node part varies per worker).
    exclusive_lock_key: str | None = None
    if playbook.exclusive_group:
        exclusive_lock_key = f"exclusive:{playbook.exclusive_group}"

    # Create job record
    job = Job(
        playbook_id=payload.playbook_id,
        created_by=current_user.id,
        status="pending",
        exclusive_lock_key=exclusive_lock_key,
    )
    db.add(job)
    await db.flush()  # get job.id before adding job_nodes

    for node_id in node_ids:
        db.add(JobNode(job_id=job.id, node_id=node_id, status="pending"))

    await db.commit()

    # Reload with relationships
    result = await db.execute(
        select(Job).where(Job.id == job.id).options(selectinload(Job.job_nodes))
    )
    job = result.scalar_one()

    # Dispatch one Celery task per node
    from app.worker.tasks.job_runner import run_job  # avoid circular import
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


@router.get("/{job_id}/logs", response_model=list[JobNodeResponse])
async def get_job_logs(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[JobNode]:
    """
    Return per-node log file URLs for a completed job.
    Real-time streaming during execution is available via WebSocket /ws/jobs/{job_id}.
    After completion, logs are stored in Object Storage (S3) or Local FS;
    `log_file_url` in each entry points to the archived log file.
    """
    job_result = await db.execute(select(Job).where(Job.id == job_id))
    if job_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Job not found")

    result = await db.execute(
        select(JobNode).where(JobNode.job_id == job_id).order_by(JobNode.node_id)
    )
    return list(result.scalars().all())


@router.get("/{job_id}/nodes/{node_id}/logs/content", response_model=list[str])
async def get_job_node_logs_content(
    job_id: uuid.UUID,
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[str]:
    """Fetch the actual lines of the log file from storage if the job is done."""
    result = await db.execute(
        select(JobNode).where(
            JobNode.job_id == job_id, JobNode.node_id == node_id
        )
    )
    jn = result.scalar_one_or_none()
    if jn is None:
        raise HTTPException(status_code=404, detail="JobNode not found")
    
    if not jn.log_file_url:
        return []

    # Currently we only support local file:// urls
    if jn.log_file_url.startswith("file://"):
        import gzip
        from pathlib import Path
        
        path = Path(jn.log_file_url[7:])
        if not path.exists():
            return ["[Log file not found on server]"]
        
        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                return [line.rstrip('\n') for line in f]
        except Exception as e:
            return [f"[Error reading log file: {e}]"]
            
    return ["[Unsupported log URL format]"]


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
