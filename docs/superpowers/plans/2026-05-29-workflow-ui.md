# Workflow UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add workflow definition management and real-time run monitoring to the NodeLinker frontend.

**Architecture:** Two new pages (`WorkflowList`, `WorkflowRunMonitor`) follow the existing `JobMonitor` left-sidebar + right-panel split. `LogPanel` is extracted from `JobMonitor.tsx` into a shared component. A `useWorkflowRunWS` hook drives real-time step updates via WebSocket, mirroring the existing `useJobLogsWS` pattern.

**Tech Stack:** React 19, TypeScript 6, TanStack Query v5, React Router v6, Tailwind CSS, Lucide React, Axios

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `frontend/src/types/index.ts` | Modify | Append Workflow*, WorkflowRun* types |
| `frontend/src/api/workflows.ts` | Create | All workflow + run API functions |
| `frontend/src/components/LogPanel.tsx` | Create | Shared log viewer (extracted from JobMonitor) |
| `frontend/src/pages/JobMonitor.tsx` | Modify | Replace local LogPanel with shared import |
| `frontend/src/hooks/useWorkflowRunWS.ts` | Create | WebSocket hook for workflow run events |
| `frontend/src/pages/WorkflowList.tsx` | Create | List + detail panel + New/Run modals |
| `frontend/src/pages/WorkflowRunMonitor.tsx` | Create | Step progress + inline log viewer |
| `frontend/src/components/Layout.tsx` | Modify | Add Workflows nav item |
| `frontend/src/App.tsx` | Modify | Register new routes |

---

### Task 1: Add Workflow types

**Files:**
- Modify: `frontend/src/types/index.ts`

- [ ] **Step 1: Append Workflow types to `types/index.ts`**

Add after the existing `JobLog` interface:

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

- [ ] **Step 2: Verify type check passes**

```bash
cd frontend && npx tsc -b --noEmit
```

Expected: exits 0 with no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/index.ts
git commit -m "feat(workflow-ui): add Workflow* TypeScript types"
```

---

### Task 2: Create API layer

**Files:**
- Create: `frontend/src/api/workflows.ts`

- [ ] **Step 1: Create `frontend/src/api/workflows.ts`**

```typescript
import client from './client'
import type { Workflow, WorkflowCreate, WorkflowRun, WorkflowRunCreate } from '../types'

export async function listWorkflows(): Promise<Workflow[]> {
  const { data } = await client.get<Workflow[]>('/workflows')
  return data
}

export async function getWorkflow(id: string): Promise<Workflow> {
  const { data } = await client.get<Workflow>(`/workflows/${id}`)
  return data
}

export async function createWorkflow(payload: WorkflowCreate): Promise<Workflow> {
  const { data } = await client.post<Workflow>('/workflows', payload)
  return data
}

export async function deleteWorkflow(id: string): Promise<void> {
  await client.delete(`/workflows/${id}`)
}

export async function listWorkflowRuns(workflowId: string): Promise<WorkflowRun[]> {
  const { data } = await client.get<WorkflowRun[]>(`/workflows/${workflowId}/runs`)
  return data
}

export async function startWorkflowRun(
  workflowId: string,
  payload: WorkflowRunCreate,
): Promise<WorkflowRun> {
  const { data } = await client.post<WorkflowRun>(`/workflows/${workflowId}/runs`, payload)
  return data
}

export async function getWorkflowRun(runId: string): Promise<WorkflowRun> {
  const { data } = await client.get<WorkflowRun>(`/workflow-runs/${runId}`)
  return data
}

export async function cancelWorkflowRun(runId: string): Promise<WorkflowRun> {
  const { data } = await client.post<WorkflowRun>(`/workflow-runs/${runId}/cancel`)
  return data
}
```

- [ ] **Step 2: Verify type check passes**

```bash
cd frontend && npx tsc -b --noEmit
```

Expected: exits 0 with no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/workflows.ts
git commit -m "feat(workflow-ui): add workflows API layer"
```

---

### Task 3: Extract LogPanel to shared component

**Files:**
- Create: `frontend/src/components/LogPanel.tsx`
- Modify: `frontend/src/pages/JobMonitor.tsx`

- [ ] **Step 1: Create `frontend/src/components/LogPanel.tsx`**

