import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getJob, getJobNodeLogsContent } from '@/api/jobs'
import { getPlaybook } from '@/api/playbooks'
import { listNodes } from '@/api/nodes'
import { useJobLogsWS } from '@/hooks/useJobLogsWS'
import { Badge } from '@/components/ui/badge'
import type { Job } from '@/types'

function jobStatusVariant(
  status: Job['status'],
): 'success' | 'destructive' | 'warning' | 'secondary' | 'outline' {
  switch (status) {
    case 'success': return 'success'
    case 'failed': return 'destructive'
    case 'running': return 'warning'
    case 'cancelled': return 'secondary'
    default: return 'outline'
  }
}

export function LogPanel({ jobId }: { jobId: string }) {
  const { lines, done, finalStatus } = useJobLogsWS(jobId)
  const { data: job } = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => getJob(jobId),
    enabled: !!jobId,
  })
  const { data: playbook } = useQuery({
    queryKey: ['playbook', job?.playbook_id],
    queryFn: () => getPlaybook(job!.playbook_id),
    enabled: !!job?.playbook_id,
  })
  const { data: allNodes = [] } = useQuery({
    queryKey: ['nodes'],
    queryFn: () => listNodes(),
  })
  const endRef = useRef<HTMLDivElement>(null)
  const [staticLines, setStaticLines] = useState<{ node_id: string; content: string }[]>([])
  const [loadingStatic, setLoadingStatic] = useState(false)
  const [staticLoaded, setStaticLoaded] = useState(false)

  useEffect(() => {
    if (job && (job.status === 'success' || job.status === 'failed' || job.status === 'cancelled')) {
      if (lines.length === 0 && !staticLoaded && !loadingStatic) {
        setLoadingStatic(true)
        const fetchAllLogs = async () => {
          let allLines: { node_id: string; content: string }[] = []
          for (const node of job.job_nodes) {
            try {
              const contents = await getJobNodeLogsContent(jobId, node.node_id)
              allLines = allLines.concat(contents.map((c) => ({ node_id: node.node_id, content: c })))
            } catch (e) {
              allLines.push({ node_id: node.node_id, content: `Failed to load logs: ${e}` })
            }
          }
          setStaticLines(allLines)
          setLoadingStatic(false)
          setStaticLoaded(true)
        }
        fetchAllLogs()
      }
    }
  }, [job?.status, lines.length, jobId, staticLoaded, loadingStatic])

  const displayLines = lines.length > 0 ? lines : staticLines

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [displayLines])

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-3 border-b border-border flex items-center gap-3">
        <span className="font-medium text-sm text-foreground">
          {playbook ? playbook.name : 'Job Logs'}
        </span>
        {job && <Badge variant={jobStatusVariant(job.status)}>{job.status}</Badge>}
        {done && finalStatus && (
          <span className="text-xs text-muted-foreground ml-auto">Completed: {finalStatus}</span>
        )}
      </div>

      {job && job.job_nodes.length > 0 && (
        <div className="px-4 py-2 border-b border-border flex gap-3 flex-wrap">
          {job.job_nodes.map((jn) => {
            const node = allNodes.find((n) => n.id === jn.node_id)
            return (
              <div
                key={jn.node_id}
                className="flex items-center gap-1.5 text-xs bg-muted/50 px-2 py-1 rounded"
              >
                <span className="font-medium text-foreground">
                  {node ? node.name : `${jn.node_id.slice(0, 8)}…`}
                </span>
                <Badge
                  variant={
                    jn.status === 'success'
                      ? 'success'
                      : jn.status === 'failed'
                      ? 'destructive'
                      : 'warning'
                  }
                  className="text-[10px] px-1 py-0 h-4"
                >
                  {jn.status}
                </Badge>
                {jn.exit_code !== null && (
                  <span className="text-muted-foreground">exit={jn.exit_code}</span>
                )}
              </div>
            )
          })}
        </div>
      )}

      <div className="flex-1 overflow-y-auto bg-gray-950 text-gray-100 font-mono text-xs p-4 space-y-0.5">
        {displayLines.length === 0 && !done && !loadingStatic && (
          <p className="text-gray-500">Waiting for output…</p>
        )}
        {displayLines.length === 0 && loadingStatic && (
          <p className="text-gray-500">Loading archived logs…</p>
        )}
        {displayLines.map((line, i) => (
          <div key={i} className="leading-5">
            {line.node_id && (
              <span className="text-gray-500 mr-2">[{line.node_id.slice(0, 8)}]</span>
            )}
            <span>{line.content}</span>
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </div>
  )
}
