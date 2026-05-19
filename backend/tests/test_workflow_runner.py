import pytest
import uuid
from unittest.mock import MagicMock, patch


def _make_job(status="success"):
    job = MagicMock()
    job.id = uuid.uuid4()
    job.status = status
    return job


def _make_run_step(step_id=None, status="pending"):
    rs = MagicMock()
    rs.id = uuid.uuid4()
    rs.workflow_step_id = step_id or uuid.uuid4()
    rs.job_id = None
    rs.status = status
    rs.started_at = None
    rs.finished_at = None
    return rs


def _make_wf_step(order=0, playbook_id=None, on_failure_step_id=None):
    s = MagicMock()
    s.id = uuid.uuid4()
    s.order = order
    s.playbook_id = playbook_id or uuid.uuid4()
    s.on_failure_step_id = on_failure_step_id
    return s


def _make_run(status="pending", node_ids=None):
    run = MagicMock()
    run.id = uuid.uuid4()
    run.status = status
    run.node_ids = node_ids or [uuid.uuid4()]
    run.extra_vars = {}
    run.created_by = uuid.uuid4()
    run.workflow_id = uuid.uuid4()
    return run


@pytest.mark.asyncio
async def test_orchestrator_success_single_step():
    """A single-step workflow that succeeds marks the run as success."""
    from app.worker.tasks.workflow_runner import _execute_workflow

    wf_step = _make_wf_step(order=0)
    run = _make_run()
    run_step = _make_run_step(step_id=wf_step.id)

    job = _make_job(status="success")

    with patch("app.worker.tasks.workflow_runner._load_run_context") as mock_ctx, \
         patch("app.worker.tasks.workflow_runner._create_job_for_step", return_value=job) as mock_create, \
         patch("app.worker.tasks.workflow_runner._poll_until_done", return_value="success") as mock_poll, \
         patch("app.worker.tasks.workflow_runner._update_run_step") as mock_update_step, \
         patch("app.worker.tasks.workflow_runner._update_run") as mock_update_run, \
         patch("app.worker.tasks.workflow_runner._publish_event") as mock_pub:

        mock_ctx.return_value = (run, [wf_step], {wf_step.id: run_step})

        await _execute_workflow(str(run.id))

        # Verify run was marked running then success (two distinct calls)
        assert mock_update_run.call_count == 2
        statuses = [c.args[1] for c in mock_update_run.call_args_list]
        assert statuses[0] == "running"
        assert statuses[1] == "success"
        # started_at kwarg present on first call, finished_at on second
        assert "started_at" in mock_update_run.call_args_list[0].kwargs
        assert "finished_at" in mock_update_run.call_args_list[1].kwargs


@pytest.mark.asyncio
async def test_orchestrator_step_failure_no_fallback_fails_run():
    """A failed step with no on_failure_step_id marks the run as failed."""
    from app.worker.tasks.workflow_runner import _execute_workflow

    wf_step = _make_wf_step(order=0, on_failure_step_id=None)
    run = _make_run()
    run_step = _make_run_step(step_id=wf_step.id)
    job = _make_job(status="failed")

    with patch("app.worker.tasks.workflow_runner._load_run_context") as mock_ctx, \
         patch("app.worker.tasks.workflow_runner._create_job_for_step", return_value=job), \
         patch("app.worker.tasks.workflow_runner._poll_until_done", return_value="failed"), \
         patch("app.worker.tasks.workflow_runner._update_run_step"), \
         patch("app.worker.tasks.workflow_runner._update_run") as mock_update_run, \
         patch("app.worker.tasks.workflow_runner._publish_event"):

        mock_ctx.return_value = (run, [wf_step], {wf_step.id: run_step})

        await _execute_workflow(str(run.id))

        final_calls = [c for c in mock_update_run.call_args_list if "failed" in c.args]
        assert len(final_calls) >= 1


@pytest.mark.asyncio
async def test_orchestrator_step_failure_with_fallback_jumps():
    """A failed step with on_failure_step_id causes the orchestrator to execute the fallback step."""
    from app.worker.tasks.workflow_runner import _execute_workflow

    fallback_step = _make_wf_step(order=1, on_failure_step_id=None)
    wf_step = _make_wf_step(order=0, on_failure_step_id=fallback_step.id)

    run = _make_run()
    run_step_0 = _make_run_step(step_id=wf_step.id)
    run_step_1 = _make_run_step(step_id=fallback_step.id)

    call_count = {"n": 0}

    def poll_side_effect(*args, **kwargs):
        call_count["n"] += 1
        return "failed" if call_count["n"] == 1 else "success"

    with patch("app.worker.tasks.workflow_runner._load_run_context") as mock_ctx, \
         patch("app.worker.tasks.workflow_runner._create_job_for_step", return_value=_make_job()), \
         patch("app.worker.tasks.workflow_runner._poll_until_done", side_effect=poll_side_effect), \
         patch("app.worker.tasks.workflow_runner._update_run_step"), \
         patch("app.worker.tasks.workflow_runner._update_run") as mock_update_run, \
         patch("app.worker.tasks.workflow_runner._publish_event"):

        mock_ctx.return_value = (
            run,
            [wf_step, fallback_step],
            {wf_step.id: run_step_0, fallback_step.id: run_step_1},
        )

        await _execute_workflow(str(run.id))

        assert call_count["n"] == 2  # both steps were executed
        final_calls = [c for c in mock_update_run.call_args_list if "success" in c.args]
        assert len(final_calls) >= 1
