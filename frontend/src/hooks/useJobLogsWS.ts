import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

interface LogLine {
  line_number: number
  content: string
  node_id: string | null
}

interface UseJobLogsWSResult {
  lines: LogLine[]
  done: boolean
  finalStatus: string | null
}

/**
 * Streams real-time log lines for a job via /ws/jobs/{jobId}.
 * Replays historical logs first, then delivers live lines.
 * Returns all lines, a done flag, and the final job status.
 */
export function useJobLogsWS(jobId: string | undefined): UseJobLogsWSResult {
  const [lines, setLines] = useState<LogLine[]>([])
  const [done, setDone] = useState(false)
  const [finalStatus, setFinalStatus] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const seenRef = useRef(new Set<number>())

  useEffect(() => {
    if (!jobId) return

    setLines([])
    setDone(false)
    setFinalStatus(null)
    seenRef.current = new Set()

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/jobs/${jobId}`)

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'log') {
          const key = msg.line_number
          if (!seenRef.current.has(key)) {
            seenRef.current.add(key)
            setLines((prev) => [
              ...prev,
              { line_number: msg.line_number, content: msg.content, node_id: msg.node_id ?? null },
            ])
          }
        } else if (msg.type === 'done') {
          setDone(true)
          setFinalStatus(msg.status)
          // Invalidate so job list reflects new status
          queryClient.invalidateQueries({ queryKey: ['jobs'] })
          queryClient.invalidateQueries({ queryKey: ['job', jobId] })
        }
      } catch {
        // ignore malformed frames
      }
    }

    ws.onerror = () => ws.close()

    return () => {
      ws.close()
    }
  }, [jobId, queryClient])

  return { lines, done, finalStatus }
}
