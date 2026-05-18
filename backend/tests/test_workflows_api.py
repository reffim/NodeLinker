def test_workflow_models_importable():
    from app.models.models import Workflow, WorkflowStep, WorkflowRun, WorkflowRunStep
    assert Workflow.__tablename__ == "workflows"
    assert WorkflowStep.__tablename__ == "workflow_steps"
    assert WorkflowRun.__tablename__ == "workflow_runs"
    assert WorkflowRunStep.__tablename__ == "workflow_run_steps"
