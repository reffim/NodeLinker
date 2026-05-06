import client from "./client"
import type { Playbook, PlaybookCreate, PlaybookUpdate } from "../types"

export async function listPlaybooks(): Promise<Playbook[]> {
  const { data } = await client.get<Playbook[]>("/playbooks")
  return data
}

export async function getPlaybook(id: string): Promise<Playbook> {
  const { data } = await client.get<Playbook>(`/playbooks/${id}`)
  return data
}

export async function createPlaybook(payload: PlaybookCreate): Promise<Playbook> {
  const { data } = await client.post<Playbook>("/playbooks", payload)
  return data
}

export async function updatePlaybook(id: string, payload: PlaybookUpdate): Promise<Playbook> {
  const { data } = await client.patch<Playbook>(`/playbooks/${id}`, payload)
  return data
}

export async function deletePlaybook(id: string): Promise<void> {
  await client.delete(`/playbooks/${id}`)
}
