import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PlaybookCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    content: Optional[str] = None
    source_type: str = Field("local", pattern="^(local|git)$")
    git_url: Optional[str] = Field(None, max_length=512)
    git_ref: Optional[str] = Field(None, max_length=128)
    exclusive_group: Optional[str] = Field(None, max_length=128)


class PlaybookUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    content: Optional[str] = None
    source_type: Optional[str] = Field(None, pattern="^(local|git)$")
    git_url: Optional[str] = Field(None, max_length=512)
    git_ref: Optional[str] = Field(None, max_length=128)
    exclusive_group: Optional[str] = Field(None, max_length=128)


class PlaybookResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str]
    content: Optional[str]
    source_type: str
    git_url: Optional[str]
    git_ref: Optional[str]
    exclusive_group: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