```tsx
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getJob, getJobNodeLogsContent } from '@/api/jobs'
import { getPlaybook } from '@/api/playbooks'
import { listNodes } from '@/api/nodes'
import { useJobLogsWS } from '@/hooks/useJobLogsWS'
import { Badge } from '@/components/ui/badge'
import type { Job } from '@/types'

function jobStatusVariant(
  status: Job['status'],
): 'success' | 'destructive' | 'warning' | 'secondary' | 'outline' {
  switch (status) {
    case 'success': return 'success'
    case 'failed': return 'destructive'
    case 'running': return 'warning'
    case 'cancelled': return 'secondary'
    default: return 'outline'
  }
}

export function LogPanel({ jobId }: { jobId: string }) {
  const { lines, done, finalStatus } = useJobLogsWS(jobId)
  const { data: job } = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => getJob(jobId),
    enabled: !!jobId,
  })
  const { data: playbook } = useQuery({
    queryKey: ['playbook', job?.playbook_id],
    queryFn: () => getPlaybook(job!.playbook_id),
    enabled: !!job?.playbook_id,
  })
  const { data: allNodes = [] } = useQuery({
    queryKey: ['nodes'],
    queryFn: () => listNodes(),
  })
  const endRef = useRef<HTMLDivElement>(null)
  const [staticLines, setStaticLines] = useState<{ node_id: string; content: string }[]>([])
  const [loadingStatic, setLoadingStatic] = useState(false)
  const [staticLoaded, setStaticLoaded] = useState(false)

  useEffect(() => {
    if (job && (job.status === 'success' || job.status === 'failed' || job.status === 'cancelled')) {
      if (lines.length === 0 && !staticLoaded && !loadingStatic) {
        setLoadingStatic(true)
        const fetchAllLogs = async () => {
          let allLines: { node_id: string; content: string }[] = []
          for (const node of job.job_nodes) {
            try {
              const contents = await getJobNodeLogsContent(jobId, node.node_id)
              allLines = allLines.concat(contents.map((c) => ({ node_id: node.node_id, content: c })))
            } catch (e) {
              allLines.push({ node_id: node.node_id, content: `Failed to load logs: ${e}` })
            }
          }
          setStaticLines(allLines)
          setLoadingStatic(false)
          setStaticLoaded(true)
        }
        fetchAllLogs()
      }
    }
  }, [job?.status, lines.length, jobId, staticLoaded, loadingStatic])

  const displayLines = lines.length > 0 ? lines : staticLines

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [displayLines])

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-3 border-b border-border flex items-center gap-3">
        <span className="font-medium text-sm text-foreground">
          {playbook ? playbook.name : 'Job Logs'}
        </span>
        {job && <Badge variant={jobStatusVariant(job.status)}>{job.status}</Badge>}
        {done && finalStatus && (
          <span className="text-xs text-muted-foreground ml-auto">Completed: {finalStatus}</span>
        )}
      </div>

      {job && job.job_nodes.length > 0 && (
        <div className="px-4 py-2 border-b border-border flex gap-3 flex-wrap">
          {job.job_nodes.map((jn) => {
            const node = allNodes.find((n) => n.id === jn.node_id)
            return (
              <div
                key={jn.node_id}
                className="flex items-center gap-1.5 text-xs bg-muted/50 px-2 py-1 rounded"
              >
                <span className="font-medium text-foreground">
                  {node ? node.name : `${jn.node_id.slice(0, 8)}…`}
                </span>
                <Badge
                  variant={
                    jn.status === 'success'
                      ? 'success'
                      : jn.status === 'failed'
                      ? 'destructive'
                      : 'warning'
                  }
                  className="text-[10px] px-1 py-0 h-4"
                >
                  {jn.status}
                </Badge>
                {jn.exit_code !== null && (
                  <span className="text-muted-foreground">exit={jn.exit_code}</span>
                )}
              </div>
            )
          })}
        </div>
      )}

      <div className="flex-1 overflow-y-auto bg-gray-950 text-gray-100 font-mono text-xs p-4 space-y-0.5">
        {displayLines.length === 0 && !done && !loadingStatic && (
          <p className="text-gray-500">Waiting for output…</p>
        )}
        {displayLines.length === 0 && loadingStatic && (
          <p className="text-gray-500">Loading archived logs…</p>
        )}
        {displayLines.map((line, i) => (
          <div key={i} className="leading-5">
            {line.node_id && (
              <span className="text-gray-500 mr-2">[{line.node_id.slice(0, 8)}]</span>
            )}
            <span>{line.content}</span>
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Update `JobMonitor.tsx` to use the shared component**

In `frontend/src/pages/JobMonitor.tsx`:

1. Delete the `jobStatusVariant` function (lines 13–21) — keep a private copy only for the sidebar job list:

```tsx
function jobStatusVariant(status: Job['status']): 'success' | 'destructive' | 'warning' | 'secondary' | 'outline' {
  switch (status) {
    case 'success': return 'success'
    case 'failed': return 'destructive'
    case 'running': return 'warning'
    case 'cancelled': return 'secondary'
    default: return 'outline'
  }
}
```

2. Delete the entire `LogPanel` function (lines 106–206).

3. Add this import after the existing imports:

```tsx
import { LogPanel } from '@/components/LogPanel'
```

The `<LogPanel key={jobId} jobId={jobId} />` usage in the JSX stays unchanged.

- [ ] **Step 3: Verify type check**

```bash
cd frontend && npx tsc -b --noEmit
```

Expected: exits 0 with no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/LogPanel.tsx frontend/src/pages/JobMonitor.tsx
git commit -m "refactor: extract LogPanel to shared component"
```

