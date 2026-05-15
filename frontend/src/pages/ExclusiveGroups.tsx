import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Unlock, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { listPlaybooks, updatePlaybook, forceUnlockGroup } from '@/api/playbooks'

// Note: A real implementation would have a backend endpoint to check/clear locks
// For now, we group playbooks on the frontend.
export default function ExclusiveGroups() {
  const queryClient = useQueryClient()
  const { data: playbooks = [], isLoading, refetch } = useQuery({
    queryKey: ['playbooks'],
    queryFn: listPlaybooks,
  })

  const [showCreateModal, setShowCreateModal] = useState(false)
  const [newGroupName, setNewGroupName] = useState('')
  const [selectedPlaybooks, setSelectedPlaybooks] = useState<string[]>([])

  const unlockMutation = useMutation({
    mutationFn: forceUnlockGroup,
    onSuccess: (data) => {
      alert(data.message)
      refetch()
    },
    onError: (error) => {
      alert(`Failed to unlock: ${error}`)
    }
  })

  const assignGroupMutation = useMutation({
    mutationFn: async ({ group, playbookIds }: { group: string, playbookIds: string[] }) => {
      for (const id of playbookIds) {
        await updatePlaybook(id, { exclusive_group: group })
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['playbooks'] })
      setShowCreateModal(false)
      setNewGroupName('')
      setSelectedPlaybooks([])
    }
  })

  // Group playbooks by exclusive_group
  const groups = playbooks.reduce((acc, pb) => {
    const groupName = pb.exclusive_group || 'No Group'
    if (!acc[groupName]) {
      acc[groupName] = []
    }
    acc[groupName].push(pb)
    return acc
  }, {} as Record<string, typeof playbooks>)

  if (isLoading) {
    return <div className="p-6 text-muted-foreground">Loading groups...</div>
  }

  return (
    <div className="p-6 overflow-y-auto h-full relative">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold">Exclusive Groups</h1>
        <Button onClick={() => setShowCreateModal(true)}>
          <Plus className="w-4 h-4 mr-2" />
          Create Group
        </Button>
      </div>
      <div className="grid gap-6">
        {Object.entries(groups).map(([groupName, groupPlaybooks]) => (
          <div key={groupName} className="border border-border rounded-lg p-4 bg-card text-card-foreground shadow-sm">
            <div className="flex justify-between items-center mb-4 border-b pb-2">
              <div>
                <h2 className="text-lg font-semibold">{groupName}</h2>
                {groupName !== 'No Group' && (
                  <div className="text-xs text-muted-foreground flex items-center gap-1 mt-1">
                    <span>Locks are managed per-node for this group</span>
                  </div>
                )}
              </div>
              {groupName !== 'No Group' && (
                <Button 
                  variant="outline" 
                  size="sm" 
                  className="text-orange-600 border-orange-200 hover:bg-orange-50"
                  disabled={unlockMutation.isPending}
                  onClick={() => {
                    if(confirm(`Are you sure you want to forcefully unlock the '${groupName}' group? This should only be used if a job crashed while holding the lock.`)) {
                      unlockMutation.mutate(groupName)
                    }
                  }}
                >
                  <Unlock className="w-4 h-4 mr-2" />
                  Force Unlock
                </Button>
              )}
            </div>
            <ul className="space-y-2">
              {groupPlaybooks.map(pb => (
                <li key={pb.id} className="flex items-center gap-2 text-sm bg-muted/50 p-2 rounded-md">
                  <span className="font-medium flex-1">{pb.name}</span>
                  <span className="text-xs text-muted-foreground w-48 truncate" title={pb.description ?? undefined}>{pb.description}</span>
                  <span className="text-xs px-2 py-1 bg-background rounded border">{pb.source_type}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {showCreateModal && (
        <div className="fixed inset-0 bg-background/80 backdrop-blur-sm z-50 flex items-center justify-center">
          <div className="bg-card text-card-foreground border border-border p-6 rounded-lg shadow-lg w-[400px]">
            <h2 className="text-lg font-semibold mb-4">Create Exclusive Group</h2>
            <div className="space-y-4">
              <div>
                <label className="text-sm font-medium mb-1 block">Group Name *</label>
                <Input 
                  value={newGroupName} 
                  onChange={(e) => setNewGroupName(e.target.value)} 
                  placeholder="e.g. production-deploy"
                />
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block">Select Playbooks</label>
                <div className="max-h-48 overflow-y-auto border border-border rounded-md p-2 space-y-2">
                  {playbooks.map(pb => (
                    <label key={pb.id} className="flex items-center gap-2 text-sm cursor-pointer hover:bg-accent p-1 rounded">
                      <input 
                        type="checkbox" 
                        checked={selectedPlaybooks.includes(pb.id)}
                        onChange={(e) => {
                          if (e.target.checked) setSelectedPlaybooks(prev => [...prev, pb.id])
                          else setSelectedPlaybooks(prev => prev.filter(id => id !== pb.id))
                        }}
                      />
                      <span className="truncate flex-1">{pb.name}</span>
                      {pb.exclusive_group && (
                        <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                          {pb.exclusive_group}
                        </span>
                      )}
                    </label>
                  ))}
                  {playbooks.length === 0 && <span className="text-sm text-muted-foreground p-2">No playbooks found.</span>}
                </div>
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <Button variant="outline" onClick={() => setShowCreateModal(false)}>Cancel</Button>
              <Button 
                disabled={!newGroupName.trim() || selectedPlaybooks.length === 0 || assignGroupMutation.isPending}
                onClick={() => assignGroupMutation.mutate({ group: newGroupName.trim(), playbookIds: selectedPlaybooks })}
              >
                {assignGroupMutation.isPending ? 'Creating...' : 'Create'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
