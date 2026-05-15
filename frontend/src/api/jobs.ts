import client from "./client"
import type { Job, JobCreate, JobLog } from "../types"

export interface ListJobsParams {
  job_status?: string
  playbook_id?: string
  limit?: number
  offset?: number
}

export async function listJobs(params?: ListJobsParams): Promise<Job[]> {
  const { data } = await client.get<Job[]>("/jobs", { params })
  return data
}

export async function getJob(id: string): Promise<Job> {
  const { data } = await client.get<Job>(`/jobs/${id}`)
  return data
}

export async function createJob(payload: JobCreate): Promise<Job> {
  const { data } = await client.post<Job>("/jobs", payload)
  return data
}

export async function getJobLogs(id: string): Promise<JobLog[]> {
  const { data } = await client.get<JobLog[]>(`/jobs/${id}/logs`)
  return data
}

export async function getJobNodeLogsContent(jobId: string, nodeId: string): Promise<string[]> {
  const { data } = await client.get<string[]>(`/jobs/${jobId}/nodes/${nodeId}/logs/content`)
  return data
}

export async function cancelJob(id: string): Promise<Job> {
  const { data } = await client.post<Job>(`/jobs/${id}/cancel`)
  return data
}
