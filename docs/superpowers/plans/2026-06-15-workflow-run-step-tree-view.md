# Workflow Run Step Tree View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat step list in WorkflowRunMonitor's left panel with a collapsible node-grouped accordion.

**Architecture:** Group `displaySteps` by `node_id`, render each group under a toggle-able node header. Add `expandedNodes: Set<string>` state that starts empty and auto-populates (so new nodes default to expanded while user-collapsed nodes stay collapsed). A helper `deriveNodeStatus` shows the worst status across a node's steps.

**Tech Stack:** React 19, TypeScript, lucide-react, Tailwind CSS

---

## File Map

| Action | Path |
|--------|------|
| Modify | `frontend/src/pages/WorkflowRunMonitor.tsx` |

---

## Task 1: Add Imports, State, Helpers, and Grouping

**Files:**
- Modify: `frontend/src/pages/WorkflowRunMonitor.tsx`

Current imports from lucide-react (line 4):
```typescript
import { ArrowLeft, Loader2, CheckCircle, XCircle, Minus, Circle } from 'lucide-react'
```

- [ ] **Step 1: Add `ChevronDown` and `ChevronRight` to lucide-react import**

Replace line 4 with:
```typescript
import { ArrowLeft, ChevronDown, ChevronRight, Loader2, CheckCircle, XCircle, Minus, Circle } from 'lucide-react'
```

- [ ] **Step 2: Add `deriveNodeStatus` helper above the `WorkflowRunMonitor` component**

The component starts at line 41 (`export default function WorkflowRunMonitor()`). Add this function just before it:

```typescript
function deriveNodeStatus(steps: WorkflowRunStep[]): WorkflowRun['status'] {
  if (steps.some((s) => s.status === 'running')) return 'running'
  if (steps.some((s) => s.status === 'failed')) return 'failed'
  if (steps.every((s) => s.status === 'success' || s.status === 'skipped')) return 'success'
  return 'pending'
}
```

- [ ] **Step 3: Add `expandedNodes` state and `toggleNode` handler inside the component**

After the existing state declarations (currently after line 81 `const [cancelError, setCancelError] = useState<string | null>(null)`), add:

```typescript
const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set())

const toggleNode = (nodeId: string) => {
  setExpandedNodes((prev) => {
    const next = new Set(prev)
    next.has(nodeId) ? next.delete(nodeId) : next.add(nodeId)
    return next
  })
}
```

- [ ] **Step 4: Add `useEffect` to auto-expand new nodes**

`displaySteps` is computed around line 94 (after `wsStepsMissed` and before the auto-select `useEffect`). The auto-expand effect must go AFTER `displaySteps` is defined. Place it immediately before the existing auto-select `useEffect`:

```typescript
// Auto-expand: any node_id not yet in set gets added (defaults to expanded)
useEffect(() => {
  setExpandedNodes((prev) => {
    const next = new Set(prev)
    for (const s of displaySteps) {
      if (s.node_id && !next.has(s.node_id)) next.add(s.node_id)
    }
    return next
  })
}, [displaySteps])
```

- [ ] **Step 5: Add `stepsByNode` grouping computation**

After the existing derived variables (after `const selectedStep = ...`), add:

```typescript
const stepsByNode = new Map<string, WorkflowRunStep[]>()
for (const step of displaySteps) {
  const nid = step.node_id ?? 'unknown'
  if (!stepsByNode.has(nid)) stepsByNode.set(nid, [])
  stepsByNode.get(nid)!.push(step)
}
```

- [ ] **Step 6: Update the auto-select `useEffect` to also expand the target node**

The current auto-select effect (lines 97–105) is:
```typescript
useEffect(() => {
  const running = displaySteps.find((s) => s.status === 'running')
  if (running) {
    setSelectedStepId(running.id)
  } else if (!selectedStepId && displaySteps.length > 0) {
    const failed = displaySteps.find((s) => s.status === 'failed')
    setSelectedStepId((failed ?? displaySteps[0]).id)
  }
}, [displaySteps, selectedStepId])
```

Replace it with:
```typescript
useEffect(() => {
  const running = displaySteps.find((s) => s.status === 'running')
  if (running) {
    setSelectedStepId(running.id)
    if (running.node_id) {
      setExpandedNodes((prev) => new Set([...prev, running.node_id!]))
    }
  } else if (!selectedStepId && displaySteps.length > 0) {
    const failed = displaySteps.find((s) => s.status === 'failed')
    const target = failed ?? displaySteps[0]
    setSelectedStepId(target.id)
    if (target.node_id) {
      setExpandedNodes((prev) => new Set([...prev, target.node_id!]))
    }
  }
}, [displaySteps, selectedStepId])
```