---

### Task 4: Add routes and nav entry

**Files:**
- Modify: `frontend/src/components/Layout.tsx`
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/pages/WorkflowList.tsx` (stub)
- Create: `frontend/src/pages/WorkflowRunMonitor.tsx` (stub)

- [ ] **Step 1: Add Workflows nav item to `Layout.tsx`**

Update the lucide import:

```tsx
import { Server, BookOpen, Activity, LogOut, Lock, GitBranch } from 'lucide-react'
```

Add to `navItems` (after Jobs):

```tsx
const navItems = [
  { to: '/nodes', label: 'Nodes', icon: Server },
  { to: '/playbooks', label: 'Playbooks', icon: BookOpen },
  { to: '/groups', label: 'Groups', icon: Lock },
  { to: '/jobs', label: 'Jobs', icon: Activity },
  { to: '/workflows', label: 'Workflows', icon: GitBranch },
]
```

- [ ] **Step 2: Create stub pages so App.tsx can import them**

`frontend/src/pages/WorkflowList.tsx`:
```tsx
export default function WorkflowList() {
  return <div className="p-8 text-muted-foreground">Workflows — coming soon</div>
}
```

`frontend/src/pages/WorkflowRunMonitor.tsx`:
```tsx
export default function WorkflowRunMonitor() {
  return <div className="p-8 text-muted-foreground">Run monitor — coming soon</div>
}
```

- [ ] **Step 3: Register routes in `App.tsx`**

Add imports after existing page imports:

```tsx
import WorkflowList from '@/pages/WorkflowList'
import WorkflowRunMonitor from '@/pages/WorkflowRunMonitor'
```

Add routes inside the protected `<Route path="/">` block, after `jobs/:jobId`:

```tsx
<Route path="workflows" element={<WorkflowList />} />
<Route path="workflows/:workflowId" element={<WorkflowList />} />
<Route path="workflow-runs/:runId" element={<WorkflowRunMonitor />} />
```

- [ ] **Step 4: Verify type check**

```bash
cd frontend && npx tsc -b --noEmit
```

Expected: exits 0 with no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Layout.tsx frontend/src/App.tsx \
        frontend/src/pages/WorkflowList.tsx frontend/src/pages/WorkflowRunMonitor.tsx
git commit -m "feat(workflow-ui): add nav entry and routes"
```

---

### Task 5: Create `useWorkflowRunWS` hook

**Files:**
- Create: `frontend/src/hooks/useWorkflowRunWS.ts`

- [ ] **Step 1: Create `frontend/src/hooks/useWorkflowRunWS.ts`**

```typescript
import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { WorkflowRunStep } from '@/types'

const TERMINAL = new Set(['success', 'failed', 'cancelled'])

export function useWorkflowRunWS(
  runId: string | undefined,
  initialSteps: WorkflowRunStep[],
  initialRunStatus: string | undefined,
) {
  const [steps, setSteps] = useState<WorkflowRunStep[]>(initialSteps)
  const [runStatus, setRunStatus] = useState<string | null>(initialRunStatus ?? null)
  const [done, setDone] = useState(false)
  const [disconnected, setDisconnected] = useState(false)
  const queryClient = useQueryClient()
  const initializedRef = useRef(false)

  // Sync from REST data the first time it arrives (before any WS updates)
  useEffect(() => {
    if (initialSteps.length > 0 && !initializedRef.current) {
      setSteps(initialSteps)
      initializedRef.current = true
    }
  }, [initialSteps])

  useEffect(() => {
    if (!runId || TERMINAL.has(initialRunStatus ?? '')) return

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/workflow-runs/${runId}`)

    ws.onopen = () => setDisconnected(false)

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'step_started') {
          setSteps((prev) =>
            prev.map((s) =>
              s.id === msg.step_id ? { ...s, status: 'running', job_id: msg.job_id } : s,
            ),
          )
        } else if (msg.type === 'step_finished') {
          setSteps((prev) =>
            prev.map((s) =>
              s.id === msg.step_id ? { ...s, status: msg.status } : s,
            ),
          )
        } else if (msg.type === 'workflow_done') {
          setRunStatus(msg.status)
          setDone(true)
          queryClient.invalidateQueries({ queryKey: ['workflow-run', runId] })
          queryClient.invalidateQueries({ queryKey: ['workflow-runs'] })
        }
      } catch {
        // ignore malformed frames
      }
    }

    ws.onerror = () => {
      setDisconnected(true)
      ws.close()
    }

    ws.onclose = () => setDisconnected(true)

    return () => ws.close()
  }, [runId, initialRunStatus, queryClient])

  return { steps, runStatus, done, disconnected }
}
```

- [ ] **Step 2: Verify type check**

```bash
cd frontend && npx tsc -b --noEmit
```

Expected: exits 0 with no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useWorkflowRunWS.ts
git commit -m "feat(workflow-ui): add useWorkflowRunWS WebSocket hook"
```

