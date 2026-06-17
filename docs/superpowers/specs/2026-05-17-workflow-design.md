# Workflow Feature Design

**Date:** 2026-05-17  
**Project:** NodeLinker (project_minerva)  
**Branch:** feature/workflow  
**Status:** Approved

---

## Summary

Workflow is a named, reusable definition of multiple Ansible playbooks executed in sequence on a shared set of nodes. Each step can optionally specify a fallback step to execute on failure, enabling rollback patterns. The implementation reuses the existing `Job`/`run_job` infrastructure and adds a Celery orchestrator task that drives step execution.

---

## Requirements

| # | Requirement |
|---|-------------|
| 1 | Steps execute sequentially; a step begins only after the previous step completes |
| 2 | Nodes are specified at run time and shared across all steps |
| 3 | A step is considered successful only when **all** nodes report success |
| 4 | On failure, a step can optionally specify a fallback step to jump to; if none, the workflow fails |
| 5 | Workflow runs track per-step status and the Job created for each step |

---

## Data Model

Four new tables are added. Existing `Playbook`, `Job`, and `JobNode` tables are unchanged.

### `workflows`
```
id           UUID  PK
name         VARCHAR(255)  NOT NULL
description  TEXT
created_at   TIMESTAMPTZ
updated_at   TIMESTAMPTZ
```

### `workflow_steps`
```
id                   UUID  PK
workflow_id          UUID  FK → workflows.id  ON DELETE CASCADE
order                INTEGER  NOT NULL
playbook_id          UUID  FK → playbooks.id  ON DELETE RESTRICT
on_failure_step_id   UUID  FK → workflow_steps.id  ON DELETE SET NULL  nullable
```

`order` is 0-based and determines execution sequence. `on_failure_step_id` is a self-referencing FK; NULL means the workflow fails on step failure with no fallback.

### `workflow_runs`
```
id           UUID  PK
workflow_id  UUID  FK → workflows.id  ON DELETE RESTRICT
status       ENUM(pending, running, success, failed, cancelled)
created_by   UUID  FK → users.id  ON DELETE SET NULL  nullable
node_ids     UUID[]  NOT NULL
extra_vars   JSONB  nullable
started_at   TIMESTAMPTZ  nullable
finished_at  TIMESTAMPTZ  nullable
created_at   TIMESTAMPTZ
```

`node_ids` stores the full list of target nodes at run time, preserving the intent even if nodes are later deleted.

### `workflow_run_steps`
```
id                UUID  PK
workflow_run_id   UUID  FK → workflow_runs.id  ON DELETE CASCADE
workflow_step_id  UUID  FK → workflow_steps.id  ON DELETE RESTRICT
job_id            UUID  FK → jobs.id  ON DELETE SET NULL  nullable
status            ENUM(pending, running, success, failed, skipped)
started_at        TIMESTAMPTZ  nullable
finished_at       TIMESTAMPTZ  nullable
```

`WorkflowRunStep` records for **all** steps are pre-created (status=`pending`, job_id=NULL) when the `WorkflowRun` is created. This allows the API to return the full step list immediately. `job_id` is populated by the orchestrator just before dispatching that step's Job. `skipped` is applied to steps that were never reached because an earlier failure had no fallback step.

---

## API Endpoints

Permissions follow the existing pattern: `admin | operator` for create/run, `admin` for delete, all authenticated roles for reads.

### Workflow Definitions

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/workflows` | List all workflow definitions |
| POST | `/api/v1/workflows` | Create workflow with inline steps |
| GET | `/api/v1/workflows/{id}` | Get definition with steps |
| PATCH | `/api/v1/workflows/{id}` | Update name/description |
| DELETE | `/api/v1/workflows/{id}` | Delete (admin only) |

`POST /api/v1/workflows` request body:
```json
{
  "name": "Deploy Pipeline",
  "description": "optional",
  "steps": [
    { "order": 0, "playbook_id": "<uuid>", "on_failure_step_order": null },
    { "order": 1, "playbook_id": "<uuid>", "on_failure_step_order": 3 },
    { "order": 2, "playbook_id": "<uuid>", "on_failure_step_order": null },
    { "order": 3, "playbook_id": "<uuid>", "on_failure_step_order": null }
  ]
}
```

`on_failure_step_order` references another step's `order` index within the same payload. Steps are created atomically; after inserting all steps, the API resolves each `on_failure_step_order` to the corresponding `WorkflowStep.id` and sets `on_failure_step_id` in a second pass. The resolved `on_failure_step_id` UUID is returned in all read responses. The API validates that every referenced order value exists in the same workflow.

### Workflow Runs

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/workflows/{id}/runs` | Start a workflow run |
| GET | `/api/v1/workflows/{id}/runs` | List runs for a workflow |
| GET | `/api/v1/workflow-runs/{run_id}` | Run detail with per-step status and job_ids |
| POST | `/api/v1/workflow-runs/{run_id}/cancel` | Cancel a running workflow |

