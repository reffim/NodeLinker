"""
Celery task: run an Ansible playbook on a single node via ansible-runner.

One task is dispatched per (job, node) pair. Each task:
  1. Acquires Redis exclusive lock if playbook has exclusive_group (retries w/ countdown if held)
  2. Marks job + job_node as `running`
  3. Writes playbook YAML + inventory to a temp project directory
  4. Starts ansible_runner.run_async() in a thread
  5. Tails the stdout artifact file with aiofiles, publishing each line to
     Redis pub/sub in real time (asyncio file-tail → Redis pub/sub → browser)
  6. Persists all collected lines to job_logs table
  7. Updates job_node status + exit_code
  8. If this is the last node to finish, updates the overall job status
  9. Releases the exclusive lock (if held)
 10. Publishes a `done` event to the Redis channel so WebSocket clients close
"""
import asyncio
import json
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
from app.db.session import async_session_factory
from app.models.models import Job, JobLog, JobNode, Node, Playbook
from app.services.lock_service import acquire_lock, release_lock
from app.worker.celery_app import celery_app

# Retry interval when the exclusive lock is held by another job (seconds)
LOCK_RETRY_COUNTDOWN: int = 30
# Maximum number of retry attempts before giving up (30 s * 120 = 1 hour)
LOCK_MAX_RETRIES: int = 120

logger = logging.getLogger(__name__)

# Redis pub/sub channel template: job:{job_id}:logs
# Messages are JSON: {"type": "log", "line_number": N, "content": "...", "node_id": "..."}
#                 or {"type": "done", "status": "success|failed|cancelled", "node_id": "..."}
CHANNEL_TPL = "job:{job_id}:logs"


# ---------------------------------------------------------------------------
# Sync helpers
# ---------------------------------------------------------------------------

def _build_inventory(node: Any, private_data_dir: str) -> None:
    inv_dir = Path(private_data_dir) / "inventory"
    inv_dir.mkdir(parents=True, exist_ok=True)
    host_vars: dict[str, str] = {
        "ansible_host": node.host,
        "ansible_port": str(node.port),
        "ansible_user": node.ssh_user,
    }
    if node.ssh_key_path:
        host_vars["ansible_ssh_private_key_file"] = node.ssh_key_path
    vars_str = " ".join(f"{k}={v}" for k, v in host_vars.items())
    (inv_dir / "hosts").write_text(f"[targets]\ntarget_node {vars_str}\n")


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
    """Start ansible-runner asynchronously (returns thread + runner object)."""
    runner_kwargs: dict[str, Any] = {
        "private_data_dir": private_data_dir,
        "playbook": playbook_name,
        "quiet": False,
        "rotate_artifacts": 5,
    }
    if extra_vars:
        runner_kwargs["extravars"] = extra_vars
    return ansible_runner.run_async(**runner_kwargs)


# ---------------------------------------------------------------------------
# Async log-tail (aiofiles-based)
# ---------------------------------------------------------------------------

async def _tail_and_stream(
    private_data_dir: str,
    runner_thread: Any,
    channel: str,
    job_id: str,
    node_id: str,
    redis_client: aioredis.Redis,
) -> list[str]:
    """
    Async file-tail of the ansible-runner stdout artifact using aiofiles.
    Publishes each line to Redis pub/sub in real time.
    Returns the list of all collected lines.
    """
    # Wait for ansible-runner to create the artifact directory (up to 5 s)
    stdout_path: Path | None = None
    for _ in range(50):
        artifacts = Path(private_data_dir) / "artifacts"
        if artifacts.exists():
            subdirs = [d for d in artifacts.iterdir() if d.is_dir()]
            if subdirs:
                candidate = subdirs[0] / "stdout"
                stdout_path = candidate
                break
        await asyncio.sleep(0.1)

    all_lines: list[str] = []
    line_number = 0

    if stdout_path:
        async with aiofiles.open(stdout_path, "r", errors="replace") as f:
            while True:
                raw = await f.readline()
                if raw:
                    line = raw.rstrip("\n")
                    line_number += 1
                    all_lines.append(line)
                    try:
                        await redis_client.publish(channel, json.dumps({
                            "type": "log",
                            "line_number": line_number,
                            "content": line,
                            "node_id": node_id,
                        }))
                    except Exception:
                        pass  # don't let Redis errors abort the run
                elif not runner_thread.is_alive():
                    # Thread finished — drain any remaining bytes
                    async for raw in f:
                        line = raw.rstrip("\n")
                        line_number += 1
                        all_lines.append(line)
                        try:
                            await redis_client.publish(channel, json.dumps({
                                "type": "log",
                                "line_number": line_number,
                                "content": line,
                                "node_id": node_id,
                            }))
                        except Exception:
                            pass
                    break
                else:
                    await asyncio.sleep(0.1)
    else:
        # Artifact dir never appeared — wait for thread and read runner.stdout
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, runner_thread.join)

    return all_lines


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

        node_res = await session.execute(select(Node).where(Node.id == uuid.UUID(node_id)))
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


