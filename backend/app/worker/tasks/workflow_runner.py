"""
Celery task: orchestrate a multi-step workflow run.

One `run_workflow` task drives the entire WorkflowRun sequentially:
  1. Mark the run as "running"
  2. For each step (ordered by `order` ASC):
     a. For each node: create a Job (1 node) + dispatch run_job
     b. Update the pre-created WorkflowRunStep (per node) to "running"
     c. Publish step_started event per node to Redis
     d. Poll DB in parallel until all per-node Jobs reach a terminal state
     e. On cancel: mark all node steps failed, mark run cancelled, exit
     f. On all success: update node steps to success, continue to next step
     g. On any failure: update node steps, check on_failure_step_id or fail run
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
) -> tuple[WorkflowRun, list[WorkflowStep], dict[uuid.UUID, list[WorkflowRunStep]]]:
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

        step_map: dict[uuid.UUID, list[WorkflowRunStep]] = {}
        for rs in run.workflow_run_steps:
            step_map.setdefault(rs.workflow_step_id, []).append(rs)

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


async def _create_job_for_node(
    run: WorkflowRun,
    step: WorkflowStep,
    node_id: uuid.UUID,
) -> Job:
    async with async_session_factory() as session:
        job = Job(
            playbook_id=step.playbook_id,
            created_by=run.created_by,
            status="pending",
        )
        session.add(job)
        await session.flush()
        session.add(JobNode(job_id=job.id, node_id=node_id, status="pending"))
        await session.commit()
        await session.refresh(job)

    from app.worker.tasks.job_runner import run_job
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
    step_map: dict[uuid.UUID, list[WorkflowRunStep]],
    executed_step_ids: set[uuid.UUID],
) -> None:
    pending_ids = [
        rs.id
        for step_id, run_steps in step_map.items()
        if step_id not in executed_step_ids
        for rs in run_steps
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
            run_steps = step_map.get(current_step.id, [])
            step_now = datetime.now(timezone.utc)

            # Create one job per node and publish step_started events
            node_job_pairs: list[tuple[Job, WorkflowRunStep]] = []
            for rs in run_steps:
                if rs.node_id is None:
                    logger.warning(
                        "run=%s step=%s run_step=%s has no node_id — skipping",
                        run_id, current_step.id, rs.id,
                    )
                    continue
                job = await _create_job_for_node(run, current_step, rs.node_id)
                await _update_run_step(rs, "running", job_id=job.id, started_at=step_now)
                await _publish_event(redis_client, run_id, {
                    "type": "step_started",
                    "step_id": str(rs.id),
                    "job_id": str(job.id),
                    "order": current_step.order,
                    "node_id": str(rs.node_id),
                })
                node_job_pairs.append((job, rs))

            # Poll all node jobs in parallel
            poll_results: list[str] = list(await asyncio.gather(
                *[_poll_until_done(run, job) for job, _ in node_job_pairs]
            ))
            step_done = datetime.now(timezone.utc)

            if "cancelled" in poll_results:
                for _, rs in node_job_pairs:
                    await _update_run_step(rs, "failed", finished_at=step_done)
                    await _publish_event(redis_client, run_id, {
                        "type": "step_finished",
                        "step_id": str(rs.id),
                        "status": "failed",
                        "node_id": str(rs.node_id),
                    })
                await _update_run(run, "cancelled", finished_at=step_done)
                await _publish_event(redis_client, run_id, {"type": "workflow_done", "status": "cancelled"})
                current_step = None

            elif all(s == "success" for s in poll_results):
                for _, rs in node_job_pairs:
                    await _update_run_step(rs, "success", finished_at=step_done)
                    await _publish_event(redis_client, run_id, {
                        "type": "step_finished",
                        "step_id": str(rs.id),
                        "status": "success",
                        "node_id": str(rs.node_id),
                    })
                next_steps = [s for s in steps if s.order > current_step.order]
                if next_steps:
                    current_step = min(next_steps, key=lambda s: s.order)
                else:
                    await _update_run(run, "success", finished_at=step_done)
                    await _publish_event(redis_client, run_id, {"type": "workflow_done", "status": "success"})
                    current_step = None

            else:  # some failed
                for (_, rs), status in zip(node_job_pairs, poll_results):
                    node_status = status if status in ("success", "failed") else "failed"
                    await _update_run_step(rs, node_status, finished_at=step_done)
                    await _publish_event(redis_client, run_id, {
                        "type": "step_finished",
                        "step_id": str(rs.id),
                        "status": node_status,
                        "node_id": str(rs.node_id),
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
                    await _publish_event(redis_client, run_id, {"type": "workflow_done", "status": "failed"})
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
    """Orchestrate a WorkflowRun by sequentially dispatching per-node Jobs."""
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
    """Mark workflow runs stuck in 'running' or 'pending' for too long as failed."""
    async def _sweep() -> int:
        threshold = datetime.now(timezone.utc) - timedelta(minutes=STALE_RUN_THRESHOLD_MINUTES)
        async with async_session_factory() as session:
            res = await session.execute(
                select(WorkflowRun).where(
                    and_(
                        WorkflowRun.status.in_(["running", "pending"]),
                        WorkflowRun.created_at < threshold,
                    )
                )
            )
            stale = res.scalars().all()
            now = datetime.now(timezone.utc)
            for run in stale:
                run.status = "failed"
                run.finished_at = now
                logger.warning("sweep: marking stale workflow run %s (was %s) as failed", run.id, run.status)
            await session.commit()
            return len(stale)

    count = asyncio.run(_sweep())
    return {"swept": count}
