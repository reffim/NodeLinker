def test_workflow_models_importable():
    from app.models.models import Workflow, WorkflowStep, WorkflowRun, WorkflowRunStep
    assert Workflow.__tablename__ == "workflows"
    assert WorkflowStep.__tablename__ == "workflow_steps"
    assert WorkflowRun.__tablename__ == "workflow_runs"
    assert WorkflowRunStep.__tablename__ == "workflow_run_steps"


def test_workflow_schemas_importable():
    from app.schemas.workflows import (
        WorkflowStepCreate,
        WorkflowCreate,
        WorkflowUpdate,
        WorkflowStepResponse,
        WorkflowResponse,
        WorkflowRunCreate,
        WorkflowRunStepResponse,
        WorkflowRunResponse,
    )
    assert WorkflowCreate.__name__ == "WorkflowCreate"


def test_workflow_create_validates_steps():
    from app.schemas.workflows import WorkflowCreate, WorkflowStepCreate
    import uuid
    wf = WorkflowCreate(
        name="My Pipeline",
        steps=[
            WorkflowStepCreate(order=0, playbook_id=uuid.uuid4(), on_failure_step_order=None),
        ]
    )
    assert len(wf.steps) == 1


def test_workflow_run_create_requires_node_ids():
    from app.schemas.workflows import WorkflowRunCreate
    import pytest as pt
    with pt.raises(Exception):
        WorkflowRunCreate(node_ids=[])
