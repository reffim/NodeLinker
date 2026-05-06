import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class JobCreate(BaseModel):
    playbook_id: uuid.UUID
    node_ids: list[uuid.UUID] = Field(..., min_length=1, description="One or more target node IDs")
    extra_vars: Optional[dict] = Field(None, description="Extra variables passed to ansible-runner")


class JobNodeResponse(BaseModel):
    node_id: uuid.UUID
    status: str
    exit_code: Optional[int]

    model_config = {"from_attributes": True}


class JobResponse(BaseModel):
    id: uuid.UUID
    playbook_id: uuid.UUID
    status: str
    created_by: Optional[uuid.UUID]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    exclusive_lock_key: Optional[str]
    created_at: datetime
    job_nodes: list[JobNodeResponse]

    model_config = {"from_attributes": True}


class JobLogResponse(BaseModel):
    id: int
    job_id: uuid.UUID
    node_id: Optional[uuid.UUID]
    line_number: int
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}
