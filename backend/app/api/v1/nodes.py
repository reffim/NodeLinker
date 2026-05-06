"""
Node CRUD API + WebSocket endpoint for live node status fan-out.

Routes:
  GET    /api/v1/nodes
  POST   /api/v1/nodes
  GET    /api/v1/nodes/{node_id}
  PATCH  /api/v1/nodes/{node_id}
  DELETE /api/v1/nodes/{node_id}

  WebSocket  /ws/nodes   (streams NodeStatusEvent JSON messages)
"""
import asyncio
import json
import logging
import uuid
from typing import AsyncIterator

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.models import Node, User
from app.schemas.nodes import NodeCreate, NodeResponse, NodeUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/nodes", tags=["nodes"])

REDIS_CHANNEL = "node_status"


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[NodeResponse])
async def list_nodes(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[Node]:
    result = await db.execute(select(Node).order_by(Node.created_at))
    return list(result.scalars().all())


@router.post("", response_model=NodeResponse, status_code=status.HTTP_201_CREATED)
async def create_node(
    payload: NodeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Node:
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    node = Node(**payload.model_dump())
    db.add(node)
    await db.commit()
    await db.refresh(node)
    return node


@router.get("/{node_id}", response_model=NodeResponse)
async def get_node(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> Node:
    node = await _get_or_404(db, node_id)
    return node


@router.patch("/{node_id}", response_model=NodeResponse)
async def update_node(
    node_id: uuid.UUID,
    payload: NodeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Node:
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    node = await _get_or_404(db, node_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(node, field, value)
    await db.commit()
    await db.refresh(node)
    return node


@router.delete("/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    node = await _get_or_404(db, node_id)
    await db.delete(node)
    await db.commit()


# ---------------------------------------------------------------------------
# WebSocket — live node status fan-out
# ---------------------------------------------------------------------------

@router.websocket("/status-stream")
async def node_status_ws(websocket: WebSocket) -> None:
    """
    WebSocket: ws://.../ws/nodes  (also reachable at /api/v1/nodes/status-stream).
    Subscribe to Redis pub/sub channel and forward status events to the client.
    """
    await websocket.accept()
    redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    pubsub = redis.pubsub()
    await pubsub.subscribe(REDIS_CHANNEL)
    logger.debug("WebSocket /ws/nodes: client connected")
    try:
        async for message in _redis_messages(pubsub):
            await websocket.send_text(message)
    except WebSocketDisconnect:
        logger.debug("WebSocket /ws/nodes: client disconnected")
    finally:
        await pubsub.unsubscribe(REDIS_CHANNEL)
        await redis.aclose()


async def _redis_messages(pubsub: aioredis.client.PubSub) -> AsyncIterator[str]:
    """Yield raw Redis pub/sub messages as JSON strings."""
    while True:
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
        if message and message["type"] == "message":
            yield message["data"]
        else:
            await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _get_or_404(db: AsyncSession, node_id: uuid.UUID) -> Node:
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return node
