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
