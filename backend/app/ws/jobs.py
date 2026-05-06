"""
WebSocket endpoint: /ws/jobs/{job_id}

Streams real-time job log lines to the browser via Redis pub/sub.

Protocol:
  Server → Client messages (JSON):
    {"type": "log", "line_number": N, "content": "...", "node_id": "..."}
    {"type": "done", "status": "success|failed|cancelled", "node_id": "..."}
    {"type": "error", "detail": "..."}

  The client should close the connection after receiving type=="done" for all
  dispatched nodes, or it may close at any time (server handles it gracefully).

  If the job already has collected logs (resumed connection), the endpoint
  sends existing DB logs first, then switches to live pub/sub.
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
from app.models.models import Job, JobLog, JobNode

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

        # Replay existing logs from DB (catch-up for reconnecting clients)
        logs_res = await session.execute(
            select(JobLog)
            .where(JobLog.job_id == job_id)
            .order_by(JobLog.node_id, JobLog.line_number)
        )
        existing_logs = logs_res.scalars().all()

        # Check if job is already in terminal state
        terminal = job.status in ("success", "failed", "cancelled")

        # Load job_nodes to know how many done events to expect
        jn_res = await session.execute(
            select(JobNode).where(JobNode.job_id == job_id)
        )
        job_nodes = jn_res.scalars().all()
        total_nodes = len(job_nodes)
        done_nodes = sum(1 for jn in job_nodes if jn.status in ("success", "failed"))

    # 2. Send existing logs to catch up
    for log in existing_logs:
        try:
            await websocket.send_json({
                "type": "log",
                "line_number": log.line_number,
                "content": log.content,
                "node_id": str(log.node_id) if log.node_id else None,
            })
        except WebSocketDisconnect:
            return

    # 3. If already terminal, send done and close
    if terminal:
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

    # 4. Subscribe to Redis pub/sub and stream live logs
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
