import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class WorkflowStepCreate(BaseModel):
    order: int = Field(..., ge=0)
    playbook_id: uuid.UUID
    on_failure_step_order: Optional[int] = Field(
        None, ge=0,
        description="order index of the fallback step within this workflow; resolved to FK after creation"
    )


class WorkflowCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    steps: list[WorkflowStepCreate] = Field(..., min_length=1)


class WorkflowUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None


class WorkflowStepResponse(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    order: int
    playbook_id: uuid.UUID
    on_failure_step_id: Optional[uuid.UUID]

    model_config = {"from_attributes": True}


class WorkflowResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime
    steps: list[WorkflowStepResponse]

    model_config = {"from_attributes": True}


class WorkflowRunCreate(BaseModel):
    node_ids: list[uuid.UUID] = Field(..., min_length=1)
    extra_vars: Optional[dict] = None


class WorkflowRunStepResponse(BaseModel):
    id: uuid.UUID
    workflow_run_id: uuid.UUID
    workflow_step_id: uuid.UUID
    job_id: Optional[uuid.UUID]
    status: str
    started_at: Optional[datetime]
    finished_at: Optional[datetime]

    model_config = {"from_attributes": True}


class WorkflowRunResponse(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    status: str
    created_by: Optional[uuid.UUID]
    node_ids: list[uuid.UUID]
    extra_vars: Optional[dict]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    created_at: datetime
    workflow_run_steps: list[WorkflowRunStepResponse]

    model_config = {"from_attributes": True}
