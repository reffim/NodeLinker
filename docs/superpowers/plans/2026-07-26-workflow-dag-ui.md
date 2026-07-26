# Workflow DAG UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace workflow step lists and accordion panels with an interactive React Flow DAG showing step sequence, failure branches, and per-node execution status chips.

**Architecture:** A single shared `WorkflowGraph` component renders React Flow nodes from `WorkflowStep[]`. In the definition view (WorkflowList) it renders a clean read-only DAG; in the run view (WorkflowRunMonitor) it overlays per-node status chips on each step card and wires clicks to the existing log panel. The WebSocket hook, log panel, API layer, and routing are untouched.

**Tech Stack:** `@xyflow/react` (React Flow v12), React 19, TypeScript ~6.0.2, Tailwind v3, Lucide icons

## Global Constraints

- All source files live under `/home/reffim/workspace/project_minerva/frontend/src/`
- All commands run from `/home/reffim/workspace/project_minerva/frontend/` unless stated otherwise
- Do not modify `src/types/index.ts`
- Do not add any dependency other than `@xyflow/react`
- TypeScript strict mode is on — `npx tsc --noEmit` must pass with zero errors after each task

---

### Task 1: Install @xyflow/react

**Files:**
- Modify: `package.json` (via npm install)

**Interfaces:**
- Produces: `@xyflow/react` importable in subsequent tasks

- [ ] **Step 1: Install the package**

```bash
cd /home/reffim/workspace/project_minerva/frontend
npm install @xyflow/react
```

Expected: `package.json` gains `"@xyflow/react"` in `dependencies`, no errors.

- [ ] **Step 2: Verify types are bundled**

```bash
ls node_modules/@xyflow/react/dist/esm/index.d.ts
```

Expected: file exists (no separate `@types/` package needed).

- [ ] **Step 3: Commit**

```bash
git add package.json package-lock.json
git commit -m "chore: add @xyflow/react dependency"
```

---

### Task 2: Create WorkflowGraph component

**Files:**
- Create: `src/components/WorkflowGraph.tsx`

**Interfaces:**
- Consumes: `WorkflowStep`, `WorkflowRunStep`, `Playbook`, `Node` from `@/types`
- Produces:
  ```ts
  export interface WorkflowGraphProps {
    steps: WorkflowStep[]
    playbookMap: Map<string, Playbook>
    runSteps?: WorkflowRunStep[]            // omit for definition view
    nodeMap?: Map<string, MinervaNode>      // MinervaNode = Node from @/types
    onStepClick?: (runStepId: string) => void  // WorkflowRunStep.id
    selectedRunStepId?: string                 // WorkflowRunStep.id
  }
  export function WorkflowGraph(props: WorkflowGraphProps): JSX.Element
  ```

- [ ] **Step 1: Create the file**

Create `src/components/WorkflowGraph.tsx` with the following content:

