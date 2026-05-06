// Matches backend Pydantic schemas

export interface User {
  id: string
  username: string
  email: string
  role: string
  oidc_provider: string | null
}

export interface Node {
  id: string
  name: string
  host: string
  port: number
  ssh_user: string
  ssh_key_path: string | null
  status: "online" | "offline" | "unreachable" | "unknown"
  last_seen_at: string | null
  tags: string[] | null
  created_at: string
}

export interface NodeCreate {
  name: string
  host: string
  port?: number
  ssh_user?: string
  ssh_key_path?: string
  tags?: string[]
}

export interface NodeUpdate {
  name?: string
  host?: string
  port?: number
  ssh_user?: string
  ssh_key_path?: string
  tags?: string[]
}

export interface NodeStatusEvent {
  node_id: string
  status: string
  last_seen_at: string | null
}

export interface Playbook {
  id: string
  name: string
  description: string | null
  content: string | null
  source_type: "local" | "git"
  git_url: string | null
  git_ref: string | null
  exclusive_group: string | null
  created_at: string
  updated_at: string
}

export interface PlaybookCreate {
  name: string
  description?: string
  content?: string
  source_type?: "local" | "git"
  git_url?: string
  git_ref?: string
  exclusive_group?: string
}

export interface PlaybookUpdate {
  name?: string
  description?: string
  content?: string
  source_type?: "local" | "git"
  git_url?: string
  git_ref?: string
  exclusive_group?: string
}

export interface JobNode {
  node_id: string
  status: string
  exit_code: number | null
}

export interface Job {
  id: string
  playbook_id: string
  status: "pending" | "running" | "success" | "failed" | "cancelled"
  created_by: string | null
  started_at: string | null
  finished_at: string | null
  exclusive_lock_key: string | null
  created_at: string
  job_nodes: JobNode[]
}

export interface JobCreate {
  playbook_id: string
  node_ids: string[]
  extra_vars?: Record<string, unknown>
}

export interface JobLog {
  id: number
  job_id: string
  node_id: string | null
  line_number: number
  content: string
  created_at: string
}
