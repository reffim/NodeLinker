# Workflow DAG UI Design

**Date:** 2026-07-08  
**Status:** Approved

## Goal

Replace text-based workflow step lists and accordion panels with an interactive DAG (directed acyclic graph) visualization using React Flow. The graph shows step sequence and failure branches visually, with per-node execution status overlaid during runs.

## Scope

**Changed:**
- `frontend/src/pages/WorkflowList.tsx` — Steps section: numbered list → DAG
- `frontend/src/pages/WorkflowRunMonitor.tsx` — Left accordion panel → DAG with node chips
- `frontend/src/components/WorkflowGraph.tsx` (new) — shared DAG component

**Unchanged:**
- Right log panel (`LogPanel`)
- WebSocket hook (`useWorkflowRunWS`)
- API layer, routing, backend

**Dependency added:** `@xyflow/react`

## Component: WorkflowGraph

Single shared component used in both views.

```ts
interface WorkflowGraphProps {
  steps: WorkflowStep[]
  playbookMap: Map<string, Playbook>
  runSteps?: WorkflowRunStep[]        // run view only
  nodeMap?: Map<string, Node>         // run view only
  onStepClick?: (stepId: string) => void
  selectedStepId?: string
}
```

### Definition view (WorkflowList)

`runSteps` omitted → renders clean DAG, no interaction needed.

### Run view (WorkflowRunMonitor)

`runSteps` + `nodeMap` provided → each step card shows per-node status chips. `onStepClick` selects the step and updates the log panel.

Selected step: `selectedStepId` passed in, highlighted with a distinct border.

## Layout & Positioning

Manual positioning — no dagre needed for linear-ish workflows.

- Step `order` maps directly to Y: `y = order * 130`
- All steps centered: `x = 200`
- React Flow `fitView` handles zoom/pan

## Nodes

Each workflow step renders as a React Flow custom node card.

**Definition view card:**
```
┌────────────────────────┐
│  Step 0                │
│  Backup Database       │
└────────────────────────┘
```

**Run view card (node chips added):**
```
┌────────────────────────┐
│  Step 0                │
│  Backup Database       │
│  ─────────────────     │
│  [web-01]✓ [db-01]⟳   │
└────────────────────────┘
```

Chip colors match existing `runStatusVariant`: green (success), yellow (running), red (failed), gray (pending/skipped).

## Edges

| Type | Style | Condition |
|------|-------|-----------|
| Normal flow | Solid gray arrow | step[i] → step[i+1] sequentially |
| Failure branch | Red dashed arrow | `on_failure_step_id` is set |

## Per-node chip logic (run view)

`runSteps` contains one entry per (workflow_step, node) combination. Group by `workflow_step_id`, then display each node's status as a chip inside the step card.

Chip label: node name (from `nodeMap`). Falls back to `node_id.slice(0, 6)` if node not found.

## WorkflowRunMonitor layout change

Left panel stays at `w-80` with the DAG replacing the accordion. React Flow `fitView` + `minZoom`/`maxZoom` constraints keep the graph readable within the panel width.

Right log panel unchanged.

## Assumptions

- Max ~3 nodes per run (confirmed by user) — chip layout stays readable
- Workflow steps are rarely more than ~10 — manual Y positioning is sufficient
- No step editing in this iteration (definition is read-only in the graph)
