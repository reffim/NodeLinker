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
