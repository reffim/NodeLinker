import client from './client'
import type { Workflow, WorkflowCreate, WorkflowRun, WorkflowRunCreate } from '../types'

export async function listWorkflows(): Promise<Workflow[]> {
  const { data } = await client.get<Workflow[]>('/workflows')
  return data
}

export async function getWorkflow(id: string): Promise<Workflow> {
  const { data } = await client.get<Workflow>(`/workflows/${id}`)
  return data
}

export async function createWorkflow(payload: WorkflowCreate): Promise<Workflow> {
  const { data } = await client.post<Workflow>('/workflows', payload)
  return data
}

export async function deleteWorkflow(id: string): Promise<void> {
  await client.delete(`/workflows/${id}`)
}

export async function listWorkflowRuns(workflowId: string): Promise<WorkflowRun[]> {
  const { data } = await client.get<WorkflowRun[]>(`/workflows/${workflowId}/runs`)
  return data
}

export async function startWorkflowRun(
  workflowId: string,
  payload: WorkflowRunCreate,
): Promise<WorkflowRun> {
  const { data } = await client.post<WorkflowRun>(`/workflows/${workflowId}/runs`, payload)
  return data
}

export async function getWorkflowRun(runId: string): Promise<WorkflowRun> {
  const { data } = await client.get<WorkflowRun>(`/workflow-runs/${runId}`)
  return data
}

export async function cancelWorkflowRun(runId: string): Promise<WorkflowRun> {
  const { data } = await client.post<WorkflowRun>(`/workflow-runs/${runId}/cancel`)
  return data
}
