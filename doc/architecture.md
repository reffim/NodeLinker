# NodeLinker Architecture Design

## Overview

NodeLinker는 Ansible Automation Platform(AWX/Tower)의 역할을 수행하면서, devtron과 유사한 노드 모니터링 UI를 제공하는 웹 기반 인프라 자동화 플랫폼이다.

---

## Minimum Requirements Mapping

| # | Requirement | Component |
|---|-------------|-----------|
| 1 | Node list + status monitoring (devtron-like) | Node Manager + WebSocket live status |
| 2 | Ansible playbook management (CRUD) | Playbook Registry |
| 3 | Select nodes → run playbook | Job Dispatcher |
| 4 | Real-time job tracking (which playbook on which node) | Job Tracker + Job Log Streamer |
| 5 | Mutual-exclusion control per node | Distributed Lock / Job Scheduler |
| 6 | Own account management + OIDC (web access) | Auth Service (local + OIDC) |
| 7 | Secure SSH credential management | Secret Manager (HashiCorp Vault) |

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Browser (SPA)                        │
│   React + React Query + Zustand + shadcn/ui + Tailwind CSS  │
│   - Node Dashboard  - Playbook Editor  - Job Monitor        │
└────────────────────────┬────────────────────────────────────┘
                         │ REST / WebSocket
