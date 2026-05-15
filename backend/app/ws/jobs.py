"""
WebSocket endpoint: /ws/jobs/{job_id}

Streams real-time job log lines to the browser via Redis pub/sub.

Protocol:
  Server → Client messages (JSON):
    {"type": "log", "line_number": N, "content": "...", "node_id": "..."}
    {"type": "done", "status": "success|failed|cancelled", "node_id": "..."}
    {"type": "replay_url", "node_id": "...", "log_file_url": "..."}
    {"type": "error", "detail": "..."}

  For jobs already completed (reconnecting clients), the server sends
  type=="replay_url" messages with log_file_url for each node, then closes.
  Real-time streaming is only active while the job is running.

  The client should close the connection after receiving type=="done" for all
  dispatched nodes, or it may close at any time (server handles it gracefully).
"""
import asyncio
import json
import logging
import uuid

import redis.asyncio as aioredis
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.config import settings
from app.db.session import async_session_factory
from app.models.models import Job, JobNode

logger = logging.getLogger(__name__)

CHANNEL_TPL = "job:{job_id}:logs"
# How long to wait for pub/sub messages before checking if job is still active (seconds)
PUBSUB_POLL_TIMEOUT = 5.0


async def job_log_ws(websocket: WebSocket, job_id: uuid.UUID) -> None:
    await websocket.accept()

    channel = CHANNEL_TPL.format(job_id=str(job_id))

    # 1. Check job exists and load current state
    async with async_session_factory() as session:
        job_res = await session.execute(
            select(Job).where(Job.id == job_id)
        )
        job = job_res.scalar_one_or_none()
        if job is None:
            await websocket.send_json({"type": "error", "detail": "Job not found"})
            await websocket.close(code=4004)
            return

        # Check if job is already in terminal state
        terminal = job.status in ("success", "failed", "cancelled")

        # Load job_nodes to know status and log URLs
        jn_res = await session.execute(
            select(JobNode).where(JobNode.job_id == job_id)
        )
        job_nodes = jn_res.scalars().all()
        total_nodes = len(job_nodes)
        done_nodes = sum(1 for jn in job_nodes if jn.status in ("success", "failed"))

    # 2. If already terminal, send log_file_url replay messages and close
    #    (logs are stored in Object Storage / Local FS after job completion)
    if terminal:
        for jn in job_nodes:
            try:
                await websocket.send_json({
                    "type": "replay_url",
                    "node_id": str(jn.node_id),
                    "log_file_url": jn.log_file_url,  # may be None if storage failed
                })
            except WebSocketDisconnect:
                return
        try:
            await websocket.send_json({
                "type": "done",
                "status": job.status,
                "node_id": None,
                "detail": "job already completed",
            })
        except WebSocketDisconnect:
            pass
        await websocket.close()
        return

    # 3. Subscribe to Redis pub/sub and stream live logs
    redis_client = aioredis.from_url(settings.REDIS_URL)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)

    done_count = done_nodes  # nodes already done when we connected

    try:
        while True:
            try:
                message = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True, timeout=PUBSUB_POLL_TIMEOUT),
                    timeout=PUBSUB_POLL_TIMEOUT + 1,
                )
            except asyncio.TimeoutError:
                # Check if job moved to terminal state while we were waiting
                async with async_session_factory() as session:
                    job_res = await session.execute(select(Job).where(Job.id == job_id))
                    job = job_res.scalar_one_or_none()
                    if job and job.status in ("success", "failed", "cancelled"):
                        await websocket.send_json({
                            "type": "done",
                            "status": job.status,
                            "node_id": None,
                        })
                        break
                continue

            if message is None:
                continue

            try:
                data = json.loads(message["data"])
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

            msg_type = data.get("type")

            if msg_type == "log":
                try:
                    await websocket.send_json(data)
                except WebSocketDisconnect:
                    return

            elif msg_type == "done":
                try:
                    await websocket.send_json(data)
                except WebSocketDisconnect:
                    return
                done_count += 1
                if done_count >= total_nodes:
                    # All nodes reported done — close the stream
                    break

    except WebSocketDisconnect:
        logger.debug("ws/jobs/%s: client disconnected", job_id)
    except Exception as exc:
        logger.exception("ws/jobs/%s: error: %s", job_id, exc)
        try:
            await websocket.send_json({"type": "error", "detail": str(exc)})
        except Exception:
            pass
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
        except Exception:
            pass
        try:
            await redis_client.aclose()
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass
