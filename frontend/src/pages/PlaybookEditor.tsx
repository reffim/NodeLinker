import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, Save, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { listPlaybooks, createPlaybook, updatePlaybook, deletePlaybook } from '@/api/playbooks'
import type { Playbook, PlaybookCreate } from '@/types'

const DEFAULT_CONTENT = `---
# New Playbook
- name: Example play
  hosts: all
  tasks:
    - name: Print hello
      debug:
        msg: "Hello from NodeLinker"
`

interface FormData {
  name: string
  description: string
  content: string
  source_type: 'local' | 'git'
  git_url: string
  git_ref: string
  exclusive_group: string
}

const EMPTY_FORM: FormData = {
  name: '',
  description: '',
  content: DEFAULT_CONTENT,
  source_type: 'local',
  git_url: '',
  git_ref: 'main',
  exclusive_group: '',
}

export default function PlaybookEditor() {
  const queryClient = useQueryClient()
  const { data: playbooks = [], isLoading } = useQuery({
    queryKey: ['playbooks'],
    queryFn: listPlaybooks,
  })

  const [selected, setSelected] = useState<Playbook | null>(null)
  const [form, setForm] = useState<FormData>(EMPTY_FORM)
  const [isNew, setIsNew] = useState(false)
  const [dirty, setDirty] = useState(false)

  const createMutation = useMutation({
    mutationFn: createPlaybook,
    onSuccess: (pb) => {
      queryClient.invalidateQueries({ queryKey: ['playbooks'] })
      setSelected(pb)
      setIsNew(false)
      setDirty(false)
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<PlaybookCreate> }) =>
      updatePlaybook(id, data),
    onSuccess: (pb) => {
      queryClient.invalidateQueries({ queryKey: ['playbooks'] })
      setSelected(pb)
      setDirty(false)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: deletePlaybook,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['playbooks'] })
      setSelected(null)
      setIsNew(false)
    },
  })

  function selectPlaybook(pb: Playbook) {
    setSelected(pb)
    setIsNew(false)
    setDirty(false)
    setForm({
      name: pb.name,
      description: pb.description ?? '',
      content: pb.content ?? '',
      source_type: pb.source_type,
      git_url: pb.git_url ?? '',
      git_ref: pb.git_ref ?? 'main',
      exclusive_group: pb.exclusive_group ?? '',
    })
  }

  function newPlaybook() {
    setSelected(null)
    setIsNew(true)
    setDirty(false)
    setForm(EMPTY_FORM)
  }

  function field<K extends keyof FormData>(key: K, value: FormData[K]) {
    setForm((f) => ({ ...f, [key]: value }))
    setDirty(true)
  }

  function handleSave() {
    const payload: PlaybookCreate = {
      name: form.name,
      description: form.description || undefined,
      content: form.source_type === 'local' ? form.content : undefined,
      source_type: form.source_type,
      git_url: form.source_type === 'git' ? form.git_url : undefined,
      git_ref: form.source_type === 'git' ? form.git_ref : undefined,
      exclusive_group: form.exclusive_group || undefined,
    }
    if (isNew) {
      createMutation.mutate(payload)
    } else if (selected) {
      updateMutation.mutate({ id: selected.id, data: payload })
    }
  }

  const isBusy = createMutation.isPending || updateMutation.isPending

  return (
    <div className="flex h-full">
      {/* Sidebar list */}
      <div className="w-64 flex-shrink-0 border-r border-border flex flex-col">
        <div className="px-4 py-3 border-b border-border flex items-center justify-between">
          <span className="font-medium text-sm">Playbooks</span>
          <Button variant="ghost" size="icon" onClick={newPlaybook}>
            <Plus className="h-4 w-4" />
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto py-2">
          {isLoading ? (
            <p className="px-4 text-sm text-muted-foreground">Loading…</p>
          ) : playbooks.length === 0 ? (
            <p className="px-4 text-sm text-muted-foreground">No playbooks yet.</p>
          ) : (
            playbooks.map((pb) => (
              <button
                key={pb.id}
                onClick={() => selectPlaybook(pb)}
                className={`w-full text-left px-4 py-2 text-sm flex items-center gap-2 hover:bg-accent transition-colors ${
                  selected?.id === pb.id ? 'bg-accent text-accent-foreground' : 'text-foreground'
                }`}
              >
                <ChevronRight className="h-3 w-3 flex-shrink-0" />
                <span className="truncate">{pb.name}</span>
                {pb.source_type === 'git' && (
                  <Badge variant="secondary" className="ml-auto text-xs">git</Badge>
                )}
              </button>
            ))
          )}
        </div>
      </div>

      {/* Editor panel */}
      {!selected && !isNew ? (
        <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
          Select a playbook or create a new one
        </div>
      ) : (
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Toolbar */}
          <div className="border-b border-border px-4 py-3 flex items-center gap-3 flex-wrap">
            <Input
              className="h-8 w-48"
              placeholder="Playbook name *"
              value={form.name}
              onChange={(e) => field('name', e.target.value)}
            />
            <Input
              className="h-8 w-56"
              placeholder="Description"
              value={form.description}
              onChange={(e) => field('description', e.target.value)}
            />
            <Input
              className="h-8 w-36"
              placeholder="Exclusive group"
              value={form.exclusive_group}
              onChange={(e) => field('exclusive_group', e.target.value)}
            />
            <select
              className="h-8 rounded-md border border-input bg-background px-2 text-sm"
              value={form.source_type}
              onChange={(e) => field('source_type', e.target.value as 'local' | 'git')}
            >
              <option value="local">Local YAML</option>
              <option value="git">Git</option>
            </select>
            {form.source_type === 'git' && (
              <>
                <Input
                  className="h-8 w-56"
                  placeholder="Git URL"
                  value={form.git_url}
                  onChange={(e) => field('git_url', e.target.value)}
                />
                <Input
                  className="h-8 w-24"
                  placeholder="Ref"
                  value={form.git_ref}
                  onChange={(e) => field('git_ref', e.target.value)}
                />
              </>
            )}
            <div className="ml-auto flex gap-2">
              {selected && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => deleteMutation.mutate(selected.id)}
                  disabled={deleteMutation.isPending}
                >
                  <Trash2 className="h-4 w-4 mr-1 text-destructive" />
                  Delete
                </Button>
              )}
              <Button size="sm" onClick={handleSave} disabled={isBusy || !dirty}>
                <Save className="h-4 w-4 mr-1" />
                {isBusy ? 'Saving…' : 'Save'}
              </Button>
            </div>
          </div>

          {/* Editor */}
          {form.source_type === 'local' ? (
            <div className="flex-1 overflow-hidden p-4">
              <textarea
                className="w-full h-full p-4 font-mono text-sm border rounded-md focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none bg-muted/30"
                placeholder="Enter YAML content here..."
                value={form.content}
                onChange={(e) => field('content', e.target.value)}
              />
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">
              Playbook content is loaded from Git at runtime.
            </div>
          )}
        </div>
      )}
    </div>
  )
}
