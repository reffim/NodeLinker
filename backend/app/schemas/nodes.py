import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class NodeCreate(BaseModel):
    name: str = Field(..., max_length=128)
    host: str = Field(..., max_length=255)
    port: int = Field(22, ge=1, le=65535)
    ssh_user: str = Field("root", max_length=64)
    ssh_key_path: Optional[str] = Field(None, max_length=512)
    tags: Optional[list[str]] = None


class NodeUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=128)
    host: Optional[str] = Field(None, max_length=255)
    port: Optional[int] = Field(None, ge=1, le=65535)
    ssh_user: Optional[str] = Field(None, max_length=64)
    ssh_key_path: Optional[str] = Field(None, max_length=512)
    tags: Optional[list[str]] = None


class NodeResponse(BaseModel):
    id: uuid.UUID
    name: str
    host: str
    port: int
    ssh_user: str
    ssh_key_path: Optional[str]
    status: str
    last_seen_at: Optional[datetime]
    tags: Optional[list[str]]
    created_at: datetime

    model_config = {"from_attributes": True}


class NodeStatusEvent(BaseModel):
    node_id: str
    status: str
    last_seen_at: Optional[str] = None
