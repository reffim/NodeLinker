"""
WebSocket endpoint: /ws/workflow-runs/{run_id}

Streams workflow step-transition events to the client via Redis pub/sub.

Protocol — Server → Client (JSON):
  {"type": "step_started",  "step_id": "...", "job_id": "...", "order": N}
  {"type": "step_finished", "step_id": "...", "status": "success|failed"}
  {"type": "workflow_done", "status": "success|failed|cancelled"}
  {"type": "error",         "detail": "..."}

For already-completed runs, the server sends the current run status as a
workflow_done message and closes immediately.
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
from app.models.models import WorkflowRun

logger = logging.getLogger(__name__)

WF_CHANNEL_TPL = "workflow:{run_id}:events"
PUBSUB_POLL_TIMEOUT = 5.0
TERMINAL_STATUSES = {"success", "failed", "cancelled"}


async def workflow_run_ws(websocket: WebSocket, run_id: uuid.UUID) -> None:
    await websocket.accept()

    channel = WF_CHANNEL_TPL.format(run_id=str(run_id))

    async with async_session_factory() as session:
        res = await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
        run = res.scalar_one_or_none()
        if run is None:
            await websocket.send_json({"type": "error", "detail": "WorkflowRun not found"})
            await websocket.close(code=4004)
            return
        already_done = run.status in TERMINAL_STATUSES
        current_status = run.status

    if already_done:
        try:
            await websocket.send_json({"type": "workflow_done", "status": current_status})
        except WebSocketDisconnect:
            pass
        await websocket.close()
        return

    redis_client = aioredis.from_url(settings.REDIS_URL)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)

    try:
        while True:
            try:
                message = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True, timeout=PUBSUB_POLL_TIMEOUT),
                    timeout=PUBSUB_POLL_TIMEOUT + 1,
                )
            except asyncio.TimeoutError:
                async with async_session_factory() as session:
                    res = await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
                    run = res.scalar_one_or_none()
                    if run and run.status in TERMINAL_STATUSES:
                        await websocket.send_json({"type": "workflow_done", "status": run.status})
                        break
                continue

            if message is None:
                continue

            try:
                data = json.loads(message["data"])
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

            try:
                await websocket.send_json(data)
            except WebSocketDisconnect:
                return

            if data.get("type") == "workflow_done":
                break

    except WebSocketDisconnect:
        logger.debug("ws/workflow-runs/%s: client disconnected", run_id)
    except Exception as exc:
        logger.exception("ws/workflow-runs/%s: error: %s", run_id, exc)
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
