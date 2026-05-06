import client from "./client"
import type { Node, NodeCreate, NodeUpdate } from "../types"

export async function listNodes(): Promise<Node[]> {
  const { data } = await client.get<Node[]>("/nodes")
  return data
}

export async function getNode(id: string): Promise<Node> {
  const { data } = await client.get<Node>(`/nodes/${id}`)
  return data
}

export async function createNode(payload: NodeCreate): Promise<Node> {
  const { data } = await client.post<Node>("/nodes", payload)
  return data
}

export async function updateNode(id: string, payload: NodeUpdate): Promise<Node> {
  const { data } = await client.patch<Node>(`/nodes/${id}`, payload)
  return data
}

export async function deleteNode(id: string): Promise<void> {
  await client.delete(`/nodes/${id}`)
}
