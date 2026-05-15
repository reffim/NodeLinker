"""
Celery task: run an Ansible playbook on a single node via ansible-runner.

One task is dispatched per (job, node) pair. Each task:
  1. Acquires Redis exclusive lock with TTL if playbook has exclusive_group
  2. Starts a lock heartbeat coroutine to renew the TTL periodically
  3. Marks job + job_node as `running`
  4. Fetches SSH credential from HashiCorp Vault (via node.credential)
  5. Writes playbook YAML + inventory (with Vault-fetched credentials) to a temp dir
  6. Starts ansible_runner.run_async() in a thread
  7. Tails the stdout artifact with aiofiles, publishing each line to Redis pub/sub
  8. On completion, compresses and saves logs to Object Storage (S3 / Local FS)
  9. Updates job_node.status + exit_code + log_file_url
 10. If this is the last node to finish, updates the overall job status
 11. Cancels the heartbeat coroutine and releases the exclusive lock
 12. Publishes a `done` event to the Redis channel so WebSocket clients close
"""
import asyncio
import gzip
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
from app.core.vault import get_credential
from app.db.session import async_session_factory
from app.models.models import Job, JobNode, Node, Playbook
from app.services.lock_service import (
    LOCK_TTL_SECONDS,
    acquire_lock,
    extend_lock,
    release_lock,
)
from app.worker.celery_app import celery_app

# Retry interval when the exclusive lock is held by another job (seconds)
LOCK_RETRY_COUNTDOWN: int = 30
# Maximum number of retry attempts before giving up (30 s * 120 = 1 hour)
LOCK_MAX_RETRIES: int = 120
# Heartbeat interval: renew lock TTL at half the TTL duration
HEARTBEAT_INTERVAL: int = LOCK_TTL_SECONDS // 2

logger = logging.getLogger(__name__)

# Redis pub/sub channel template: job:{job_id}:logs
# Messages are JSON: {"type": "log", "line_number": N, "content": "...", "node_id": "..."}
#                 or {"type": "done", "status": "success|failed|cancelled", "node_id": "..."}
CHANNEL_TPL = "job:{job_id}:logs"


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
    """
    Periodically extend the Redis lock TTL while a job is running.
    Stops when `stop_event` is set (job finished or failed).
    Prevents deadlocks from long-running jobs outliving the initial TTL.
    """
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=HEARTBEAT_INTERVAL)
        except asyncio.TimeoutError:
            pass  # expected — time to renew

        if stop_event.is_set():
            break

        ok = await extend_lock(redis_client, node_id, playbook_group, token)
        if not ok:
            logger.warning(
                "heartbeat: lock extend failed — lock may have expired node=%s group=%s job=%s",
                node_id, playbook_group, token,
            )


# ---------------------------------------------------------------------------
# Log storage helpers
# ---------------------------------------------------------------------------

def _log_file_path(job_id: str, node_id: str) -> Path:
    """Return the local FS path where the compressed log will be stored."""
    base = Path(settings.LOG_STORAGE_BASE_PATH)
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{job_id}_{node_id}.log.gz"


def _save_log_local(lines: list[str], job_id: str, node_id: str) -> str:
    """Compress and write log lines to local FS; return the file URL."""
    path = _log_file_path(job_id, node_id)
    content = "\n".join(lines).encode("utf-8")
    with gzip.open(path, "wb") as f:
        f.write(content)
    logger.debug("log saved: path=%s lines=%d", path, len(lines))
    return f"file://{path}"


async def _save_logs_to_storage(lines: list[str], job_id: str, node_id: str) -> str | None:
    """
    Persist log lines to the configured storage backend.
    Returns the URL/path of the stored log file, or None on failure.

    Currently supports 'local' storage.
    's3' support can be added here (e.g. via aiobotocore).
    """
    if not lines:
        return None
    try:
        loop = asyncio.get_event_loop()
        url = await loop.run_in_executor(None, _save_log_local, lines, job_id, node_id)
        return url
    except Exception as exc:
        logger.error("log storage failed job=%s node=%s: %s", job_id, node_id, exc)
        return None


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
            # Write key to a temp file within the private data dir
            key_path = Path(private_data_dir) / "ssh_key"
            key_path.write_text(credential_data["private_key"])
            key_path.chmod(0o600)
            host_vars["ansible_ssh_private_key_file"] = str(key_path)
        elif "password" in credential_data:
            host_vars["ansible_ssh_pass"] = credential_data["password"]

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
        "envvars": {
            "ANSIBLE_HOST_KEY_CHECKING": "False",
        },
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
    Returns the list of all collected lines (to be persisted to storage).
    """
    # Wait for ansible-runner to create the artifact directory and the stdout file (up to 5 s)
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
    log_file_url: str | None,
) -> None:
    """
    Update job_node status and, if all nodes have finished, update the overall job status.
    Stores the log_file_url (Object Storage / Local FS path) in job_nodes.
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
            jn.log_file_url = log_file_url

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
    """Execute an Ansible playbook on a single node.

    - SSH credentials are fetched from HashiCorp Vault via node.credential.
    - Real-time logs are streamed to Redis pub/sub.
    - Completed logs are compressed and stored to Object Storage / Local FS.
    - If the playbook has an exclusive_group, a Redis lock with TTL is held,
      with a heartbeat coroutine renewing it periodically to prevent deadlocks.
    """
    logger.info("run_job: job=%s node=%s", job_id, node_id)

    channel = CHANNEL_TPL.format(job_id=job_id)

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
                # Start heartbeat to keep the lock alive
                heartbeat_task = asyncio.create_task(
                    _lock_heartbeat(redis_client, node_id, lock_group, job_id, stop_heartbeat)
                )

            if not playbook.content:
                await _finish_node(job_id, node_id, "failed", None, None)
                await redis_client.publish(channel, json.dumps({
                    "type": "done", "status": "failed", "node_id": node_id,
                }))
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
                    # Proceed without credential — Ansible will use default key discovery

            stdout_lines: list[str] = []
            rc: int | None = None
            success = False

            with tempfile.TemporaryDirectory(prefix="minerva_job_") as tmpdir:
                try:
                    await _build_inventory(node, credential_data, tmpdir)
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
                    log_url = await _save_logs_to_storage(stdout_lines, job_id, node_id)
                    await _finish_node(job_id, node_id, "failed", rc, log_url)
                    await redis_client.publish(channel, json.dumps({
                        "type": "done", "status": "cancelled", "node_id": node_id,
                    }))
                    return {"status": "cancelled"}

            # ------------------------------------------------------------------
            # Persist logs to Object Storage / Local FS
            # ------------------------------------------------------------------
            log_file_url = await _save_logs_to_storage(stdout_lines, job_id, node_id)

            node_status = "success" if success else "failed"
            await _finish_node(job_id, node_id, node_status, rc, log_file_url)

            await redis_client.publish(channel, json.dumps({
                "type": "done", "status": node_status, "node_id": node_id,
            }))

            logger.info(
                "run_job: job=%s node=%s status=%s rc=%s log=%s",
                job_id, node_id, node_status, rc, log_file_url,
            )
            return {"status": node_status, "rc": rc, "lines": len(stdout_lines), "log_file_url": log_file_url}

        finally:
            # Stop heartbeat
            stop_heartbeat.set()
            if heartbeat_task:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

            # Release the exclusive lock
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
