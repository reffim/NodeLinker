import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
from datetime import datetime, timezone


def make_user(role="operator"):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.role = role
    return user


def make_workflow(name="Test Workflow", steps=None):
    wf = MagicMock()
    wf.id = uuid.uuid4()
    wf.name = name
    wf.description = None
    wf.created_at = datetime.now(timezone.utc)
    wf.updated_at = datetime.now(timezone.utc)
    wf.steps = steps or []
    return wf


def make_workflow_step(workflow_id=None, order=0, playbook_id=None, on_failure_step_id=None):
    step = MagicMock()
    step.id = uuid.uuid4()
    step.workflow_id = workflow_id or uuid.uuid4()
    step.order = order
    step.playbook_id = playbook_id or uuid.uuid4()
    step.on_failure_step_id = on_failure_step_id
    return step


def make_workflow_run(workflow_id=None, status="pending", node_ids=None):
    run = MagicMock()
    run.id = uuid.uuid4()
    run.workflow_id = workflow_id or uuid.uuid4()
    run.status = status
    run.node_ids = node_ids or [uuid.uuid4()]
    run.extra_vars = {}
    run.created_by = uuid.uuid4()
    run.started_at = None
    run.finished_at = None
    run.created_at = datetime.now(timezone.utc)
    run.workflow_run_steps = []
    return run


def make_workflow_run_step(run_id=None, step_id=None, status="pending", job_id=None):
    rs = MagicMock()
    rs.id = uuid.uuid4()
    rs.workflow_run_id = run_id or uuid.uuid4()
    rs.workflow_step_id = step_id or uuid.uuid4()
    rs.job_id = job_id
    rs.status = status
    rs.started_at = None
    rs.finished_at = None
    return rs
