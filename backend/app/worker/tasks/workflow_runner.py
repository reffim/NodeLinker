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
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as aioredis
from sqlalchemy import and_, select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.session import async_session_factory
from app.models.models import Job, JobNode, WorkflowRun, WorkflowRunStep, WorkflowStep
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

POLL_INTERVAL = 5  # seconds between DB polls
WF_CHANNEL_TPL = "workflow:{run_id}:events"
STALE_RUN_THRESHOLD_MINUTES = 60


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
        # Don't overwrite a terminal status with a non-terminal one
        if new_status == "running" and db_run.status != "pending":
            run.status = db_run.status  # sync in-memory to current DB state
            return
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
            if db_run is None:
                logger.error("poll: WorkflowRun %s not found — aborting poll", run.id)
                return "failed"
            if db_run.status == "cancelled":
                job_res = await session.execute(select(Job).where(Job.id == job.id))
                db_job = job_res.scalar_one_or_none()
                if db_job and db_job.status in ("pending", "running"):
                    db_job.status = "cancelled"
                    await session.commit()
                return "cancelled"

            job_res = await session.execute(select(Job).where(Job.id == job.id))
            db_job = job_res.scalar_one_or_none()
            if db_job is None:
                logger.error("poll: Job %s not found — aborting poll", job.id)
                return "failed"
            if db_job.status in ("success", "failed", "cancelled"):
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

    # Handle the case where _update_run detected the run was cancelled before we started
    if run.status == "cancelled":
        try:
            await _publish_event(redis_client, run_id, {"type": "workflow_done", "status": "cancelled"})
        finally:
            try:
                await redis_client.aclose()
            except Exception:
                pass
        return

    step_index: dict[uuid.UUID, WorkflowStep] = {s.id: s for s in steps}
    executed: set[uuid.UUID] = set()

    current_step: Optional[WorkflowStep] = steps[0] if steps else None

    try:
        if current_step is None:
            await _update_run(run, "success", finished_at=datetime.now(timezone.utc))
            await _publish_event(redis_client, run_id, {"type": "workflow_done", "status": "success"})
            return

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

            terminal_status = await _poll_until_done(run, job)
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
                    fallback = step_index.get(current_step.on_failure_step_id)
                    if fallback is not None:
                        current_step = fallback
                    else:
                        logger.error(
                            "run=%s step=%s on_failure_step_id=%s not found in workflow steps — failing run",
                            run_id, current_step.id, current_step.on_failure_step_id,
                        )
                        await _update_run(run, "failed", finished_at=step_done)
                        await _publish_event(redis_client, run_id, {"type": "workflow_done", "status": "failed"})
                        current_step = None
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
# Celery tasks
# ---------------------------------------------------------------------------

@celery_app.task(name="app.worker.tasks.workflow_runner.run_workflow", bind=False)
def run_workflow(workflow_run_id: str) -> dict:
    """Orchestrate a WorkflowRun by sequentially dispatching per-step Jobs."""
    logger.info("run_workflow: run=%s", workflow_run_id)

    async def _run() -> dict:
        try:
            await _execute_workflow(workflow_run_id)
            return {"status": "done", "run_id": workflow_run_id}
        except Exception as exc:
            logger.exception("run_workflow: unhandled error run=%s: %s", workflow_run_id, exc)
            # Best-effort: mark the run as failed so it doesn't stay stuck in "running"
            try:
                async with async_session_factory() as session:
                    res = await session.execute(
                        select(WorkflowRun).where(WorkflowRun.id == uuid.UUID(workflow_run_id))
                    )
                    db_run = res.scalar_one_or_none()
                    if db_run and db_run.status == "running":
                        db_run.status = "failed"
                        db_run.finished_at = datetime.now(timezone.utc)
                        await session.commit()
            except Exception:
                logger.exception("run_workflow: failed to mark run as failed run=%s", workflow_run_id)
            return {"status": "error", "error": str(exc)}

    return asyncio.run(_run())


@celery_app.task(name="app.worker.tasks.workflow_runner.sweep_stale_runs", bind=False)
def sweep_stale_runs() -> dict:
    """Mark workflow runs stuck in 'running' for over STALE_RUN_THRESHOLD_MINUTES as failed."""
    async def _sweep() -> int:
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
