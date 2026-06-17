# Workflow UI Design

**Date:** 2026-05-25
**Project:** NodeLinker (project_minerva)
**Branch:** feature/workflow
**Status:** Approved

---

## Summary

Add a Workflow UI to the frontend covering two capabilities: workflow definition management (list, create, delete) and real-time run monitoring with inline job logs. A single "Workflows" sidebar entry routes to both views.

---

## Routing & Navigation

**New routes:**

| Path | Component | Description |
|------|-----------|-------------|
| `/workflows` | `WorkflowList` | Workflow list, no selection |
| `/workflows/:workflowId` | `WorkflowList` | Workflow list + right-panel detail |
| `/workflow-runs/:runId` | `WorkflowRunMonitor` | Run monitor with step list + inline logs |

**Layout.tsx changes:**
- Add `{ to: '/workflows', label: 'Workflows', icon: GitBranch }` to `navItems`, below Jobs.

---

## New Files

| File | Purpose |
|------|---------|
| `frontend/src/api/workflows.ts` | API functions: CRUD + runs |
| `frontend/src/hooks/useWorkflowRunWS.ts` | WebSocket hook for run events |
| `frontend/src/components/LogPanel.tsx` | Extracted from `JobMonitor.tsx` (currently a local function) |
| `frontend/src/pages/WorkflowList.tsx` | `/workflows` and `/workflows/:id` |
| `frontend/src/pages/WorkflowRunMonitor.tsx` | `/workflow-runs/:runId` |

**Modified files:**

| File | Change |
|------|--------|
| `frontend/src/types/index.ts` | Add `Workflow*` types |
| `frontend/src/App.tsx` | Register new routes |
| `frontend/src/components/Layout.tsx` | Add Workflows nav item |
| `frontend/src/pages/JobMonitor.tsx` | Remove local `LogPanel` function, import from `components/LogPanel` |

---

## Types

Appended to `src/types/index.ts`:

```typescript
export interface WorkflowStep {
  id: string
  workflow_id: string
  order: number
  playbook_id: string
  on_failure_step_id: string | null
}

export interface Workflow {
  id: string
  name: string
  description: string | null
  created_at: string
  updated_at: string
  steps: WorkflowStep[]
}

export interface WorkflowCreate {
  name: string
  description?: string
  steps: {
    order: number
    playbook_id: string
    on_failure_step_order: number | null
  }[]
}

export interface WorkflowRunStep {
  id: string
  workflow_run_id: string
  workflow_step_id: string
  job_id: string | null
  status: 'pending' | 'running' | 'success' | 'failed' | 'skipped'
  started_at: string | null
  finished_at: string | null
}

export interface WorkflowRun {
  id: string
  workflow_id: string
  status: 'pending' | 'running' | 'success' | 'failed' | 'cancelled'
  created_by: string | null
  node_ids: string[]
  extra_vars: Record<string, unknown> | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  workflow_run_steps: WorkflowRunStep[]
}

export interface WorkflowRunCreate {
  node_ids: string[]
  extra_vars?: Record<string, unknown>
}
```

---

## API Layer (`src/api/workflows.ts`)

```typescript
listWorkflows(): Promise<Workflow[]>          // GET /api/v1/workflows
getWorkflow(id): Promise<Workflow>            // GET /api/v1/workflows/:id
createWorkflow(payload): Promise<Workflow>   // POST /api/v1/workflows
deleteWorkflow(id): Promise<void>            // DELETE /api/v1/workflows/:id

listWorkflowRuns(workflowId): Promise<WorkflowRun[]>     // GET /api/v1/workflows/:id/runs
startWorkflowRun(workflowId, payload): Promise<WorkflowRun>  // POST /api/v1/workflows/:id/runs
getWorkflowRun(runId): Promise<WorkflowRun>              // GET /api/v1/workflow-runs/:runId
cancelWorkflowRun(runId): Promise<WorkflowRun>           // POST /api/v1/workflow-runs/:runId/cancel
```

---

## WebSocket Hook (`src/hooks/useWorkflowRunWS.ts`)

Connects to `/ws/workflow-runs/:runId`. Handles three event types from the backend:

- `step_started` — `{ type, step_id, job_id, order }` → update that step's status to `running`, set its `job_id`
- `step_finished` — `{ type, step_id, status }` → update that step's status
- `workflow_done` — `{ type, status }` → update run status, invalidate react-query caches

