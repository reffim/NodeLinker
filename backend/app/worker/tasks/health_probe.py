"""
SSH/ICMP health probe Celery task.

Every 30 s, probes all registered nodes via SSH (Paramiko) and updates
node status in the database, then publishes a status-change event to
the Redis pub/sub channel "node_status" for WebSocket fan-out.
"""
import asyncio
import json
import logging
import socket
from datetime import datetime, timezone

import paramiko
import redis as sync_redis
from sqlalchemy import select

from app.core.config import settings
from app.db.session import async_session_factory
from app.models.models import Node
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

REDIS_CHANNEL = "node_status"
SSH_TIMEOUT = 5  # seconds


def _probe_ssh(host: str, port: int, username: str, key_path: str | None) -> str:
    """
    Attempt an SSH connection to the node.
    Returns: "online" | "offline" | "unreachable"
    """
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        connect_kwargs: dict = {
            "hostname": host,
            "port": port,
            "username": username,
            "timeout": SSH_TIMEOUT,
            "banner_timeout": SSH_TIMEOUT,
            "auth_timeout": SSH_TIMEOUT,
        }
        if key_path:
            connect_kwargs["key_filename"] = key_path
        else:
            connect_kwargs["look_for_keys"] = True
            connect_kwargs["allow_agent"] = True

        client.connect(**connect_kwargs)
        return "online"
    except paramiko.AuthenticationException:
        # Auth failed but TCP reachable → host is up
        return "online"
    except (paramiko.SSHException, socket.timeout, TimeoutError, OSError):
        # Try ICMP-style TCP-connect fallback to port 22
        try:
            with socket.create_connection((host, port), timeout=SSH_TIMEOUT):
                return "offline"
        except OSError:
            return "unreachable"
    finally:
        client.close()


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
    new_status = await asyncio.get_event_loop().run_in_executor(
        None, _probe_ssh, node.host, node.port, node.ssh_user, node.ssh_key_path
    )
    last_seen = now if new_status == "online" else node.last_seen_at
    await _update_node_status(str(node.id), new_status, last_seen)
    if old_status != new_status:
        _publish_status(r, node.id, new_status, last_seen)
        logger.info("Node %s (%s): %s → %s", node.name, node.host, old_status, new_status)


async def _run_probes() -> None:
    r = sync_redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        async with async_session_factory() as session:
            result = await session.execute(select(Node))
            nodes = result.scalars().all()

        tasks = [_probe_node(node, r) for node in nodes]
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        r.close()


@celery_app.task(name="app.worker.tasks.health_probe.probe_all_nodes")
def probe_all_nodes() -> None:
    asyncio.run(_run_probes())
