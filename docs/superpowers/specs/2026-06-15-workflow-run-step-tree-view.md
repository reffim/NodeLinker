# Workflow Run Step Tree View Design

**Date:** 2026-06-15
**Project:** NodeLinker (project_minerva)
**Branch:** feature/workflow
**Status:** Approved

---

## Summary

Replace the flat step list in `WorkflowRunMonitor`'s left panel with a collapsible node-grouped accordion. Steps are nested under their node header. Only `WorkflowRunMonitor.tsx` is modified.

---

## Layout

### Node Header Row

Clicking the header toggles the node's expand/collapse state.

```
▼ test-node-01                    ●running
▼ test-node-02                    ✅success
▶ test-node-03                    ○pending
```

**Left side:** `▼` or `▶` chevron + node name (from `nodeMap`; falls back to `node_id.slice(0, 8)` if not found)

**Right side:** Summary status badge derived from all steps under that node:
- Any step `running` → `running` (warning)
- Any step `failed`, none `running` → `failed` (destructive)
- All steps `success` or `skipped` → `success`
- Otherwise → `pending` (outline)

### Step Row (indented, visible only when node is expanded)

Same content as the current flat step row, with left padding added and the node name line removed (it's now in the header).

```
    ⟳ Step 1  deploy-playbook
    ✅ Step 2  verify-playbook
         → Step 3 on failure
    ○  Step 3  rollback-playbook  (skipped)
```

Clicking a step row selects it and shows its logs in the right panel. Selected step gets `bg-accent` highlight, same as today.

---

## State

### New state: `expandedNodes`

```typescript
const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set())
```

Initialized empty. A `useEffect` on `displaySteps` adds any node_id not yet in the set (so newly appearing nodes default to expanded, while user-collapsed nodes stay collapsed):

```typescript
useEffect(() => {
  setExpandedNodes((prev) => {
    const next = new Set(prev)
    for (const s of displaySteps) {
      if (s.node_id && !next.has(s.node_id)) next.add(s.node_id)
    }
    return next
  })
}, [displaySteps])

Toggle handler:
```typescript
const toggleNode = (nodeId: string) => {
  setExpandedNodes((prev) => {
    const next = new Set(prev)
    next.has(nodeId) ? next.delete(nodeId) : next.add(nodeId)
    return next
  })
}
```

### Grouping

`displaySteps` is grouped by `node_id` in the order they first appear. Within each group, steps are ordered by `stepOrderMap` (workflow step order).

```typescript
const stepsByNode: Map<string, WorkflowRunStep[]> = new Map()
for (const step of displaySteps) {
  const nid = step.node_id ?? 'unknown'
  if (!stepsByNode.has(nid)) stepsByNode.set(nid, [])
  stepsByNode.get(nid)!.push(step)
}
```

---

## Auto-Expand Behavior

When a running step is detected (via `useEffect` on `displaySteps`), the node containing that step is added to `expandedNodes` before auto-selecting the step. This ensures the selected step is always visible.

---

## Node Order

Nodes appear in the order their first step appears in `displaySteps` (which reflects workflow step order × node order from the run).

---

## Failure Banner

The existing "Step N failed: playbook — see logs below" banner above the step list is unchanged.

---

## Out of Scope

- Drag-to-reorder nodes or steps
- Filtering steps by status
- Showing node online/offline status in the header (only step-derived status)
- Persisting expand/collapse state across page reloads