**Interface:**
```typescript
useWorkflowRunWS(runId: string | undefined, initialSteps: WorkflowRunStep[]): {
  steps: WorkflowRunStep[]   // merged: initial data + WS updates
  runStatus: string | null   // updated by workflow_done
  done: boolean
}
```

Initialises `steps` from `initialSteps` prop (REST data). Merges WS updates on top. When `runId` is undefined or run is already terminal, the hook is a no-op and returns the initial data unchanged.

---

## WorkflowList Page (`/workflows`, `/workflows/:workflowId`)

**Layout:** Same left-sidebar + right-panel split as `JobMonitor`.

### Left sidebar (w-72)

- Header: "Workflows" label + "New" button (opens create modal)
- List: one row per workflow
  - Name (truncated)
  - Step count badge (`N steps`)
- Active item highlighted (`bg-accent`)
- Click → navigate to `/workflows/:workflowId`

### Right panel — Workflow detail

Shown when a workflow is selected.

**Header section:**
- Workflow name + description
- Delete button (visible to admin role only) with confirmation

**Steps section:**
- Ordered list of steps (by `order`)
- Each row: `Step N`, playbook name, optional `→ Step M (on failure)` label resolved from `on_failure_step_id`

**Runs history section:**
- `GET /api/v1/workflows/:id/runs` — list of past and active runs, most recent first
- Each row: status Badge, `created_at` formatted datetime, "View" button → `/workflow-runs/:runId`
- Polling: `refetchInterval: 10_000` while any run is in `pending | running` state

**"Run Now" button:**
- Opens `RunWorkflowModal`
- Node multi-select (same checkbox list pattern as `RunJobModal` in `JobMonitor`)
- Optional `extra_vars` textarea (JSON, validated client-side before submit)
- On success → navigate to `/workflow-runs/:runId`

### "New Workflow" modal

Fields:
- Name (required, text input)
- Description (optional, textarea)
- Steps (dynamic list, minimum 1):
  - Each step: playbook select + "On failure" select
  - "On failure" options: "None (fail workflow)" + each other step in the list by its display index
  - Add/remove step buttons; order = list index (0-based, auto-assigned on submit)
- Submit → `POST /api/v1/workflows` → invalidate `['workflows']` list → close modal

---

## WorkflowRunMonitor Page (`/workflow-runs/:runId`)

**Layout:** Left panel (step list) + right panel (log viewer).

### Left panel (w-80)

**Header:**
- Back link → `/workflows/:workflowId`
- Workflow name + run status Badge
- "Cancel" button — visible only when status is `pending | running`; calls `cancelWorkflowRun(runId)`

**Step list:**

Each row shows:
- Step index + playbook name
- Status indicator:
  - `pending` → `○`
  - `running` → spinner icon (animated)
  - `success` → `✅`
  - `failed` → `✗` (destructive color)
  - `skipped` → `—` (muted color)
- Fallback label: `→ Step N` if `on_failure_step_id` is set (resolved from workflow definition)
- Click → select step → right panel shows that step's logs

**Auto-selection:** When a `step_started` WS event arrives, automatically switch the selected step to the newly running one.

**Footer:** `started_at` and `finished_at` timestamps.

### Right panel (log viewer)

Uses `LogPanel` extracted to `src/components/LogPanel.tsx`.

- Selected step has a `job_id` → render `<LogPanel jobId={step.job_id} />`
- Selected step has no `job_id` (pending or skipped) → render "No logs for this step."

### Data loading

On mount:
1. `GET /api/v1/workflow-runs/:runId` → load run + steps (initial state)
2. `GET /api/v1/workflows/:workflowId` → load workflow definition (for step names + fallback labels)
3. Start `useWorkflowRunWS` hook with the loaded steps

If run is already terminal on mount, the WS hook is a no-op and the page is read-only.

---

## Error Handling

- API errors display an inline error message below the relevant form or panel.
- WS disconnection on the run monitor page: show a muted "Disconnected — data may be stale" banner; do not crash the page.
- Invalid JSON in extra_vars field: client-side validation error before submit.

---

## Out of Scope

- Editing existing workflow steps (update is name/description only, per backend API)
- Workflow run re-run (would require a new run with the same params)
- Pagination on runs history list
- extra_vars display in runs history
