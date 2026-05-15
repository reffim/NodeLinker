import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, RefreshCw, Trash2, Edit2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { listNodes, createNode, updateNode, deleteNode } from '@/api/nodes'
import { listJobs } from '@/api/jobs'
import { listPlaybooks } from '@/api/playbooks'
import { useNodeStatusWS } from '@/hooks/useNodeStatusWS'
import { Link } from 'react-router-dom'
import type { Node, NodeCreate } from '@/types'

function statusVariant(status: Node['status']): 'success' | 'destructive' | 'warning' | 'secondary' {
  switch (status) {
    case 'online': return 'success'
    case 'offline': return 'destructive'
    case 'unreachable': return 'warning'
    default: return 'secondary'
  }
}

interface NodeFormData {
  name: string
  host: string
  port: string
  ssh_user: string
  ssh_key_path: string
  tags: string
}

const EMPTY_FORM: NodeFormData = { name: '', host: '', port: '22', ssh_user: 'root', ssh_key_path: '', tags: '' }

export default function NodeDashboard() {
  const queryClient = useQueryClient()
  const { data: nodes = [], isLoading } = useQuery({ queryKey: ['nodes'], queryFn: listNodes })
  const { data: jobs = [] } = useQuery({ queryKey: ['jobs'], queryFn: () => listJobs(), refetchInterval: 10_000 })
  const { data: playbooks = [] } = useQuery({ queryKey: ['playbooks'], queryFn: () => listPlaybooks() })
  useNodeStatusWS()

  const [showForm, setShowForm] = useState(false)
  const [editingNode, setEditingNode] = useState<Node | null>(null)
  const [form, setForm] = useState<NodeFormData>(EMPTY_FORM)

  const createMutation = useMutation({
    mutationFn: createNode,
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['nodes'] }); closeForm() },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: NodeCreate }) => updateNode(id, data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['nodes'] }); closeForm() },
  })

  const deleteMutation = useMutation({
    mutationFn: deleteNode,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['nodes'] }),
  })

  function openCreate() {
    setEditingNode(null)
    setForm(EMPTY_FORM)
    setShowForm(true)
  }

  function openEdit(node: Node) {
    setEditingNode(node)
    setForm({
      name: node.name,
      host: node.host,
      port: String(node.port),
      ssh_user: node.ssh_user,
      ssh_key_path: node.ssh_key_path ?? '',
      tags: (node.tags ?? []).join(', '),
    })
    setShowForm(true)
  }

  function closeForm() {
    setShowForm(false)
    setEditingNode(null)
    setForm(EMPTY_FORM)
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const payload: NodeCreate = {
      name: form.name,
      host: form.host,
      port: Number(form.port) || 22,
      ssh_user: form.ssh_user,
      ssh_key_path: form.ssh_key_path || undefined,
      tags: form.tags ? form.tags.split(',').map((t) => t.trim()).filter(Boolean) : undefined,
    }
    if (editingNode) {
      updateMutation.mutate({ id: editingNode.id, data: payload })
    } else {
      createMutation.mutate(payload)
    }
  }

  const isBusy = createMutation.isPending || updateMutation.isPending

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Nodes</h1>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => queryClient.invalidateQueries({ queryKey: ['nodes'] })}>
            <RefreshCw className="h-4 w-4" />
          </Button>
          <Button size="sm" onClick={openCreate}>
            <Plus className="h-4 w-4 mr-1" /> Add Node
          </Button>
        </div>
      </div>

      {/* Add/Edit form */}
      {showForm && (
        <Card>
          <CardHeader>
            <CardTitle>{editingNode ? 'Edit Node' : 'Add Node'}</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <label className="text-sm font-medium">Name *</label>
                <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
              </div>
              <div className="space-y-1">
                <label className="text-sm font-medium">Host *</label>
                <Input value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} required />
              </div>
              <div className="space-y-1">
                <label className="text-sm font-medium">Port</label>
                <Input type="number" value={form.port} onChange={(e) => setForm({ ...form, port: e.target.value })} />
              </div>
              <div className="space-y-1">
                <label className="text-sm font-medium">SSH User</label>
                <Input value={form.ssh_user} onChange={(e) => setForm({ ...form, ssh_user: e.target.value })} />
              </div>
              <div className="space-y-1">
                <label className="text-sm font-medium">SSH Key Path</label>
                <Input value={form.ssh_key_path} onChange={(e) => setForm({ ...form, ssh_key_path: e.target.value })} />
              </div>
              <div className="space-y-1">
                <label className="text-sm font-medium">Tags (comma-separated)</label>
                <Input value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} />
              </div>
              <div className="col-span-2 flex gap-2 justify-end">
                <Button type="button" variant="outline" onClick={closeForm}>Cancel</Button>
                <Button type="submit" disabled={isBusy}>{isBusy ? 'Saving…' : 'Save'}</Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {/* Node table */}
      {isLoading ? (
        <p className="text-muted-foreground text-sm">Loading nodes…</p>
      ) : nodes.length === 0 ? (
        <p className="text-muted-foreground text-sm">No nodes registered yet.</p>
      ) : (
        <div className="rounded-md border border-border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">Name</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">Host</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">Status</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">Recent Job</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">Tags</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">Last Seen</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {nodes.map((node) => {
                // Find the most recent job that includes this node
                // Assuming jobs are returned from backend in descending order of created_at
                const recentJob = jobs.find(j => j.job_nodes.some(jn => jn.node_id === node.id))
                const playbook = recentJob ? playbooks.find(p => p.id === recentJob.playbook_id) : null
                const jn = recentJob?.job_nodes.find(jn => jn.node_id === node.id)
                
                return (
                <tr key={node.id} className="hover:bg-muted/20 transition-colors">
                  <td className="px-4 py-3 font-medium">{node.name}</td>
                  <td className="px-4 py-3 text-muted-foreground">{node.host}:{node.port}</td>
                  <td className="px-4 py-3">
                    <Badge variant={statusVariant(node.status)}>{node.status}</Badge>
                  </td>
                  <td className="px-4 py-3 text-xs">
                    {recentJob && playbook ? (
                      <div className="flex flex-col gap-1 items-start">
                        <Link to={`/jobs/${recentJob.id}`} className="text-primary hover:underline font-medium text-xs">
                          {playbook.name}
                        </Link>
                        <div className="flex items-center gap-2">
                          <span className="text-muted-foreground flex items-center gap-1 text-[10px]">
                            <span className={`w-1.5 h-1.5 rounded-full ${recentJob.status === 'running' ? 'bg-blue-500 animate-pulse' : jn?.status === 'success' ? 'bg-green-500' : jn?.status === 'failed' ? 'bg-red-500' : 'bg-gray-400'}`}></span>
                            {recentJob.status === 'running' ? 'Running' : jn?.status === 'success' ? 'Success' : jn?.status === 'failed' ? 'Failed' : recentJob.status}
                          </span>
                          <Link to={`/jobs?nodeId=${node.id}`} className="text-[10px] text-muted-foreground hover:text-primary transition-colors hover:underline">
                            View history
                          </Link>
                        </div>
                      </div>
                    ) : (
                      <div className="flex flex-col gap-1 items-start">
                        <span className="text-muted-foreground">—</span>
                        <Link to={`/jobs?nodeId=${node.id}`} className="text-[10px] text-muted-foreground hover:text-primary transition-colors hover:underline">
                          View history
                        </Link>
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      {(node.tags ?? []).map((tag) => (
                        <Badge key={tag} variant="outline">{tag}</Badge>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground text-xs">
                    {node.last_seen_at ? new Date(node.last_seen_at).toLocaleString() : '—'}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1 justify-end">
                      <Button variant="ghost" size="icon" onClick={() => openEdit(node)}>
                        <Edit2 className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => deleteMutation.mutate(node.id)}
                        disabled={deleteMutation.isPending}
                      >
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </div>
                  </td>
                </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