---

### Task 6: Implement WorkflowList page

**Files:**
- Modify: `frontend/src/pages/WorkflowList.tsx`

Replace the stub with the full implementation.

- [ ] **Step 1: Write `frontend/src/pages/WorkflowList.tsx`**

```tsx
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { Plus, ChevronRight, Play, Trash2, GitBranch } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  listWorkflows, getWorkflow, createWorkflow, deleteWorkflow,
  listWorkflowRuns, startWorkflowRun,
} from '@/api/workflows'
import { listPlaybooks } from '@/api/playbooks'
import { listNodes } from '@/api/nodes'
import { useAuthStore } from '@/stores/auth'
import type { WorkflowCreate, WorkflowRun } from '@/types'

function runStatusVariant(
  status: WorkflowRun['status'],
): 'success' | 'destructive' | 'warning' | 'secondary' | 'outline' {
  switch (status) {
    case 'success': return 'success'
    case 'failed': return 'destructive'
    case 'running': return 'warning'
    case 'cancelled': return 'secondary'
    default: return 'outline'
  }
}

// ── New Workflow Modal ────────────────────────────────────────────────────────

type StepForm = { playbookId: string; onFailureIdx: number | '' }

function NewWorkflowModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient()
  const { data: playbooks = [] } = useQuery({ queryKey: ['playbooks'], queryFn: listPlaybooks })

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [steps, setSteps] = useState<StepForm[]>([{ playbookId: '', onFailureIdx: '' }])
  const [error, setError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: createWorkflow,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workflows'] })
      onClose()
    },
    onError: () => setError('Failed to create workflow. Please try again.'),
  })

  function addStep() {
    setSteps((prev) => [...prev, { playbookId: '', onFailureIdx: '' }])
  }

  function removeStep(i: number) {
    setSteps((prev) => {
      const next = prev.filter((_, idx) => idx !== i)
      return next.map((s) => ({
        ...s,
        onFailureIdx:
          s.onFailureIdx === i || (s.onFailureIdx !== '' && s.onFailureIdx >= next.length)
            ? ''
            : s.onFailureIdx,
      }))
    })
  }

  function updateStep(i: number, field: keyof StepForm, value: string | number | '') {
    setSteps((prev) => prev.map((s, idx) => (idx === i ? { ...s, [field]: value } : s)))
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim() || steps.some((s) => !s.playbookId)) return
    const payload: WorkflowCreate = {
      name: name.trim(),
      description: description.trim() || undefined,
      steps: steps.map((s, i) => ({
        order: i,
        playbook_id: s.playbookId,
        on_failure_step_order: s.onFailureIdx === '' ? null : s.onFailureIdx,
      })),
    }
    mutation.mutate(payload)
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-card border border-border rounded-lg w-full max-w-lg p-6 space-y-4 shadow-lg max-h-[90vh] overflow-y-auto">
        <h2 className="font-semibold text-lg">New Workflow</h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1">
            <label className="text-sm font-medium">Name</label>
            <input
              className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              placeholder="Deploy Pipeline"
            />
          </div>
          <div className="space-y-1">
            <label className="text-sm font-medium">Description</label>
            <textarea
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              placeholder="Optional description"
            />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-sm font-medium">Steps</label>
              <button
                type="button"
                onClick={addStep}
                className="text-xs text-primary hover:underline"
              >
                + Add step
              </button>
            </div>
            {steps.map((step, i) => (
              <div key={i} className="border border-border rounded-md p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-muted-foreground">Step {i}</span>
                  {steps.length > 1 && (
                    <button
                      type="button"
                      onClick={() => removeStep(i)}
                      className="text-xs text-destructive hover:underline"
                    >
                      Remove
                    </button>
                  )}
                </div>
                <select
                  className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm"
                  value={step.playbookId}
                  onChange={(e) => updateStep(i, 'playbookId', e.target.value)}
                  required
                >
                  <option value="">Select playbook…</option>
                  {playbooks.map((pb) => (
                    <option key={pb.id} value={pb.id}>{pb.name}</option>
                  ))}
                </select>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground whitespace-nowrap">
                    On failure →
                  </span>
                  <select
                    className="flex-1 h-8 rounded-md border border-input bg-background px-2 text-xs"
                    value={step.onFailureIdx === '' ? '' : String(step.onFailureIdx)}
                    onChange={(e) =>
                      updateStep(
                        i,
                        'onFailureIdx',
                        e.target.value === '' ? '' : Number(e.target.value),
                      )
                    }
                  >
                    <option value="">None (fail workflow)</option>
                    {steps.map((_, j) =>
                      j !== i ? (
                        <option key={j} value={j}>
                          Step {j}
                        </option>
                      ) : null,
                    )}
                  </select>
                </div>
              </div>
            ))}
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}

          <div className="flex gap-2 justify-end">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? 'Creating…' : 'Create'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Run Workflow Modal ────────────────────────────────────────────────────────

function RunWorkflowModal({
  workflowId,
  onClose,
}: {
  workflowId: string
  onClose: () => void
}) {
  const navigate = useNavigate()
  const { data: nodes = [] } = useQuery({ queryKey: ['nodes'], queryFn: listNodes })
  const [selectedNodes, setSelectedNodes] = useState<string[]>([])
  const [extraVarsText, setExtraVarsText] = useState('')
  const [extraVarsError, setExtraVarsError] = useState<string | null>(null)
  const [apiError, setApiError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: ({
      nodeIds,
      extraVars,
    }: {
      nodeIds: string[]
      extraVars?: Record<string, unknown>
    }) => startWorkflowRun(workflowId, { node_ids: nodeIds, extra_vars: extraVars }),
    onSuccess: (run) => {
      onClose()
      navigate(`/workflow-runs/${run.id}`)
    },
    onError: () => setApiError('Failed to start run. Please try again.'),
  })

  function toggleNode(id: string) {
    setSelectedNodes((prev) =>
      prev.includes(id) ? prev.filter((n) => n !== id) : [...prev, id],
    )
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setExtraVarsError(null)
    setApiError(null)
    let extraVars: Record<string, unknown> | undefined
    if (extraVarsText.trim()) {
      try {
        extraVars = JSON.parse(extraVarsText)
      } catch {
        setExtraVarsError('Invalid JSON')
        return
      }
    }
    if (selectedNodes.length === 0) return
    mutation.mutate({ nodeIds: selectedNodes, extraVars })
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-card border border-border rounded-lg w-full max-w-md p-6 space-y-4 shadow-lg">
        <h2 className="font-semibold text-lg">Run Workflow</h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1">
            <label className="text-sm font-medium">Target Nodes</label>
            <div className="border border-border rounded-md max-h-40 overflow-y-auto divide-y divide-border">
              {nodes.length === 0 ? (
                <p className="px-3 py-2 text-sm text-muted-foreground">No nodes available.</p>
              ) : (
                nodes.map((node) => (
                  <label
                    key={node.id}
                    className="flex items-center gap-2 px-3 py-2 hover:bg-accent cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={selectedNodes.includes(node.id)}
                      onChange={() => toggleNode(node.id)}
                    />
                    <span className="text-sm">{node.name}</span>
                    <Badge
                      variant={node.status === 'online' ? 'success' : 'secondary'}
                      className="ml-auto"
                    >
                      {node.status}
                    </Badge>
                  </label>
                ))
              )}
            </div>
          </div>
          <div className="space-y-1">
            <label className="text-sm font-medium">
              Extra Vars{' '}
              <span className="text-muted-foreground font-normal">(JSON, optional)</span>
            </label>
            <textarea
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono"
              value={extraVarsText}
              onChange={(e) => setExtraVarsText(e.target.value)}
              rows={3}
              placeholder='{"key": "value"}'
            />
            {extraVarsError && <p className="text-xs text-destructive">{extraVarsError}</p>}
          </div>
          {apiError && <p className="text-sm text-destructive">{apiError}</p>}
          <div className="flex gap-2 justify-end">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={mutation.isPending || selectedNodes.length === 0}
            >
              {mutation.isPending ? 'Launching…' : 'Run'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── WorkflowList Page ─────────────────────────────────────────────────────────

export default function WorkflowList() {
  const { workflowId } = useParams<{ workflowId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { user } = useAuthStore()

  const [showNewModal, setShowNewModal] = useState(false)
  const [showRunModal, setShowRunModal] = useState(false)

  const { data: workflows = [], isLoading } = useQuery({
    queryKey: ['workflows'],
    queryFn: listWorkflows,
  })

  const { data: selectedWorkflow } = useQuery({
    queryKey: ['workflow', workflowId],
    queryFn: () => getWorkflow(workflowId!),
    enabled: !!workflowId,
  })

  const { data: runs = [] } = useQuery({
    queryKey: ['workflow-runs', workflowId],
    queryFn: () => listWorkflowRuns(workflowId!),
    enabled: !!workflowId,
    refetchInterval: (query) =>
      query.state.data?.some((r) => r.status === 'pending' || r.status === 'running')
        ? 10_000
        : false,
  })

  const { data: playbooks = [] } = useQuery({
    queryKey: ['playbooks'],
    queryFn: listPlaybooks,
  })

  const deleteMutation = useMutation({
    mutationFn: deleteWorkflow,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workflows'] })
      navigate('/workflows')
    },
  })

  const playbookMap = new Map(playbooks.map((pb) => [pb.id, pb]))
  const stepOrderMap = new Map(
    selectedWorkflow?.steps.map((s) => [s.id, s.order]) ?? [],
  )

  function handleDelete() {
    if (!workflowId || !confirm(`Delete "${selectedWorkflow?.name}"? This cannot be undone.`))
      return
    deleteMutation.mutate(workflowId)
  }

  return (
    <div className="flex h-full">
      {/* Sidebar */}
      <div className="w-72 flex-shrink-0 border-r border-border flex flex-col">
        <div className="px-4 py-3 border-b border-border flex items-center justify-between">
          <span className="font-medium text-sm flex items-center gap-2">
            <GitBranch className="h-4 w-4" /> Workflows
          </span>
          <Button variant="ghost" size="sm" onClick={() => setShowNewModal(true)}>
            <Plus className="h-4 w-4 mr-1" /> New
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto divide-y divide-border">
          {isLoading ? (
            <p className="px-4 py-3 text-sm text-muted-foreground">Loading…</p>
          ) : workflows.length === 0 ? (
            <p className="px-4 py-3 text-sm text-muted-foreground">No workflows yet.</p>
          ) : (
            workflows.map((wf) => (
              <button
                key={wf.id}
                onClick={() => navigate(`/workflows/${wf.id}`)}
                className={`w-full text-left px-4 py-3 hover:bg-accent transition-colors flex items-center gap-2 ${
                  workflowId === wf.id ? 'bg-accent' : ''
                }`}
              >
                <ChevronRight className="h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate">{wf.name}</div>
                  <div className="text-xs text-muted-foreground">
                    {wf.steps.length} step{wf.steps.length !== 1 ? 's' : ''}
                  </div>
                </div>
              </button>
            ))
          )}
        </div>
      </div>

      {/* Detail panel */}
      <div className="flex-1 overflow-auto">
        {!workflowId ? (
          <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
            Select a workflow
          </div>
        ) : !selectedWorkflow ? (
          <div className="p-8 text-muted-foreground text-sm">Loading…</div>
        ) : (
          <div className="p-6 space-y-6 max-w-2xl">
            {/* Header */}
            <div className="flex items-start justify-between gap-4">
              <div>
                <h1 className="text-xl font-semibold">{selectedWorkflow.name}</h1>
                {selectedWorkflow.description && (
                  <p className="text-sm text-muted-foreground mt-1">
                    {selectedWorkflow.description}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <Button onClick={() => setShowRunModal(true)}>
                  <Play className="h-4 w-4 mr-1" /> Run Now
                </Button>
                {user?.role === 'admin' && (
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={handleDelete}
                    disabled={deleteMutation.isPending}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </div>

            {/* Steps */}
            <div>
              <h2 className="text-sm font-semibold mb-2">Steps</h2>
              <div className="border border-border rounded-md divide-y divide-border">
                {selectedWorkflow.steps
                  .slice()
                  .sort((a, b) => a.order - b.order)
                  .map((step) => {
                    const pb = playbookMap.get(step.playbook_id)
                    const failOrder =
                      step.on_failure_step_id
                        ? stepOrderMap.get(step.on_failure_step_id)
                        : undefined
                    return (
                      <div key={step.id} className="px-4 py-3 flex items-center gap-3">
                        <span className="text-xs font-mono text-muted-foreground w-12 flex-shrink-0">
                          Step {step.order}
                        </span>
                        <span className="flex-1 text-sm">
                          {pb?.name ?? step.playbook_id.slice(0, 8)}
                        </span>
                        {failOrder !== undefined && (
                          <span className="text-xs text-muted-foreground">
                            → Step {failOrder} on failure
                          </span>
                        )}
                      </div>
                    )
                  })}
              </div>
            </div>

            {/* Runs history */}
            <div>
              <h2 className="text-sm font-semibold mb-2">Runs</h2>
              {runs.length === 0 ? (
                <p className="text-sm text-muted-foreground">No runs yet.</p>
              ) : (
                <div className="border border-border rounded-md divide-y divide-border">
                  {runs.map((run) => (
                    <div key={run.id} className="px-4 py-3 flex items-center gap-3">
                      <Badge variant={runStatusVariant(run.status)}>{run.status}</Badge>
                      <span className="text-xs text-muted-foreground flex-1">
                        {new Date(run.created_at).toLocaleString()}
                      </span>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => navigate(`/workflow-runs/${run.id}`)}
                      >
                        View
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {showNewModal && <NewWorkflowModal onClose={() => setShowNewModal(false)} />}
      {showRunModal && workflowId && (
        <RunWorkflowModal workflowId={workflowId} onClose={() => setShowRunModal(false)} />
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify type check**

```bash
cd frontend && npx tsc -b --noEmit
```

Expected: exits 0 with no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/WorkflowList.tsx
git commit -m "feat(workflow-ui): implement WorkflowList page"
```

