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
