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
    # URL pointing to Object Storage (S3) or Local FS where the compressed
    # log archive is stored. Null while the job is still running.
    log_file_url: Optional[str]

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
