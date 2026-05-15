"""
Playbook CRUD API.

Routes:
  GET    /api/v1/playbooks
  POST   /api/v1/playbooks
  GET    /api/v1/playbooks/{playbook_id}
  PATCH  /api/v1/playbooks/{playbook_id}
  DELETE /api/v1/playbooks/{playbook_id}
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.models import Playbook, User
from app.schemas.playbooks import PlaybookCreate, PlaybookResponse, PlaybookUpdate

router = APIRouter(prefix="/playbooks", tags=["playbooks"])


@router.get("", response_model=list[PlaybookResponse])
async def list_playbooks(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[Playbook]:
    result = await db.execute(select(Playbook).order_by(Playbook.created_at))
    return list(result.scalars().all())


@router.post("", response_model=PlaybookResponse, status_code=status.HTTP_201_CREATED)
async def create_playbook(
    payload: PlaybookCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Playbook:
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    playbook = Playbook(**payload.model_dump())
    db.add(playbook)
    await db.commit()
    await db.refresh(playbook)
    return playbook


@router.get("/{playbook_id}", response_model=PlaybookResponse)
async def get_playbook(
    playbook_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> Playbook:
    return await _get_or_404(db, playbook_id)


@router.patch("/{playbook_id}", response_model=PlaybookResponse)
async def update_playbook(
    playbook_id: uuid.UUID,
    payload: PlaybookUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Playbook:
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    playbook = await _get_or_404(db, playbook_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(playbook, field, value)
    await db.commit()
    await db.refresh(playbook)
    return playbook


@router.delete("/{playbook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_playbook(
    playbook_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    playbook = await _get_or_404(db, playbook_id)
    await db.delete(playbook)
    await db.commit()


async def _get_or_404(db: AsyncSession, playbook_id: uuid.UUID) -> Playbook:
    result = await db.execute(select(Playbook).where(Playbook.id == playbook_id))
    playbook = result.scalar_one_or_none()
    if playbook is None:
        raise HTTPException(status_code=404, detail="Playbook not found")
    return playbook


@router.post("/groups/{group_name}/unlock", status_code=status.HTTP_200_OK)
async def force_unlock_group(
    group_name: str,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Force release all Redis locks for a specific exclusive group across all nodes."""
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    import redis.asyncio as aioredis
    from app.core.config import settings
    
    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        # Find all lock keys for this group
        pattern = f"node:*:exclusive:{group_name}"
        keys = await r.keys(pattern)
        if keys:
            await r.delete(*keys)
            return {"message": f"Cleared {len(keys)} locks for group '{group_name}'"}
        return {"message": f"No active locks found for group '{group_name}'"}
    finally:
        await r.aclose()