```tsx
import '@xyflow/react/dist/style.css'
import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  Position,
  type NodeProps,
  type Node as RFNode,
  type Edge,
} from '@xyflow/react'
import { CheckCircle, XCircle, Loader2, Minus, Circle } from 'lucide-react'
import type { WorkflowStep, WorkflowRunStep, Playbook, Node as MinervaNode } from '@/types'

type StepNodeData = {
  label: string
  order: number
  chips?: { runStepId: string; nodeName: string; status: WorkflowRunStep['status'] }[]
  onChipClick?: (runStepId: string) => void
  isSelected?: boolean
}

type StepRFNode = RFNode<StepNodeData, 'step'>

function ChipIcon({ status }: { status: WorkflowRunStep['status'] }) {
  switch (status) {
    case 'success': return <CheckCircle className="h-3 w-3 text-green-500" />
    case 'failed':  return <XCircle className="h-3 w-3 text-red-500" />
    case 'running': return <Loader2 className="h-3 w-3 text-yellow-500 animate-spin" />
    case 'skipped': return <Minus className="h-3 w-3 text-muted-foreground" />
    default:        return <Circle className="h-3 w-3 text-muted-foreground" />
  }
}

function StepNode({ data }: NodeProps<StepRFNode>) {
  return (
    <div
      className={`bg-card border rounded-md px-3 py-2 min-w-[180px] shadow-sm ${
        data.isSelected ? 'border-primary ring-1 ring-primary' : 'border-border'
      }`}
    >
      <Handle type="target" position={Position.Top} className="!bg-border" />
      <div className="text-xs text-muted-foreground">Step {data.order}</div>
      <div className="text-sm font-medium truncate max-w-[160px]">{data.label}</div>
      {data.chips && data.chips.length > 0 && (
        <>
          <div className="my-1.5 border-t border-border" />
          <div className="flex flex-wrap gap-1">
            {data.chips.map((chip) => (
              <button
                key={chip.runStepId}
                onClick={() => data.onChipClick?.(chip.runStepId)}
                className="flex items-center gap-1 text-xs bg-muted rounded px-1.5 py-0.5 hover:bg-accent transition-colors"
              >
                <ChipIcon status={chip.status} />
                <span className="max-w-[80px] truncate">{chip.nodeName}</span>
              </button>
            ))}
          </div>
        </>
      )}
      <Handle type="source" position={Position.Bottom} className="!bg-border" />
    </div>
  )
}

const nodeTypes = { step: StepNode }

export interface WorkflowGraphProps {
  steps: WorkflowStep[]
  playbookMap: Map<string, Playbook>
  runSteps?: WorkflowRunStep[]
  nodeMap?: Map<string, MinervaNode>
  onStepClick?: (runStepId: string) => void
  selectedRunStepId?: string
}

export function WorkflowGraph({
  steps,
  playbookMap,
  runSteps,
  nodeMap,
  onStepClick,
  selectedRunStepId,
}: WorkflowGraphProps) {
  const sorted = [...steps].sort((a, b) => a.order - b.order)

  const runStepsByWorkflowStep = new Map<string, WorkflowRunStep[]>()
  for (const rs of runSteps ?? []) {
    if (!runStepsByWorkflowStep.has(rs.workflow_step_id))
      runStepsByWorkflowStep.set(rs.workflow_step_id, [])
    runStepsByWorkflowStep.get(rs.workflow_step_id)!.push(rs)
  }

  const nodes: StepRFNode[] = sorted.map((step) => {
    const rss = runStepsByWorkflowStep.get(step.id) ?? []
    const chips = runSteps
      ? rss.map((rs) => ({
          runStepId: rs.id,
          nodeName: rs.node_id
            ? (nodeMap?.get(rs.node_id)?.name ?? rs.node_id.slice(0, 6))
            : 'unknown',
          status: rs.status,
        }))
      : undefined
    return {
      id: step.id,
      type: 'step' as const,
      position: { x: 0, y: step.order * 130 },
      data: {
        label: playbookMap.get(step.playbook_id)?.name ?? step.playbook_id.slice(0, 8),
        order: step.order,
        chips,
        onChipClick: onStepClick,
        isSelected: rss.some((rs) => rs.id === selectedRunStepId),
      },
    }
  })

  const edges: Edge[] = []
  for (let i = 0; i < sorted.length - 1; i++) {
    edges.push({
      id: `seq-${sorted[i].id}-${sorted[i + 1].id}`,
      source: sorted[i].id,
      target: sorted[i + 1].id,
      type: 'smoothstep',
    })
  }
  for (const step of sorted) {
    if (step.on_failure_step_id) {
      edges.push({
        id: `fail-${step.id}-${step.on_failure_step_id}`,
        source: step.id,
        target: step.on_failure_step_id,
        type: 'smoothstep',
        style: { stroke: '#ef4444', strokeDasharray: '5,5' },
        label: 'on failure',
        labelStyle: { fontSize: 10, fill: '#ef4444' },
      })
    }
  }

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      fitView
      fitViewOptions={{ padding: 0.2 }}
      minZoom={0.4}
      maxZoom={1.5}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={false}
    >
      <Background gap={16} size={1} />
      <Controls showInteractive={false} />
    </ReactFlow>
  )
}
```

- [ ] **Step 2: Type-check**

```bash
npx tsc --noEmit 2>&1 | grep -i "WorkflowGraph\|error"
```

Expected: zero errors. If `NodeProps<StepRFNode>` causes a type error (varies by @xyflow/react version), replace `NodeProps<StepRFNode>` with `NodeProps` and cast `data` as `StepNodeData` inside the function body: `const d = data as StepNodeData`.

- [ ] **Step 3: Commit**

```bash
git add src/components/WorkflowGraph.tsx
git commit -m "feat: add WorkflowGraph DAG component"
```

---

### Task 3: Integrate into WorkflowList (definition view)

**Files:**
- Modify: `src/pages/WorkflowList.tsx`

**Interfaces:**
- Consumes: `WorkflowGraph, WorkflowGraphProps` from `@/components/WorkflowGraph`

- [ ] **Step 1: Add import**

In `src/pages/WorkflowList.tsx`, add after the last import line:

```ts
import { WorkflowGraph } from '@/components/WorkflowGraph'
```

- [ ] **Step 2: Remove `stepOrderMap` (only used in the old Steps list)**

Find and delete this block (near line 358):

```ts
  const stepOrderMap = new Map(
    selectedWorkflow?.steps.map((s) => [s.id, s.order]) ?? [],
  )
```