async def _insert_logs(job_id: str, node_id: str, lines: list[str]) -> None:
    async with async_session_factory() as session:
        for i, line in enumerate(lines, 1):
            session.add(JobLog(
                job_id=uuid.UUID(job_id),
                node_id=uuid.UUID(node_id),
                line_number=i,
                content=line,
            ))
        await session.commit()


async def _finish_node(
    job_id: str,
    node_id: str,
    node_status: str,
    exit_code: int | None,
) -> None:
    """
    Update job_node status and, if all nodes have finished, update the overall job status.
    """
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

        # Check if all nodes in this job are done
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
    """Execute an Ansible playbook on a single node with aiofiles-based real-time log streaming.

    If the playbook has an exclusive_group, a Redis distributed lock is acquired before
    execution begins. When the lock is held by another job, this task is retried with a
    countdown of LOCK_RETRY_COUNTDOWN seconds (serialising same-group jobs on the same node).
    """
    logger.info("run_job: job=%s node=%s", job_id, node_id)

    channel = CHANNEL_TPL.format(job_id=job_id)

    async def _execute() -> dict:
        redis_client = aioredis.from_url(settings.REDIS_URL)
        lock_acquired = False
        lock_node_id: str | None = None
        lock_group: str | None = None
        try:
            ctx = await _load_context(job_id, node_id)
            if ctx is None:
                return {"status": "failed", "error": "context not found"}
            job, _jn, playbook, node = ctx

            if job.status == "cancelled":
                return {"status": "cancelled"}

            # ------------------------------------------------------------------
            # Exclusive lock: acquire before running, retry if held
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
                        node_id,
                        playbook.exclusive_group,
                        job_id,
                        LOCK_RETRY_COUNTDOWN,
                    )
                    # Re-raise as a Celery retry — this re-queues the task
                    raise self.retry(countdown=LOCK_RETRY_COUNTDOWN)

                logger.info(
                    "run_job: lock acquired node=%s group=%s job=%s",
                    node_id, playbook.exclusive_group, job_id,
                )

            if not playbook.content:
                await _finish_node(job_id, node_id, "failed", None)
                await redis_client.publish(channel, json.dumps({
                    "type": "done", "status": "failed", "node_id": node_id,
                }))
                return {"status": "failed", "error": "playbook has no content"}

            await _mark_running(job_id, node_id)

            stdout_lines: list[str] = []
            rc: int | None = None
            success = False

            with tempfile.TemporaryDirectory(prefix="minerva_job_") as tmpdir:
                try:
                    _build_inventory(node, tmpdir)
                    playbook_name = _write_playbook(playbook.content, tmpdir)

                    # Start ansible-runner in its own thread
                    runner_thread, runner = _start_runner(tmpdir, playbook_name, extra_vars)

                    # Tail the artifact file with aiofiles + publish to Redis
                    stdout_lines = await _tail_and_stream(
                        tmpdir, runner_thread, channel, job_id, node_id, redis_client
                    )

                    rc = runner.rc
                    success = runner.status == "successful"

                except Exception as exc:
                    logger.exception("run_job: error job=%s node=%s: %s", job_id, node_id, exc)
                    stdout_lines = [f"Internal error: {exc}"]
                    rc = -1
                    success = False

            # Check cancellation during run
            async with async_session_factory() as session:
                check = await session.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
                current = check.scalar_one_or_none()
                if current and current.status == "cancelled":
                    if stdout_lines:
                        await _insert_logs(job_id, node_id, stdout_lines)
                    await redis_client.publish(channel, json.dumps({
                        "type": "done", "status": "cancelled", "node_id": node_id,
                    }))
                    return {"status": "cancelled"}

            if stdout_lines:
                await _insert_logs(job_id, node_id, stdout_lines)

            node_status = "success" if success else "failed"
            await _finish_node(job_id, node_id, node_status, rc)

            await redis_client.publish(channel, json.dumps({
                "type": "done", "status": node_status, "node_id": node_id,
            }))

            logger.info("run_job: job=%s node=%s status=%s rc=%s", job_id, node_id, node_status, rc)
            return {"status": node_status, "rc": rc, "lines": len(stdout_lines)}

        finally:
            # Release the exclusive lock before closing Redis (if we held it)
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
