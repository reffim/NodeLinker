"""
Async SSH health probe Celery task.

Every 30 s, probes all registered nodes concurrently via asyncssh (non-blocking)
and updates node status in the database, then publishes a status-change event to
the Redis pub/sub channel "node_status" for WebSocket fan-out.

SSH credentials are retrieved from HashiCorp Vault via the node's credential_id.
If no credential is set, the probe falls back to TCP reachability (port check).
"""
import asyncio
import json
import logging
import socket
from datetime import datetime, timezone

import asyncssh
import redis as sync_redis
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.vault import get_credential
from app.db.session import async_session_factory
from app.models.models import Credential, Node
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

REDIS_CHANNEL = "node_status"
SSH_TIMEOUT = 5.0  # seconds


async def _probe_ssh(
    host: str,
    port: int,
    username: str,
    credential: Credential | None,
    secret_data: dict | None,
) -> str:
    """
    Attempt a non-blocking SSH connection via asyncssh.
    Returns: "online" | "offline" | "unreachable"
    """
    connect_kwargs: dict = {
        "host": host,
        "port": port,
        "username": username,
        "connect_timeout": SSH_TIMEOUT,
        "known_hosts": None,  # accept any host key for health probing
    }
    if credential and secret_data:
        if credential.type == "ssh_password":
            connect_kwargs["password"] = secret_data.get("password")
        elif credential.type == "ssh_key":
            pk = secret_data.get("private_key")
            if pk:
                try:
                    connect_kwargs["client_keys"] = [asyncssh.import_private_key(pk)]
                except Exception as exc:
                    logger.warning("health_probe: Failed to import private key for host=%s: %s", host, exc)

    try:
        async with asyncssh.connect(**connect_kwargs):
            return "online"
    except asyncssh.PermissionDenied:
        # Auth failed but TCP reachable → host is up
        return "online"
    except (asyncssh.DisconnectError, asyncssh.ConnectionLost, ConnectionRefusedError):
        return "offline"
    except (asyncio.TimeoutError, OSError, Exception) as exc:
        logger.debug("health_probe: SSH failed host=%s: %s — falling back to TCP", host, exc)
        # TCP port reachability fallback
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=SSH_TIMEOUT,
            )
            writer.close()
            return "offline"
        except Exception:
            return "unreachable"


async def _update_node_status(node_id: str, status: str, last_seen_at: datetime | None) -> None:
    async with async_session_factory() as session:
        result = await session.execute(select(Node).where(Node.id == node_id))
        node = result.scalar_one_or_none()
        if node is None:
            return
        if node.status == status:
            return  # no change — skip DB write and pub/sub
        node.status = status
        if status == "online":
            node.last_seen_at = last_seen_at
        await session.commit()


def _publish_status(r: sync_redis.Redis, node_id: str, status: str, last_seen_at: datetime | None) -> None:
    payload = json.dumps(
        {
            "node_id": str(node_id),
            "status": status,
            "last_seen_at": last_seen_at.isoformat() if last_seen_at else None,
        }
    )
    r.publish(REDIS_CHANNEL, payload)


async def _probe_node(node: Node, r: sync_redis.Redis) -> None:
    old_status = node.status
    now = datetime.now(timezone.utc)

    # Fetch credential from Vault (async, non-blocking)
    secret_data = None
    if node.credential:
        try:
            secret_data = await get_credential(node.credential.vault_path)
        except Exception as exc:
            logger.warning("health_probe: vault read failed path=%s: %s", node.credential.vault_path, exc)

    # Run the async SSH probe directly (no thread executor needed)
    new_status = await _probe_ssh(node.host, node.port, node.ssh_user, node.credential, secret_data)

    last_seen = now if new_status == "online" else node.last_seen_at
    await _update_node_status(str(node.id), new_status, last_seen)
    if old_status != new_status:
        _publish_status(r, node.id, new_status, last_seen)
        logger.info("Node %s (%s): %s → %s", node.name, node.host, old_status, new_status)


async def _run_probes() -> None:
    r = sync_redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(Node).options(selectinload(Node.credential))
            )
            nodes = result.scalars().all()

        # Probe all nodes concurrently — asyncssh is non-blocking, scales well
        tasks = [_probe_node(node, r) for node in nodes]
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        r.close()


@celery_app.task(name="app.worker.tasks.health_probe.probe_all_nodes")
def probe_all_nodes() -> None:
    asyncio.run(_run_probes())