---

### Task 7: Implement WorkflowRunMonitor page

**Files:**
- Modify: `frontend/src/pages/WorkflowRunMonitor.tsx`

Replace the stub with the full implementation.

- [ ] **Step 1: Write `frontend/src/pages/WorkflowRunMonitor.tsx`**

```tsx
import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Loader2, CheckCircle, XCircle, Minus, Circle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { LogPanel } from '@/components/LogPanel'
import { getWorkflowRun, cancelWorkflowRun, getWorkflow } from '@/api/workflows'
import { listPlaybooks } from '@/api/playbooks'
import { useWorkflowRunWS } from '@/hooks/useWorkflowRunWS'
import type { WorkflowRun, WorkflowRunStep } from '@/types'

function runStatusVariant(
  status: WorkflowRun['status'],
): 'success' | 'destructive' | 'warning' | 'secondary' | 'outline' {
  switch (status) {
    case 'success': return 'success'
    case 'failed': return 'destructive'
    case 'running': return 'warning'
    case 'cancelled': return 'secondary'
    default: return 'outline'
  }
}

function StepStatusIcon({ status }: { status: WorkflowRunStep['status'] }) {
  switch (status) {
    case 'success':
      return <CheckCircle className="h-4 w-4 text-green-500 flex-shrink-0" />
    case 'failed':
      return <XCircle className="h-4 w-4 text-red-500 flex-shrink-0" />
    case 'running':
      return <Loader2 className="h-4 w-4 text-yellow-500 animate-spin flex-shrink-0" />
    case 'skipped':
      return <Minus className="h-4 w-4 text-muted-foreground flex-shrink-0" />
    default:
      return <Circle className="h-4 w-4 text-muted-foreground flex-shrink-0" />
  }
}

export default function WorkflowRunMonitor() {
  const { runId } = useParams<{ runId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data: run } = useQuery({
    queryKey: ['workflow-run', runId],
    queryFn: () => getWorkflowRun(runId!),
    enabled: !!runId,
  })

  const { data: workflow } = useQuery({
    queryKey: ['workflow', run?.workflow_id],
    queryFn: () => getWorkflow(run!.workflow_id),
    enabled: !!run?.workflow_id,
  })

  const { data: playbooks = [] } = useQuery({
    queryKey: ['playbooks'],
    queryFn: listPlaybooks,
  })

  const { steps, runStatus, done, disconnected } = useWorkflowRunWS(
    runId,
    run?.workflow_run_steps ?? [],
    run?.status,
  )

  const [selectedStepId, setSelectedStepId] = useState<string | null>(null)

  // Auto-select the running step; fall back to first step after data loads
  useEffect(() => {
    const running = steps.find((s) => s.status === 'running')
    if (running) {
      setSelectedStepId(running.id)
    } else if (!selectedStepId && steps.length > 0) {
      setSelectedStepId(steps[0].id)
    }
  }, [steps])

  const cancelMutation = useMutation({
    mutationFn: () => cancelWorkflowRun(runId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workflow-run', runId] })
      queryClient.invalidateQueries({ queryKey: ['workflow-runs'] })
    },
  })

  const playbookMap = new Map(playbooks.map((pb) => [pb.id, pb]))
  const stepDefMap = new Map(workflow?.steps.map((s) => [s.id, s]) ?? [])
  const stepOrderMap = new Map(workflow?.steps.map((s) => [s.id, s.order]) ?? [])

  const displayStatus = (runStatus ?? run?.status ?? 'pending') as WorkflowRun['status']
  const isActive = displayStatus === 'pending' || displayStatus === 'running'
  const selectedStep = steps.find((s) => s.id === selectedStepId) ?? null

  return (
    <div className="flex h-full">
      {/* Left panel — step list */}
      <div className="w-80 flex-shrink-0 border-r border-border flex flex-col">
        <div className="px-4 py-3 border-b border-border space-y-2">
          <button
            onClick={() => navigate(`/workflows/${run?.workflow_id ?? ''}`)}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> Back to workflow
          </button>
          <div className="flex items-center justify-between gap-2">
            <span className="font-medium text-sm truncate">{workflow?.name ?? '…'}</span>
            <Badge variant={runStatusVariant(displayStatus)}>{displayStatus}</Badge>
          </div>
          {isActive && (
            <Button
              variant="destructive"
              size="sm"
              className="w-full"
              onClick={() => cancelMutation.mutate()}
              disabled={cancelMutation.isPending}
            >
              {cancelMutation.isPending ? 'Cancelling…' : 'Cancel Run'}
            </Button>
          )}
          {done && (
            <p className="text-xs text-muted-foreground">Run complete.</p>
          )}
        </div>

        {disconnected && (
          <div className="px-4 py-2 text-xs text-muted-foreground bg-muted/50 border-b border-border">
            Disconnected — data may be stale
          </div>
        )}

        <div className="flex-1 overflow-y-auto divide-y divide-border">
          {steps.map((runStep) => {
            const stepDef = stepDefMap.get(runStep.workflow_step_id)
            const pb = stepDef ? playbookMap.get(stepDef.playbook_id) : undefined
            const failOrder =
              stepDef?.on_failure_step_id
                ? stepOrderMap.get(stepDef.on_failure_step_id)
                : undefined
            const stepOrder = stepDef?.order ?? 0
            return (
              <button
                key={runStep.id}
                onClick={() => setSelectedStepId(runStep.id)}
                className={`w-full text-left px-4 py-3 hover:bg-accent transition-colors flex items-start gap-3 ${
                  selectedStepId === runStep.id ? 'bg-accent' : ''
                }`}
              >
                <StepStatusIcon status={runStep.status} />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium">Step {stepOrder}</div>
                  <div className="text-xs text-muted-foreground truncate">
                    {pb?.name ?? 'Unknown playbook'}
                  </div>
                  {failOrder !== undefined && (
                    <div className="text-xs text-muted-foreground">
                      → Step {failOrder} on failure
                    </div>
                  )}
                </div>
              </button>
            )
          })}
        </div>

        {(run?.started_at || run?.finished_at) && (
          <div className="px-4 py-3 border-t border-border text-xs text-muted-foreground space-y-1">
            {run.started_at && (
              <div>Started: {new Date(run.started_at).toLocaleString()}</div>
            )}
            {run.finished_at && (
              <div>Finished: {new Date(run.finished_at).toLocaleString()}</div>
            )}
          </div>
        )}
      </div>

      {/* Right panel — log viewer */}
      <div className="flex-1 overflow-hidden">
        {!selectedStep ? (
          <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
            Select a step to view logs
          </div>
        ) : selectedStep.job_id ? (
          <LogPanel key={selectedStep.job_id} jobId={selectedStep.job_id} />
        ) : (
          <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
            No logs for this step.
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify type check**

```bash
cd frontend && npx tsc -b --noEmit
```

Expected: exits 0 with no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/WorkflowRunMonitor.tsx
git commit -m "feat(workflow-ui): implement WorkflowRunMonitor page"
```

