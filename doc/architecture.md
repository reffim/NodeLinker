# NodeLinker Architecture

## Overview

NodeLinker는 Ansible Automation Platform(AWX/Tower)의 역할을 수행하면서, devtron과 유사한 노드 모니터링 UI를 제공하는 웹 기반 인프라 자동화 플랫폼이다.

이 문서는 설계 목표가 아니라 **현재 구현 상태**를 기술한다. 아직 동작하지 않거나 일부만 구현된 항목은 [Known Limitations](#known-limitations)에 정리한다.

---

## Requirements Mapping

| # | Requirement | Component | Status |
|---|-------------|-----------|--------|
| 1 | Node list + status monitoring (devtron-like) | Node API + health probe + `/ws/nodes` | Implemented |
| 2 | Ansible playbook management (CRUD) | Playbook API (content stored in PostgreSQL) | Implemented for local playbooks; Git source is not executable |
| 3 | Select nodes → run playbook | Job API + `run_job` Celery task | Implemented |
| 4 | Job tracking (which playbook on which node) | `job_nodes` + `job_log_chunks` + REST polling | Implemented (near-real-time polling) |
| 5 | Mutual-exclusion control per node | Redis lock service + `exclusive_group` | Implemented |
| 6 | Own account management + OIDC (web access) | Auth API (local + OIDC) | Local implemented; OIDC callback is broken |
| 7 | Secure SSH credential management | Credential API + HashiCorp Vault KV v2 | Implemented at API level; no UI |
| 8 | Multi-step playbook orchestration | Workflow API + `run_workflow` task + `/ws/workflow-runs/{run_id}` | Implemented |

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Browser (SPA)                        │
│   React 19 + React Query + Zustand + Tailwind + React Flow  │
│   Nodes / Playbooks / Groups / Jobs / Workflows / Run view  │
└────────────────────────────┬────────────────────────────────┘
                             │ HTTP (REST, WebSocket upgrade)
┌────────────────────────────▼────────────────────────────────┐
│                            Nginx                            │
│   Serves the built SPA, proxies /api/ and /ws/ to backend   │
│   Rate limits: /api/ 60 r/m, auth login/register 10 r/m     │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│                       FastAPI backend                       │
│   /api/v1: auth, credentials, nodes, playbooks, jobs,       │
│            workflows, workflow-runs                         │
│   /ws/nodes   /ws/workflow-runs/{run_id}                    │
└───┬──────────────────┬──────────────────────┬───────────────┘
    │ SQL              │ enqueue, pub/sub,    │ KV v2 read/write
    │                  │ force-unlock         │
    │       ┌──────────▼───────────┐          │
    │       │       Redis 7        │          │
    │       │ - Celery broker and  │          │
    │       │   result backend     │          │
    │       │ - Per-node locks     │          │
    │       │ - Pub/sub channels   │          │
    │       └──────────▲───────────┘          │
    │                  │                      │
    │       ┌──────────▼───────────┐          │
    │       │ Celery beat + worker │          │
    │       │ (separate containers)│          │
    │       │ Beat enqueues:       │          │
    │       │ - probe_all_nodes    │          │
    │       │ - sweep_stale_runs   │          │
    │       │ Worker also runs:    ├──────────┤
    │       │ - run_job            │          │
    │       │ - run_workflow       │          │
    │       └───┬──────────────┬───┘          │
    │       SQL │              │ SSH          │
┌───▼───────────▼──────┐   ┌───▼─────────┐  ┌─▼────────────────┐
│     PostgreSQL 16    │   │ Managed     │  │ HashiCorp Vault  │
│ Metadata, playbook   │   │ nodes       │  │ SSH keys and     │
│ content, job logs    │   │             │  │ passwords        │
└──────────────────────┘   └─────────────┘  └──────────────────┘
```

Ansible runs inside the Celery worker: `ansible-runner` is started per (job, node) in a temporary directory that is deleted when the task finishes. Logs persist only in PostgreSQL. There is no object storage.

---

## Software Stack

### Backend
| Layer | Technology | Notes |
|-------|-----------|-------|
| API framework | **FastAPI** (Python 3.12) | REST and WebSocket; OpenAPI docs at `/api/docs` |
| Task queue | **Celery 5** + Redis broker | Worker concurrency 4; beat for periodic tasks |
| Ansible execution | **ansible-runner** + ansible-core | `run_async` per (job, node) |
| ORM | **SQLAlchemy 2.x** (async, asyncpg) + Alembic | 5 migrations; applied at backend startup |
| Database | **PostgreSQL 16** | Includes playbook content and job log chunks |
| Broker / pub/sub / locks | **Redis 7** | No session cache; auth is stateless JWT |
| Secret manager | **HashiCorp Vault** (`hvac`) | KV v2, default mount `secret` |
| Auth | **python-jose** (JWT), **bcrypt**, **Authlib** (OIDC client) | JWTs in HttpOnly cookies |
| Health probe | **asyncssh** | Concurrent SSH with TCP fallback |
| Log tailing | **aiofiles** | Reads the ansible-runner stdout artifact |

### Frontend
| Layer | Technology | Notes |
|-------|-----------|-------|
| Framework | **React 19** + TypeScript | |
| Build | **Vite** | |
| UI components | Hand-maintained shadcn-style components + Tailwind CSS 3 | `components/ui`: badge, button, card, input |
| State | **Zustand** (auth user, persisted to localStorage) + **React Query** (server state) | |
| HTTP | **axios** | Sends cookies; a 401 clears auth state and redirects to `/login` |
| Workflow graph | **@xyflow/react** (React Flow) | Read-only DAG in the workflow and run views |
| Real-time | Native WebSocket + polling | See [Real-time Updates](#5-real-time-updates) |
| Routing | **React Router v6** | |

`@monaco-editor/react` is declared in `package.json` but not imported. The playbook editor is a `<textarea>`.

### Infrastructure / DevOps
| Layer | Technology |
|-------|-----------|
| Containerization | Docker + Docker Compose (`docker-compose.yml`, `docker-compose.dev.yml` overrides) |
| Reverse proxy | Nginx 1.27; `nginx/Dockerfile` builds the frontend into the image |
| Local development | `dev/local.sh` (lifecycle), `dev/seed-local.sh` (Vault and test data seed) |
| Test targets | `test-node`, `test-node-2` SSH containers (`dev/Dockerfile.test-node`) |

Compose services: `db`, `redis`, `vault`, `test-node`, `test-node-2`, `backend`, `celery-worker`, `celery-beat`, `nginx`. Only Nginx publishes a port by default; the dev override also exposes the database, Redis, Vault, the backend, and the test nodes.

---

## Key Design Decisions

### 1. Mutual Exclusion

Each playbook may set an `exclusive_group`. For such playbooks, `run_job` acquires the Redis lock `node:{node_id}:exclusive:{exclusive_group}` before running, so jobs in the same group are serialized per node. Jobs on different nodes, or with no group, are not serialized.

| Aspect | Behavior |
|--------|----------|
| Acquire | `SET NX` with a 300 s TTL; the token is the job ID |
| Heartbeat | Extends the TTL every 150 s while the task runs; a crashed worker's lock expires through the TTL |
| Release | Lua script deletes the key only if the token matches |
| Contention | Celery retry every 30 s, up to 120 times (about 1 hour); the job node stays `pending` meanwhile |
| Force unlock | `POST /playbooks/groups/{group}/unlock` (admin, operator) deletes the group's locks on all nodes, without checking for running jobs |

The `jobs.exclusive_lock_key` column is informational only. It stores `exclusive:{group}`, is not the actual Redis key, and is not set on jobs created by workflows.

### 2. Node Status Monitoring

Celery beat triggers `probe_all_nodes` every 30 s. It probes all nodes concurrently with `asyncssh` (5 s timeout), using credentials from Vault when the node has one.

| Probe result | Status |
|--------------|--------|
| SSH connects, or authentication is rejected (host is up) | `online` |
| Connection refused or lost, or SSH disconnects | `offline` |
| Other SSH failure, but the TCP port accepts connections | `offline` |
| Other SSH failure, and the TCP port is unreachable | `unreachable` |

New nodes start as `unknown`. Only status changes are written to PostgreSQL and published to the Redis channel `node_status`, which `/ws/nodes` forwards to browsers.

### 3. Job Execution and Log Storage

```
POST /api/v1/jobs
  └─ creates jobs + one job_nodes row per node; enqueues one run_job per node

run_job(job, node)
  1. Acquire the exclusive lock if the playbook has a group (retry if held)
  2. Mark job and job node as running
  3. Read the SSH credential from Vault
  4. Write inventory, key file, and playbook to a temporary directory
  5. Start ansible-runner; tail stdout and insert into job_log_chunks
  6. Set job node status and exit code
  7. When all job nodes are terminal, set the job to success or failed
  8. Stop the heartbeat and release the lock
```

Log lines are buffered in memory and flushed as one `job_log_chunks` row about every 1.5 s, and again when tailing ends. The UI reads them incrementally with `GET /jobs/{id}/logs/chunks?after={last_chunk_id}`. This replaced the earlier Redis log streaming and file archival design (migration `0005`). No retention or cleanup exists for log chunks.

### 4. Workflows

A workflow is an ordered list of steps, each referencing a playbook, with an optional `on_failure_step_id`. `POST /workflows/{id}/runs` pre-creates one `workflow_run_steps` row per (step, node) as `pending`, then enqueues `run_workflow`.

The `run_workflow` task runs steps one at a time:

1. It creates one single-node job per node, dispatches `run_job` for each, and publishes `step_started`.
2. It polls PostgreSQL every 5 s until every job of the step is terminal, then publishes `step_finished` per node.
3. It chooses what happens next:

| Step outcome | Next action |
|--------------|-------------|
| All nodes succeeded | Next step by `order`; the run succeeds if there is none |
| Any node failed, fallback set | Jump to the fallback step, then continue with steps of higher `order` |
| Any node failed, no fallback | The run fails |
| Run cancelled | Mark the current step's rows `failed` and the run `cancelled` |

A failure on one node fails the step for routing purposes, but all nodes in the step finish first. Steps never reached are marked `skipped`. A run that reaches the end through a successful fallback finishes as `success`.

`sweep_stale_runs` runs every 5 minutes and marks runs as `failed` if they are `pending` or `running` and were created more than 60 minutes ago.

Workflow steps cannot be edited after creation: `PATCH /workflows/{id}` accepts only the name and description.

### 5. Real-time Updates

| Data | Mechanism | Interval |
|------|-----------|----------|
| Node status | `/ws/nodes` (Redis `node_status`) | On change |
| Workflow step transitions | `/ws/workflow-runs/{run_id}` (Redis `workflow:{run_id}:events`) | On change |
| Workflow run state | REST polling, alongside the WebSocket | 3 s while active |
| Job status | REST polling | 2 s while active |
| Job logs | REST polling of log chunks | 2 s |
| Job list | REST polling | 10 s |
| Run list of a workflow | REST polling | 10 s while any run is active |

Workflow WebSocket events:

```json
{"type": "step_started",  "step_id": "<run step id>", "job_id": "...", "order": 0, "node_id": "..."}
{"type": "step_finished", "step_id": "<run step id>", "status": "success|failed", "node_id": "..."}
{"type": "workflow_done", "status": "success|failed|cancelled"}
{"type": "error",         "detail": "..."}
```

If the run has already finished when a client connects, the server sends `workflow_done` and closes.

### 6. Playbook Storage

Playbook YAML is stored in `playbooks.content` and edited in the browser. The `git` source type stores `git_url` and `git_ref`, but nothing clones or syncs the repository.

### 7. Authentication and Authorization

- **Local accounts:** bcrypt password hashes. `POST /auth/register` is open, and the first user becomes `admin` while later users become `operator`.
- **Sessions:** JWT access token (15 min) and refresh token (7 days) in HttpOnly, SameSite=Lax cookies, marked `Secure` unless `DEBUG` is on. The frontend client does not refresh automatically on 401.
- **OIDC:** Authorization Code flow with a signed `state`, enabled by `OIDC_ENABLED`. See the limitation below.

| Role | Read | Create, update, run, cancel, force unlock | Delete |
|------|------|-------------------------------------------|--------|
| `admin` | Yes | Yes | Yes |
| `operator` | Yes | Yes | No |
| `viewer` | Yes | No | No |

There is no API to change a user's role or manage users.

### 8. Credentials

PostgreSQL stores only metadata (`name`, `type`, `vault_path`); secrets are in Vault KV v2 as `{"private_key": ...}` or `{"password": ...}`. Creating a credential writes to Vault first, and deletes the secret again if the database commit fails. The API never returns secret material.

---

## API Surface

All REST routes are under `/api/v1` and require the access token cookie, except the public auth routes (`register`, `login`, `logout`, `refresh`, `oidc/*`). `GET /api/health` is also public.

| Resource | Routes |
|----------|--------|
| Auth | `POST /auth/register`, `/login`, `/logout`, `/refresh`; `GET /auth/me`, `/oidc/login`, `/oidc/callback` |
| Credentials | CRUD on `/credentials` |
| Nodes | CRUD on `/nodes` |
| Playbooks | CRUD on `/playbooks`; `POST /playbooks/groups/{group}/unlock` |
| Jobs | `GET`, `POST /jobs`; `GET /jobs/{id}`; `GET /jobs/{id}/logs/chunks`; `POST /jobs/{id}/cancel` |
| Workflows | CRUD on `/workflows`; `GET`, `POST /workflows/{id}/runs` |
| Workflow runs | `GET /workflow-runs/{id}`; `POST /workflow-runs/{id}/cancel` |

WebSocket routes: `/ws/nodes`, `/ws/workflow-runs/{run_id}`.

---

## Data Model

Source of truth: `backend/app/models/models.py`.

```sql
-- Users
users(id, username, email, password_hash, oidc_sub, oidc_provider, role, created_at)
-- role: 'admin' | 'operator' | 'viewer'

-- Credentials (metadata only; secrets are stored in Vault)
credentials(id, name, type, vault_path, created_by, created_at, updated_at)
-- type: 'ssh_key' | 'ssh_password'

-- Nodes
nodes(id, name, host, port, ssh_user, credential_id, status, last_seen_at, tags, created_at)
-- status: 'online' | 'offline' | 'unreachable' | 'unknown'

-- Playbooks
playbooks(id, name, description, content, source_type, git_url, git_ref, exclusive_group, created_at, updated_at)
-- source_type: 'local' | 'git'

-- Jobs
jobs(id, playbook_id, status, created_by, started_at, finished_at, exclusive_lock_key, created_at)
-- status: 'pending' | 'running' | 'success' | 'failed' | 'cancelled'

-- Job-node mapping (composite primary key)
job_nodes(job_id, node_id, status, exit_code)
-- status: 'pending' | 'running' | 'success' | 'failed'

-- Job log chunks, unique on (job_id, node_id, chunk_seq)
job_log_chunks(id, job_id, node_id, chunk_seq, content, created_at)

-- Workflow definitions
workflows(id, name, description, created_at, updated_at)
workflow_steps(id, workflow_id, order, playbook_id, on_failure_step_id)

-- Workflow executions
workflow_runs(id, workflow_id, status, created_by, node_ids, extra_vars, started_at, finished_at, created_at)
-- status: 'pending' | 'running' | 'success' | 'failed' | 'cancelled'

-- One row per (step, node) in a run
workflow_run_steps(id, workflow_run_id, workflow_step_id, job_id, node_id, status, started_at, finished_at)
-- status: 'pending' | 'running' | 'success' | 'failed' | 'skipped'
```

---

## Directory Structure

```
project_minerva/
├── backend/
│   ├── app/
│   │   ├── api/v1/       # Routers: auth, credentials, nodes, playbooks, jobs, workflows
│   │   ├── core/         # Config, JWT and passwords, OIDC client, Vault client
│   │   ├── db/           # Async engine and session
│   │   ├── models/       # SQLAlchemy models
│   │   ├── schemas/      # Pydantic schemas
│   │   ├── services/     # lock_service (Redis locks)
│   │   ├── worker/       # Celery app; tasks: job_runner, workflow_runner, health_probe
│   │   └── ws/           # Workflow run WebSocket (/ws/nodes lives in api/v1/nodes.py)
│   ├── alembic/          # DB migrations (0001-0005)
│   ├── tests/            # pytest: workflow API, workflow runner, log chunk API
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── api/          # axios client and per-resource API functions
│   │   ├── components/   # Layout, LogPanel, WorkflowGraph, ProtectedRoute, ui/
│   │   ├── hooks/        # useNodeStatusWS, useWorkflowRunWS, useJobLogsPoll
│   │   ├── lib/          # Utilities
│   │   ├── pages/        # Login, Nodes, Playbooks, Groups, Jobs, Workflows, Run monitor
│   │   ├── stores/       # Zustand auth store
│   │   └── types/        # TypeScript types
│   ├── package.json
│   └── Dockerfile        # Standalone SPA image; not used by docker-compose.yml
├── nginx/                # Compose entry point: nginx.conf and Dockerfile (SPA + proxy)
├── dev/                  # Local helper scripts and test node Dockerfile
├── playbooks/            # Sample playbooks
├── doc/                  # This document
├── docs/superpowers/     # Feature design specs and implementation plans
├── docker-compose.yml
└── docker-compose.dev.yml
```

---

## Implementation Status

| Area | Status |
|------|--------|
| DB schema, local auth, API skeleton | Done |
| Vault integration, credential API | Done; no frontend UI |
| Node inventory, health probe, status WebSocket | Done |
| Playbook CRUD, single and multi-node job dispatch | Done for local playbooks |
| Log storage | Done with DB chunks; replaced the planned Object Storage pipeline |
| Mutual exclusion with TTL, heartbeat, and force unlock | Done |
| Workflows: orchestration, per-node run steps, DAG UI | Done; no step editing |
| Frontend SPA | Done, except credential management and credential assignment |
| Docker Compose and Nginx packaging | Done for development; see the production items below |
| OIDC login | Incomplete; callback fails |
| Git-backed playbooks | Not implemented; fields only |
| Production hardening | Not done |

---

## Known Limitations

These reflect the code as of this update. They come from reading the code, not from runtime testing, unless the text says otherwise.

### Functional gaps

- **OIDC callback fails.** `core/oidc.py` calls `client.parse_id_token()` on Authlib's `AsyncOAuth2Client`, which does not define that method in the pinned Authlib 1.3.2, so the callback should raise `AttributeError` after the token exchange. The nonce is also never verified.
- **Git playbooks cannot run.** The UI sends no content for the `git` source, and `run_job` fails any playbook with empty content.
- **No credential UI.** The frontend does not call the credentials API, and the node form does not set `credential_id`. Credentials are assigned through the API or `dev/seed-local.sh`.
- **Cancellation does not stop Ansible.** Cancelling only updates database status, so a running playbook continues until it ends. Job nodes of tasks that had not started stay `pending`.
- **`last_seen_at` is stale while a node stays online.** The update is skipped when the status has not changed, so the value records the last transition to `online`.

### Workflow and job execution

- **Worker starvation.** `run_workflow` occupies a worker slot while polling, and the worker has 4 slots. Four concurrent runs would leave no slot for the `run_job` tasks they are waiting on.
- **Exhausted lock retries leave jobs stuck.** After about an hour of contention the task ends, but nothing marks the job as failed, so the job stays `pending`. A workflow polling that job keeps waiting.
- **Stale sweep can hit healthy runs.** The 60-minute limit counts from `created_at`, so a run legitimately active for longer is marked `failed`. The sweep does not stop the orchestrator task.
- **Fallback cycles are not validated.** `on_failure_step_order` may point to the same or an earlier step, and the orchestrator has no guard against a repeating failure loop.
- **Polling can exceed the API rate limit.** Viewing a running job makes about 66 requests per minute (status 30, logs 30, list 6), and a workflow run view about 80, against a 60 r/m limit per client IP with a burst of 20. This is calculated, not measured.

### Security and production readiness

- **WebSockets are unauthenticated.** `/ws/nodes` and `/ws/workflow-runs/{run_id}` do not check the auth cookie.
- **Registration is open.** Anyone who can reach the API can create an `operator` account.
- **Vault runs in dev mode.** Compose uses in-memory storage and a static root token, so secrets are lost on restart. `dev/local.sh` re-seeds them.
- **SSH host keys are not verified**, by either Ansible or the health probe.
- **Default secrets and test targets.** `JWT_SECRET_KEY` and the database and Vault credentials have insecure defaults, and the base Compose file starts the test node containers.
- **Plain HTTP.** The Nginx config serves only port 80, while auth cookies are marked `Secure` when `DEBUG` is off. TLS must be terminated in front of it for login to work outside `localhost`.
