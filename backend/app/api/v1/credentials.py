"""
Credentials API — CRUD for SSH credential metadata.

Actual secret material is stored in HashiCorp Vault;
only metadata (name, type, vault_path) lives in PostgreSQL.

Routes:
  GET    /api/v1/credentials
  POST   /api/v1/credentials
  GET    /api/v1/credentials/{credential_id}
  PATCH  /api/v1/credentials/{credential_id}
  DELETE /api/v1/credentials/{credential_id}
"""
import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.vault import write_credential, delete_credential
from app.db.session import get_db
from app.models.models import Credential, User
from app.schemas.credentials import CredentialCreate, CredentialResponse, CredentialUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/credentials", tags=["credentials"])


@router.get("", response_model=list[CredentialResponse])
async def list_credentials(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[Credential]:
    result = await db.execute(select(Credential).order_by(Credential.created_at))
    return list(result.scalars().all())


@router.post("", response_model=CredentialResponse, status_code=status.HTTP_201_CREATED)
async def create_credential(
    payload: CredentialCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Credential:
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # Check vault_path uniqueness
    existing = await db.execute(
        select(Credential).where(Credential.vault_path == payload.vault_path)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="A credential with this vault_path already exists")

    # Write the actual secret to Vault first
    try:
        await write_credential(payload.vault_path, payload.secret)
    except Exception as exc:
        logger.error("create_credential: vault write failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Vault write failed: {exc}")

    # Persist metadata in PostgreSQL (no secret material stored here)
    credential = Credential(
        name=payload.name,
        type=payload.type,
        vault_path=payload.vault_path,
        created_by=current_user.id,
    )
    db.add(credential)
    await db.commit()
    await db.refresh(credential)
    return credential


@router.get("/{credential_id}", response_model=CredentialResponse)
async def get_credential(
    credential_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> Credential:
    return await _get_or_404(db, credential_id)


@router.patch("/{credential_id}", response_model=CredentialResponse)
async def update_credential(
    credential_id: uuid.UUID,
    payload: CredentialUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Credential:
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    credential = await _get_or_404(db, credential_id)

    if payload.name is not None:
        credential.name = payload.name

    # If new secret material is provided, update Vault
    if payload.secret is not None:
        try:
            await write_credential(credential.vault_path, payload.secret)
        except Exception as exc:
            logger.error("update_credential: vault write failed: %s", exc)
            raise HTTPException(status_code=502, detail=f"Vault write failed: {exc}")

    await db.commit()
    await db.refresh(credential)
    return credential


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential_endpoint(
    credential_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    credential = await _get_or_404(db, credential_id)

    # Delete secret from Vault first
    try:
        await delete_credential(credential.vault_path)
    except Exception as exc:
        logger.warning("delete_credential: vault delete failed (continuing): %s", exc)

    await db.delete(credential)
    await db.commit()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _get_or_404(db: AsyncSession, credential_id: uuid.UUID) -> Credential:
    result = await db.execute(select(Credential).where(Credential.id == credential_id))
    credential = result.scalar_one_or_none()
    if credential is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    return credential