- [ ] **Step 7: TypeScript check**

```bash
cd /home/reffim/workspace/project_minerva/frontend && npx tsc -b --noEmit 2>&1
```

Expected: no output (no errors). If there are type errors, fix them before committing.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/WorkflowRunMonitor.tsx
git commit -m "feat: add node grouping state and helpers to WorkflowRunMonitor"
```

---

## Task 2: Replace Flat Step List with Accordion Rendering

**Files:**
- Modify: `frontend/src/pages/WorkflowRunMonitor.tsx`

The current flat step list (lines 168–203) is:
```typescript
<div className="flex-1 overflow-y-auto divide-y divide-border">
  {displaySteps.map((runStep) => {
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
          <div className="text-xs text-muted-foreground">
            {runStep.node_id ? (nodeMap.get(runStep.node_id)?.name ?? runStep.node_id.slice(0, 8)) : ''}
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
```

- [ ] **Step 1: Replace the flat list with the accordion**

Replace the entire block above with:

```typescript
<div className="flex-1 overflow-y-auto">
  {Array.from(stepsByNode.entries()).map(([nodeId, nodeSteps]) => {
    const node = nodeMap.get(nodeId)
    const isExpanded = expandedNodes.has(nodeId)
    const nodeSummary = deriveNodeStatus(nodeSteps)
    return (
      <div key={nodeId} className="border-b border-border">
        <button
          onClick={() => toggleNode(nodeId)}
          className="w-full text-left px-4 py-2.5 flex items-center gap-2 bg-muted/30 hover:bg-muted/50 transition-colors"
        >
          {isExpanded
            ? <ChevronDown className="h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" />
            : <ChevronRight className="h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" />
          }
          <span className="text-sm font-medium flex-1 truncate">
            {node?.name ?? nodeId.slice(0, 8)}
          </span>
          <Badge variant={runStatusVariant(nodeSummary)} className="text-[10px]">
            {nodeSummary}
          </Badge>
        </button>
        {isExpanded && nodeSteps.map((runStep) => {
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
              className={`w-full text-left pl-8 pr-4 py-2.5 hover:bg-accent transition-colors flex items-start gap-3 border-t border-border/50 ${
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
    )
  })}
</div>
```

- [ ] **Step 2: TypeScript check — must be clean**

```bash
cd /home/reffim/workspace/project_minerva/frontend && npx tsc -b --noEmit 2>&1
```

Expected: no output. Fix any errors before continuing.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/WorkflowRunMonitor.tsx
git commit -m "feat: replace flat step list with node-grouped accordion in WorkflowRunMonitor"
```

---

## Task 3: Rebuild nginx and Visual Verification

- [ ] **Step 1: Rebuild nginx with new frontend**

```bash
docker compose -f /home/reffim/workspace/project_minerva/docker-compose.yml \
  -f /home/reffim/workspace/project_minerva/docker-compose.dev.yml \
  build --no-cache nginx 2>&1 | tail -6
```

Expected: ends with `nodelinker-nginx Built`

```bash
docker compose -f /home/reffim/workspace/project_minerva/docker-compose.yml \
  -f /home/reffim/workspace/project_minerva/docker-compose.dev.yml \
  up -d nginx 2>&1 | tail -3
```

Expected: `nodelinker-nginx-1  Started`

- [ ] **Step 2: Hard refresh browser and run a workflow**

1. Open `http://localhost:8888`, press `Ctrl+Shift+R` (hard refresh)
2. Navigate to Workflows → select a workflow → Run Now → select 2+ nodes → confirm
3. Open the workflow run monitor
4. Verify: steps are grouped under node headers (`▼ test-node-01`, `▼ test-node-02`)
5. Verify: node header shows summary status badge (running/success/failed/pending)
6. Verify: clicking a node header collapses/expands its steps
7. Verify: clicking a step still shows its logs on the right panel
8. Verify: auto-selection works — running step is auto-selected and its node stays expanded

- [ ] **Step 3: Final commit (if any cleanup needed)**

```bash
git status
# If clean, nothing to do. If there are tweaks, commit them.
```