---

### Task 8: Build verification and smoke test

**Files:** None (verification only)

- [ ] **Step 1: Full production build**

```bash
cd frontend && npm run build
```

Expected: exits 0 with no TypeScript or bundler errors.

- [ ] **Step 2: Manual smoke test**

Start the dev stack:

```bash
docker compose -f docker-compose.dev.yml up
```

Verify in the browser:

1. **Nav:** "Workflows" item appears in sidebar with GitBranch icon.
2. **Empty state:** `/workflows` shows "Select a workflow" in the right panel.
3. **Create:** Click "New" → modal opens. Add two steps; set Step 1 "On failure → Step 0". Submit → new workflow appears in list.
4. **Detail:** Click the workflow → right panel shows name, steps with `→ Step 0 on failure` label on Step 1, empty runs list, "Run Now" button.
5. **Run:** Click "Run Now" → node checklist appears. Select nodes, optionally enter `{"key":"val"}` in Extra Vars, click Run → redirected to `/workflow-runs/:runId`.
6. **Monitor:** Left panel shows all steps with pending/running/success icons updating live via WebSocket. Click a step with a job → right panel shows log output.
7. **Cancel:** "Cancel Run" button visible while active; clicking it cancels the run and the button disappears.
8. **Completion:** After run finishes, timestamps appear in the left panel footer. "Run complete." message shows.
9. **History:** Navigate back to `/workflows/:id` → run appears in Runs section with correct status badge. "View" link navigates back to run monitor (read-only).
10. **Regression:** Navigate to `/jobs` → Job Monitor still works; existing log streaming is unaffected.

- [ ] **Step 3: Commit any cleanup**

```bash
# Only if there are fixups from smoke testing
git add -p
git commit -m "fix(workflow-ui): post-smoke-test cleanup"
```