`POST /api/v1/workflows/{id}/runs` request body:
```json
{
  "node_ids": ["<uuid>", "<uuid>"],
  "extra_vars": {}
}
```

Response includes `workflow_run_steps[]` with each step's current `status` and `job_id`.

---

## Celery Orchestrator Task

**File:** `backend/app/worker/tasks/workflow_runner.py`  
**Task name:** `app.worker.tasks.workflow_runner.run_workflow`

The task is dispatched immediately after the `WorkflowRun` record is created by the API.

### Execution Flow

```
run_workflow(workflow_run_id)
│
├─ Load WorkflowRun → set status = "running", started_at = now
├─ Load WorkflowSteps ordered by `order` ASC
│
└─ Loop over current step:
   │
   ├─ Create Job(playbook_id, created_by, status="pending")
   ├─ Create JobNode per node_id
   ├─ Dispatch run_job.delay() per node (existing mechanism, unchanged)
   ├─ Create WorkflowRunStep(job_id=job.id, status="running", started_at=now)
   │
   ├─ Poll loop (5s interval):
   │   ├─ Reload WorkflowRun — if status=="cancelled": cancel current Job → exit
   │   └─ Reload Job — if status in {success, failed, cancelled}: break
   │
   ├─ Job.status == "cancelled"
   │   └─ WorkflowRun.status = "cancelled", finished_at = now → exit
   │
   ├─ Job.status == "success"
   │   ├─ WorkflowRunStep.status = "success", finished_at = now
   │   ├─ next step exists → continue loop
   │   └─ no more steps → WorkflowRun.status = "success", finished_at = now → exit
   │
   └─ Job.status == "failed"
       ├─ WorkflowRunStep.status = "failed", finished_at = now
       ├─ on_failure_step_id set → jump to that step, continue loop
       └─ on_failure_step_id is NULL
           └─ WorkflowRun.status = "failed", finished_at = now → exit
```

### Cancellation

The cancel API sets `WorkflowRun.status = "cancelled"`. The orchestrator detects this in the next poll cycle (within 5 seconds), calls the existing `cancel_job` logic on the current running Job, marks `WorkflowRunStep.status = "failed"`, and exits.

### Error handling

If the orchestrator task itself crashes (worker restart, unhandled exception), `WorkflowRun.status` remains `"running"`. A startup sweep (Celery beat task, runs once at boot) checks for stale `running` workflow runs older than a configurable threshold and marks them `"failed"`.

---

## Real-time Events

### Existing channel (reused, unchanged)

Each step's Job streams logs on the existing channel:
```
job:{job_id}:logs
```
Clients use the `job_id` from `WorkflowRunStep` to subscribe to the log stream for the current step.

### New channel

```
workflow:{workflow_run_id}:events
```

Published by the orchestrator task at step transitions:

```json
{ "type": "step_started",  "step_id": "<uuid>", "job_id": "<uuid>", "order": 1 }
{ "type": "step_finished", "step_id": "<uuid>", "status": "success|failed" }
{ "type": "workflow_done", "status": "success|failed|cancelled" }
```

### New WebSocket endpoint

`/ws/workflow-runs/{run_id}` — follows the same pattern as the existing `/ws/jobs/{job_id}` handler in `backend/app/ws/jobs.py`. Subscribes to `workflow:{run_id}:events` and forwards messages to the connected client.

---

## Frontend Monitoring View

A new WorkflowRun detail page shows step-by-step progress. The client subscribes to `workflow:{run_id}:events` and updates the view on each event. Clicking a step opens the existing Job log viewer for that step's `job_id`.

```
[Deploy Pipeline]  ●  running

Step 0  ✅ success        [View logs]
Step 1  ⏳ running        [View logs]   ← current step
Step 2  ○  pending
Step 3  ○  pending        (on failure → Rollback)
```

---

## File Map

| File | Action |
|------|--------|
| `backend/app/models/models.py` | Add `Workflow`, `WorkflowStep`, `WorkflowRun`, `WorkflowRunStep` models |
| `backend/app/schemas/workflows.py` | Pydantic schemas for request/response |
| `backend/app/api/v1/workflows.py` | CRUD + run endpoints |
| `backend/app/api/v1/router.py` | Register workflows router |
| `backend/app/worker/tasks/workflow_runner.py` | `run_workflow` Celery task |
| `backend/app/ws/workflow_runs.py` | WebSocket handler for run events |
| `backend/app/main.py` | Register new WebSocket route |
| `backend/alembic/versions/0003_add_workflow_tables.py` | DB migration |

---

## Out of Scope

- Scheduled / cron-triggered workflow runs
- Parallel step execution
- Step-level node override (all steps share the run's node list)
- Workflow versioning
