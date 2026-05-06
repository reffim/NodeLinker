"""
Redis distributed lock service for Minerva mutual exclusion.

Lock key format: node:{node_id}:exclusive:{playbook_group}

Uses SET NX PX (atomic set-if-not-exists with millisecond TTL) to acquire;
DEL with Lua ownership check to release safely.

Design:
- Acquire returns True (lock held by caller) or False (already held by another)
- Release is a no-op if the token does not match (avoids releasing another owner's lock)
- TTL is generous (LOCK_TTL_SECONDS) to survive long-running playbooks; the
  release on completion is the authoritative unlock.
"""

import logging
from typing import Optional

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

# Default TTL for exclusive locks: 2 hours (safety net if a worker crashes)
LOCK_TTL_SECONDS: int = 7200

# Lua script: DEL key only if its value equals the given token (atomic ownership check)
_RELEASE_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""


def _lock_key(node_id: str, playbook_group: str) -> str:
    return f"node:{node_id}:exclusive:{playbook_group}"


async def acquire_lock(
    redis_client: aioredis.Redis,
    node_id: str,
    playbook_group: str,
    token: str,
    ttl_seconds: int = LOCK_TTL_SECONDS,
) -> bool:
    """
    Try to acquire the exclusive lock for (node_id, playbook_group).

    Returns True if the lock was acquired, False if it is already held.
    `token` must be a unique value (e.g. job_id) so the owner can release it safely.
    """
    key = _lock_key(node_id, playbook_group)
    result = await redis_client.set(key, token, nx=True, ex=ttl_seconds)
    acquired = result is not None
    if acquired:
        logger.debug("lock acquired: key=%s token=%s ttl=%s", key, token, ttl_seconds)
    else:
        holder = await redis_client.get(key)
        logger.debug(
            "lock already held: key=%s holder=%s",
            key,
            holder.decode() if isinstance(holder, bytes) else holder,
        )
    return acquired


async def release_lock(
    redis_client: aioredis.Redis,
    node_id: str,
    playbook_group: str,
    token: str,
) -> bool:
    """
    Release the exclusive lock only if the token matches (we own it).

    Returns True if the lock was released, False if the token did not match
    (already expired or owned by someone else).
    """
    key = _lock_key(node_id, playbook_group)
    released = await redis_client.eval(_RELEASE_SCRIPT, 1, key, token)  # type: ignore[arg-type]
    if released:
        logger.debug("lock released: key=%s token=%s", key, token)
    else:
        logger.warning(
            "lock release failed (token mismatch or already gone): key=%s token=%s",
            key,
            token,
        )
    return bool(released)


async def get_lock_holder(
    redis_client: aioredis.Redis,
    node_id: str,
    playbook_group: str,
) -> Optional[str]:
    """Return the token of the current lock holder, or None if unlocked."""
    key = _lock_key(node_id, playbook_group)
    value = await redis_client.get(key)
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else value
