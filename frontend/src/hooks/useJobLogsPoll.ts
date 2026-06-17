import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { getJobLogChunks } from '@/api/jobs'
import type { Job } from '@/types'

interface LogLine {
  node_id: string
  content: string
}

const TERMINAL = new Set(['success', 'failed', 'cancelled'])

export function useJobLogsPoll(jobId: string | undefined): { lines: LogLine[] } {
  const [lines, setLines] = useState<LogLine[]>([])
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!jobId) return

    setLines([])

    let lastId = 0
    let active = true

    const poll = async () => {
      if (!active) return
      try {
        const chunks = await getJobLogChunks(jobId, lastId)
        if (!active) return
        if (chunks.length > 0) {
          lastId = chunks[chunks.length - 1].id
          setLines((prev) => [
            ...prev,
            ...chunks.flatMap((c) =>
              c.content.split('\n').filter(Boolean).map((line) => ({
                node_id: c.node_id,
                content: line,
              }))
            ),
          ])
          return
        }
        // Empty poll — stop if job is terminal (all chunks already received)
        const job = queryClient.getQueryData<Job>(['job', jobId])
        if (job && TERMINAL.has(job.status)) {
          active = false
        }
      } catch {
        // keep polling on transient errors
      }
    }

    poll()
    const id = setInterval(poll, 2000)
    return () => {
      active = false
      clearInterval(id)
    }
  }, [jobId, queryClient])

  return { lines }
}
