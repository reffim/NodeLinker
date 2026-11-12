import { useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { WorkflowRunStep } from '@/types'

const TERMINAL = new Set(['success', 'failed', 'cancelled'])

// Step status progression: pending → running → (success | failed | skipped)
const STEP_RANK: Record<WorkflowRunStep['status'], number> = {
  pending: 0,
  running: 1,
  success: 2,
  failed: 2,
  skipped: 2,
}

type StepPatch = Partial<Pick<WorkflowRunStep, 'status' | 'job_id'>>

export function useWorkflowRunWS(
  runId: string | undefined,
  initialSteps: WorkflowRunStep[],
  initialRunStatus: string | undefined,
) {
  // Only WS-driven changes live in state; REST data (initialSteps) is refreshed by
  // react-query and merged at render time. Redis pub/sub drops events published
  // while no client is subscribed, so WS alone can miss a step_started (no job_id)
  // or step_finished (step stuck in 'running') — REST fills those gaps.
  const [wsPatches, setWsPatches] = useState<Record<string, StepPatch>>({})
  const [runStatus, setRunStatus] = useState<string | null>(initialRunStatus ?? null)
  const [done, setDone] = useState(() => TERMINAL.has(initialRunStatus ?? ''))
  const [disconnected, setDisconnected] = useState(false)
  const queryClient = useQueryClient()

  // For each step, keep whichever source has progressed further
  const steps = useMemo(
    () =>
      initialSteps.map((rest) => {
        const ws = wsPatches[rest.id]
        if (!ws) return rest
        const status =
          ws.status && STEP_RANK[ws.status] > STEP_RANK[rest.status] ? ws.status : rest.status
        return { ...rest, status, job_id: rest.job_id ?? ws.job_id ?? null }
      }),
    [initialSteps, wsPatches],
  )

  useEffect(() => {
    if (!runId || TERMINAL.has(initialRunStatus ?? '')) return

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/workflow-runs/${runId}`)

    ws.onopen = () => setDisconnected(false)

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'step_started') {
          setWsPatches((prev) => ({
            ...prev,
            [msg.step_id]: { ...prev[msg.step_id], status: 'running', job_id: msg.job_id },
          }))
        } else if (msg.type === 'step_finished') {
          setWsPatches((prev) => ({
            ...prev,
            [msg.step_id]: { ...prev[msg.step_id], status: msg.status },
          }))
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
