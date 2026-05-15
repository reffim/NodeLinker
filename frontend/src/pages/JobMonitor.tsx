import { useEffect, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { Play, XCircle, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { listJobs, getJob, createJob, cancelJob, getJobNodeLogsContent } from '@/api/jobs'
import { getPlaybook, listPlaybooks } from '@/api/playbooks'
import { listNodes } from '@/api/nodes'
import { useJobLogsWS } from '@/hooks/useJobLogsWS'
import type { Job } from '@/types'

function jobStatusVariant(status: Job['status']): 'success' | 'destructive' | 'warning' | 'secondary' | 'outline' {
  switch (status) {
    case 'success': return 'success'
    case 'failed': return 'destructive'
    case 'running': return 'warning'
    case 'cancelled': return 'secondary'
    default: return 'outline'
  }
}

function RunJobModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { data: playbooks = [] } = useQuery({ queryKey: ['playbooks'], queryFn: listPlaybooks })
  const { data: nodes = [] } = useQuery({ queryKey: ['nodes'], queryFn: listNodes })

  const [playbookId, setPlaybookId] = useState('')
  const [selectedNodes, setSelectedNodes] = useState<string[]>([])

  const mutation = useMutation({
    mutationFn: createJob,
    onSuccess: (job) => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      onClose()
      navigate(`/jobs/${job.id}`)
    },
  })

  function toggleNode(id: string) {
    setSelectedNodes((prev) =>
      prev.includes(id) ? prev.filter((n) => n !== id) : [...prev, id]
    )
  }

  function handleRun(e: React.FormEvent) {
    e.preventDefault()
    if (!playbookId || selectedNodes.length === 0) return
    mutation.mutate({ playbook_id: playbookId, node_ids: selectedNodes })
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-card border border-border rounded-lg w-full max-w-md p-6 space-y-4 shadow-lg">
        <h2 className="font-semibold text-lg">Run Job</h2>
        <form onSubmit={handleRun} className="space-y-4">
          <div className="space-y-1">
            <label className="text-sm font-medium">Playbook</label>
            <select
              className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm"
              value={playbookId}
              onChange={(e) => setPlaybookId(e.target.value)}
              required
            >
              <option value="">Select playbook…</option>
              {playbooks.map((pb) => (
                <option key={pb.id} value={pb.id}>{pb.name}</option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <label className="text-sm font-medium">Target Nodes</label>
            <div className="border border-border rounded-md max-h-40 overflow-y-auto divide-y divide-border">
              {nodes.length === 0 ? (
                <p className="px-3 py-2 text-sm text-muted-foreground">No nodes available.</p>
              ) : (
                nodes.map((node) => (
                  <label key={node.id} className="flex items-center gap-2 px-3 py-2 hover:bg-accent cursor-pointer">
                    <input
                      type="checkbox"
                      checked={selectedNodes.includes(node.id)}
                      onChange={() => toggleNode(node.id)}
                    />
                    <span className="text-sm">{node.name}</span>
                    <Badge variant={node.status === 'online' ? 'success' : 'secondary'} className="ml-auto">
                      {node.status}
                    </Badge>
                  </label>
                ))
              )}
            </div>
          </div>
          <div className="flex gap-2 justify-end">
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={mutation.isPending || !playbookId || selectedNodes.length === 0}>
              {mutation.isPending ? 'Launching…' : 'Run'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

function LogPanel({ jobId }: { jobId: string }) {
  const { lines, done, finalStatus } = useJobLogsWS(jobId)
  const { data: job } = useQuery({ queryKey: ['job', jobId], queryFn: () => getJob(jobId), enabled: !!jobId })

  const { data: playbook } = useQuery({
    queryKey: ['playbook', job?.playbook_id],
    queryFn: () => getPlaybook(job!.playbook_id),
    enabled: !!job?.playbook_id
  })

  const { data: allNodes = [] } = useQuery({
    queryKey: ['nodes'],
    queryFn: () => listNodes()
  })
  const endRef = useRef<HTMLDivElement>(null)
  
  const [staticLines, setStaticLines] = useState<{node_id: string, content: string}[]>([])
  const [loadingStatic, setLoadingStatic] = useState(false)
  const [staticLoaded, setStaticLoaded] = useState(false)

  useEffect(() => {
    if (job && (job.status === 'success' || job.status === 'failed' || job.status === 'cancelled')) {
      if (lines.length === 0 && !staticLoaded && !loadingStatic) {
        setLoadingStatic(true)
        const fetchAllLogs = async () => {
          let allLines: {node_id: string, content: string}[] = []
          for (const node of job.job_nodes) {
            try {
              const contents = await getJobNodeLogsContent(jobId, node.node_id)
              allLines = allLines.concat(contents.map(c => ({ node_id: node.node_id, content: c })))
            } catch (e) {
              allLines.push({ node_id: node.node_id, content: `Failed to load logs: ${e}` })
            }
          }
          setStaticLines(allLines)
          // Always reset loading state so it doesn't get stuck
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
            const node = allNodes.find(n => n.id === jn.node_id)
            return (
              <div key={jn.node_id} className="flex items-center gap-1.5 text-xs bg-muted/50 px-2 py-1 rounded">
                <span className="font-medium text-foreground">{node ? node.name : `${jn.node_id.slice(0, 8)}…`}</span>
                <Badge variant={jn.status === 'success' ? 'success' : jn.status === 'failed' ? 'destructive' : 'warning'} className="text-[10px] px-1 py-0 h-4">
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

export default function JobMonitor() {
  const { jobId } = useParams<{ jobId: string }>()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  
  const filterNodeId = searchParams.get('nodeId')

  const { data: allNodes = [] } = useQuery({
    queryKey: ['nodes'],
    queryFn: () => listNodes()
  })

  const { data: jobs = [], isLoading } = useQuery({
    queryKey: ['jobs'],
    queryFn: () => listJobs(),
    refetchInterval: 10_000,
  })

  const filteredJobs = filterNodeId
    ? jobs.filter(job => job.job_nodes.some(jn => jn.node_id === filterNodeId))
    : jobs

  const [showRunModal, setShowRunModal] = useState(false)

  const cancelMutation = useMutation({
    mutationFn: cancelJob,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['jobs'] }),
  })

  return (
    <div className="flex h-full">
      {/* Job list sidebar */}
      <div className="w-72 flex-shrink-0 border-r border-border flex flex-col">
        <div className="px-4 py-3 border-b border-border space-y-3">
          <div className="flex items-center justify-between">
            <span className="font-medium text-sm">Jobs</span>
            <Button variant="ghost" size="sm" onClick={() => setShowRunModal(true)}>
              <Play className="h-4 w-4 mr-1" /> Run
            </Button>
          </div>
          <select 
            className="w-full text-xs p-1.5 rounded border border-input bg-transparent text-foreground"
            value={filterNodeId || ''}
            onChange={(e) => setSearchParams(e.target.value ? { nodeId: e.target.value } : {})}
          >
            <option value="">All Nodes</option>
            {allNodes.map(node => (
              <option key={node.id} value={node.id}>{node.name}</option>
            ))}
          </select>
        </div>
        <div className="flex-1 overflow-y-auto divide-y divide-border">
          {isLoading ? (
            <p className="px-4 py-3 text-sm text-muted-foreground">Loading…</p>
          ) : filteredJobs.length === 0 ? (
            <p className="px-4 py-3 text-sm text-muted-foreground">No jobs found.</p>
          ) : (
            filteredJobs.map((job) => (
              <button
                key={job.id}
                onClick={() => navigate(`/jobs/${job.id}`)}
                className={`w-full text-left px-4 py-3 hover:bg-accent transition-colors flex items-start gap-2 ${
                  jobId === job.id ? 'bg-accent' : ''
                }`}
              >
                <ChevronRight className="h-3.5 w-3.5 mt-0.5 flex-shrink-0 text-muted-foreground" />
                <div className="flex-1 min-w-0 space-y-1">
                  <div className="text-xs font-medium truncate">{job.id.slice(0, 16)}…</div>
                  <div className="flex items-center gap-1.5">
                    <Badge variant={jobStatusVariant(job.status)} className="text-xs">{job.status}</Badge>
                    <span className="text-xs text-muted-foreground">
                      {job.job_nodes.length} node{job.job_nodes.length !== 1 ? 's' : ''}
                    </span>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {new Date(job.created_at).toLocaleString()}
                  </div>
                </div>
                {(job.status === 'running' || job.status === 'pending') && (
                  <button
                    onClick={(e) => { e.stopPropagation(); cancelMutation.mutate(job.id) }}
                    className="p-1 hover:text-destructive transition-colors"
                  >
                    <XCircle className="h-4 w-4" />
                  </button>
                )}
              </button>
            ))
          )}
        </div>
      </div>

      {/* Log panel */}
      <div className="flex-1 overflow-hidden">
        {jobId ? (
          <LogPanel key={jobId} jobId={jobId} />
        ) : (
          <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
            Select a job to view logs
          </div>
        )}
      </div>

      {showRunModal && <RunJobModal onClose={() => setShowRunModal(false)} />}
    </div>
  )
}
