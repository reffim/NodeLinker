import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { Node, NodeStatusEvent } from '@/types'

/**
 * Subscribes to /ws/nodes and patches the cached node list in React Query.
 * Server sends: { node_id, status, last_seen_at }
 */
export function useNodeStatusWS() {
  const queryClient = useQueryClient()

  useEffect(() => {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/nodes`)

    ws.onmessage = (event) => {
      try {
        const msg: NodeStatusEvent = JSON.parse(event.data)
        queryClient.setQueryData<Node[]>(['nodes'], (prev) => {
          if (!prev) return prev
          return prev.map((n) =>
            n.id === msg.node_id
              ? { ...n, status: msg.status as Node['status'], last_seen_at: msg.last_seen_at }
              : n
          )
        })
      } catch {
        // ignore malformed frames
      }
    }

    ws.onerror = () => ws.close()

    return () => {
      ws.close()
    }
  }, [queryClient])
}
