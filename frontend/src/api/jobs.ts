import client from "./client"
import type { Job, JobCreate, JobLogChunk } from "../types"

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

export async function getJobLogChunks(jobId: string, after: number): Promise<JobLogChunk[]> {
  const { data } = await client.get<JobLogChunk[]>(`/jobs/${jobId}/logs/chunks`, {
    params: { after },
  })
  return data
}

export async function cancelJob(id: string): Promise<Job> {
  const { data } = await client.post<Job>(`/jobs/${id}/cancel`)
  return data
}