- [ ] **Step 3: Replace the Steps section with the DAG**

Find the `{/* Steps */}` block and replace it entirely:

**Old:**
```tsx
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
```

**New:**
```tsx
            {/* Steps */}
            <div>
              <h2 className="text-sm font-semibold mb-2">Steps</h2>
              <div className="h-72 rounded-md border border-border overflow-hidden">
                <WorkflowGraph
                  steps={selectedWorkflow.steps}
                  playbookMap={playbookMap}
                />
              </div>
            </div>
```

- [ ] **Step 4: Type-check**

```bash
npx tsc --noEmit 2>&1 | grep -i "WorkflowList\|error"
```

Expected: zero errors.

- [ ] **Step 5: Commit**

```bash
git add src/pages/WorkflowList.tsx
git commit -m "feat: replace step list with DAG in WorkflowList"
```

---

### Task 4: Integrate into WorkflowRunMonitor (run view)

**Files:**
- Modify: `src/pages/WorkflowRunMonitor.tsx`

**Interfaces:**
- Consumes: `WorkflowGraph` from `@/components/WorkflowGraph`
- The existing `selectedStepId` state (type `string | null`) continues to drive the log panel on the right — unchanged.

- [ ] **Step 1: Update lucide import and add WorkflowGraph import**

**Old import line (line 4):**
```ts
import { ArrowLeft, ChevronDown, ChevronRight, Loader2, CheckCircle, XCircle, Minus, Circle } from 'lucide-react'
```

**New:**
```ts
import { ArrowLeft } from 'lucide-react'
```

Add after the last import:
```ts
import { WorkflowGraph } from '@/components/WorkflowGraph'
```

- [ ] **Step 2: Delete `StepStatusIcon` (only used by the accordion being removed)**

Delete these lines (approximately lines 26–39):
```tsx
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
```

- [ ] **Step 3: Delete `deriveNodeStatus` (only used by accordion)**

Delete these lines (approximately lines 41–46):
```ts
function deriveNodeStatus(steps: WorkflowRunStep[]): WorkflowRun['status'] {
  if (steps.some((s) => s.status === 'running')) return 'running'
  if (steps.some((s) => s.status === 'failed')) return 'failed'
  if (steps.every((s) => s.status === 'success' || s.status === 'skipped')) return 'success'
  return 'pending'
}
```

- [ ] **Step 4: Remove accordion state, helpers, and computed maps**

Inside `WorkflowRunMonitor()`, delete:

**expandedNodes state + toggleNode (approx lines 90–98):**
```ts
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set())

  const toggleNode = (nodeId: string) => {
    setExpandedNodes((prev) => {
      const next = new Set(prev)
      next.has(nodeId) ? next.delete(nodeId) : next.add(nodeId)
      return next
    })
  }
```

**stepOrderMap (approx line 102):**
```ts
  const stepOrderMap = new Map(workflow?.steps.map((s) => [s.id, s.order]) ?? [])
```

**stepsByNode map (approx lines 153–158):**
```ts
  const stepsByNode = new Map<string, WorkflowRunStep[]>()
  for (const step of displaySteps) {
    const nid = step.node_id ?? 'unknown'
    if (!stepsByNode.has(nid)) stepsByNode.set(nid, [])
    stepsByNode.get(nid)!.push(step)
  }
```

- [ ] **Step 5: Delete the auto-expand useEffect**

Delete this entire block (approx lines 114–122):
```ts
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

- [ ] **Step 6: Strip expandedNodes references from the auto-select useEffect**

**Old:**
```ts
  // Auto-select: running step while active; failed step (or first) once terminal
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

**New:**
```ts
  // Auto-select: running step while active; failed step (or first) once terminal
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

- [ ] **Step 7: Replace accordion JSX with WorkflowGraph**

In the JSX, find the `<div className="flex-1 overflow-y-auto">` block that contains the `Array.from(stepsByNode.entries()).map(...)` accordion and replace it:

**Old:**
```tsx
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

**New:**
```tsx
        <div className="flex-1 min-h-0">
          <WorkflowGraph
            steps={workflow?.steps ?? []}
            playbookMap={playbookMap}
            runSteps={displaySteps}
            nodeMap={nodeMap}
            onStepClick={setSelectedStepId}
            selectedRunStepId={selectedStepId ?? undefined}
          />
        </div>
```

- [ ] **Step 8: Type-check (zero errors required)**

```bash
npx tsc --noEmit
```

Expected: no output (zero errors). If there are unused-variable errors for removed code, verify the removals in steps 2–6 are complete.

- [ ] **Step 9: Commit**

```bash
git add src/pages/WorkflowRunMonitor.tsx
git commit -m "feat: replace accordion with DAG in WorkflowRunMonitor"
```