┌────────────────────────▼────────────────────────────────────┐
│                    API Gateway (FastAPI)                    │
│   /api/v1/*   - Auth middleware - Rate limiting             │
│   WebSocket /ws/jobs/{job_id}  /ws/nodes                    │
└──┬──────────────┬───────────────┬──────────────┬────────────┘
   │              │               │              │
┌──▼───┐   ┌──────▼──────┐   ┌────▼─────┐  ┌─────▼──────┐
│ Auth │   │   Node Mgr  │   │Playbook  │  │  Job Svc   │
│ Svc  │   │  (Inventory)│   │Registry  │  │            │
│      │   │             │   │          │  │ Dispatcher │
│Local │   │async health │   │Git-      │  │ Tracker    │
│+OIDC │   │probe        │   │backed or │  │ Log Stream │
└──┬───┘   └──────┬──────┘   │local FS  │  └─────┬──────┘
   │              │          └─────┬────┘        │
   │              │                │             │
┌──▼──────────────▼────────────────▼─────────────▼───────────┐
│                       PostgreSQL                           │
│  users / sessions / nodes / credentials / playbooks / jobs │
└────────────────────────────────────────────────────────────┘
                         │
┌────────────────────────▼───────────────────────────────────┐
│                        Redis                               │
│  - Node distributed locks (mutual exclusion per node)      │
│  - Job status pub/sub (WebSocket fan-out)                  │
│  - Session cache                                           │
└────────────────────────────────────────────────────────────┘
           │                                 │
┌──────────▼──────────┐  ┌───────────────────▼────────────────┐
│  HashiCorp Vault    │  │  Object Storage (S3 / Local FS)    │
│  - SSH keys/creds   │  │  - Compressed job log archives     │
│  - Ansible secrets  │  │  - Playbook artifacts              │
└─────────────────────┘  └────────────────────────────────────┘
                         │
┌────────────────────────▼───────────────────────────────────┐
│               Ansible Runner (ansible-runner)              │
│  - Subprocess isolation per job                            │
│  - Artifact collection → Object Storage                    │
│  - Runs inside Job Service worker (Celery worker)          │
└────────────────────────────────────────────────────────────┘
```

---

## Software Stack

### Backend
| Layer | Technology | Rationale |
|-------|-----------|-----------|
| API Framework | **FastAPI** (Python 3.12) | Async-native, WebSocket support, auto OpenAPI docs |
| Task Queue | **Celery** + Redis broker | Distributed job execution, retry, concurrency control |
| Ansible Execution | **ansible-runner** | Official Ansible project library for subprocess-safe execution |
| ORM | **SQLAlchemy 2.x** (async) + Alembic | Mature Python ORM, migration support |
| DB | **PostgreSQL 16** | Relational integrity for jobs/nodes/playbooks |
| Cache / PubSub / Locks | **Redis 7** | Distributed lock (SETNX/EXPIRE) for node mutex; job status pub/sub |
| Secret Manager | **HashiCorp Vault** (or similar) | Secure storage for SSH credentials |
| Auth | **python-jose** (JWT) + **Authlib** (OIDC client) | Local JWT sessions + standard OIDC code flow |
| WebSocket | FastAPI native WebSocket | Real-time job log streaming and node status push |

### Frontend
| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Framework | **React 18** + TypeScript | Industry standard, strong ecosystem |
| Build | **Vite** | Fast dev/build cycle |
| UI Components | **shadcn/ui** + Tailwind CSS | Consistent design system, accessible |
| State | **Zustand** (global) + **React Query** (server state) | Lightweight, no boilerplate |
| Real-time | Native WebSocket + React Query invalidation | Job logs, node status live updates |
| Routing | **React Router v6** | SPA routing |

### Infrastructure / DevOps
| Layer | Technology |
|-------|-----------|
| Containerization | Docker + Docker Compose (dev) |
| Process supervision | systemd or Docker for prod |
| Reverse proxy | Nginx (static serving + API proxy) |
| SSH connectivity | asyncssh / aioping (health probe) / Ansible SSH |

---

## Key Design Decisions

### 1. Mutual Exclusion (Requirement 5)
Before dispatching a job, the Job Service acquires a Redis distributed lock keyed by `node:{node_id}:exclusive:{playbook_group}` with a designated TTL. To prevent deadlocks from worker crashes, a background heartbeat mechanism extends the lock's TTL while the job is actively running. If the lock is already held, the job is queued (Celery) until the lock is released. Playbooks are tagged with an `exclusive_group`; jobs with the same group on the same node are serialized.

### 2. Node Status Monitoring (Requirement 1)
An asynchronous background worker (using Python `asyncio` + `asyncssh` / `aioping`) runs health probes every 30 seconds per node. This non-blocking approach ensures high scalability even with thousands of nodes, avoiding worker thread depletion. Status (`online`, `offline`, `unreachable`) is written to PostgreSQL and published to Redis pub/sub. The WebSocket `/ws/nodes` endpoint fans out status changes to all connected browser clients.

### 3. Real-time Job Log Streaming & Storage (Requirement 4)
ansible-runner writes stdout to artifact files. A file-tail watcher (Python `asyncio` + `aiofiles`) reads new lines and publishes them to Redis pub/sub channel `job:{job_id}:logs`. The WebSocket `/ws/jobs/{job_id}` endpoint subscribes and pushes lines to the browser. Upon job completion, the log files are compressed and uploaded to an Object Storage (e.g., S3) or Local FS, and the file URL is saved in the DB. This prevents relational database bloat from storing massive log lines.

### 4. Playbook Storage (Requirement 2)
Two options supported:
- **Local FS**: Playbooks stored under a managed directory, edited in-browser (Monaco editor)
- **Git-backed**: Optional Git repo URL; NodeLinker clones/pulls on sync

### 5. OIDC Integration (Requirement 6)
Auth service supports:
- Local accounts: bcrypt-hashed passwords, JWT access tokens (15min) + refresh tokens (7d) in HttpOnly cookies
- OIDC: Authorization Code flow. Callback exchanges code for id_token, creates/maps local user record, issues same JWT session

---

## Data Model (Core Tables)

```sql
-- Nodes
nodes(id, name, host, port, ssh_user, credential_id, status, last_seen_at, tags, created_at)

-- Credentials (metadata only; actual secrets stored in Vault)
credentials(id, name, type, vault_path, created_by, created_at, updated_at)
-- type: 'ssh_key' | 'ssh_password' | 'vault_token' etc.

-- Playbooks
playbooks(id, name, description, content, source_type, git_url, git_ref, exclusive_group, created_at, updated_at)

-- Jobs
jobs(id, playbook_id, status, created_by, started_at, finished_at, exclusive_lock_key, created_at)

-- Job-Node mapping (log_file_url points to Object Storage / Local FS)
job_nodes(job_id, node_id, status, exit_code, log_file_url)

-- Job logs: Real-time logs are streamed via Redis pub/sub.
-- Persistent logs are compressed and stored in Object Storage (S3) or Local FS.
-- No line-by-line storage in RDBMS to prevent database bloat.

-- Users
users(id, username, email, password_hash, oidc_sub, oidc_provider, role, created_at)
```

---

## Directory Structure (Monorepo)

```
nodelinker/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI routers (auth, nodes, playbooks, jobs)
│   │   ├── core/         # Config, security, OIDC client, Vault integration
│   │   ├── db/           # Database session and connection management
│   │   ├── models/       # SQLAlchemy models
│   │   ├── schemas/      # Pydantic schemas
│   │   ├── services/     # Business logic (job_service, node_service, lock_service)
│   │   ├── worker/       # Celery tasks and Async workers (job runner, health probe)
│   │   └── ws/           # WebSocket endpoints
│   ├── alembic/          # DB migrations
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/   # UI components
│   │   ├── pages/        # Route pages (Nodes, Playbooks, Jobs)
│   │   ├── api/          # API client (axios + React Query hooks)
│   │   ├── hooks/        # Custom React hooks
│   │   ├── lib/          # Utility libraries
│   │   ├── types/        # TypeScript type definitions
│   │   └── stores/       # Zustand stores
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml
└── nginx/
    └── nginx.conf
```

---

## Implementation Phases (suggested)

| Phase | Scope |
|-------|-------|
| 1 | DB schema + Auth (local + OIDC) + basic API skeleton |
| 2 | Vault integration + Credential model + SSH key management |
| 3 | Node inventory + async health probe + node status WebSocket |
| 4 | Playbook CRUD + ansible-runner integration (single node) |
| 5 | Multi-node job dispatch + Job Tracker + log streaming WS |
| 6 | Object Storage setup + job log archival pipeline |
| 7 | Mutual exclusion (Redis lock with TTL/heartbeat) + exclusive group enforcement |
| 8 | Frontend SPA: Node dashboard, Playbook editor, Job monitor |
| 9 | Docker Compose packaging + Nginx + production hardening |