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
