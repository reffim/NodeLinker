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
