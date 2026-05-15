import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CredentialCreate(BaseModel):
    name: str = Field(..., max_length=128)
    type: str = Field(..., pattern="^(ssh_key|ssh_password)$")
    vault_path: str = Field(..., max_length=512, description="KV v2 path in Vault, e.g. 'ansible/node-prod-01'")
    # Secret material to write into Vault on creation
    secret: dict = Field(..., description="Secret key-values to store in Vault (e.g. {'private_key': '...'})")


class CredentialUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=128)
    # Updating secret material in Vault
    secret: Optional[dict] = Field(None, description="New secret key-values to overwrite in Vault")


class CredentialResponse(BaseModel):
    id: uuid.UUID
    name: str
    type: str
    vault_path: str
    created_by: Optional[uuid.UUID]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
