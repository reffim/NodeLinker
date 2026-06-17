# DB Log Chunking Design

**Date:** 2026-06-05
**Project:** NodeLinker (project_minerva)
**Branch:** feature/workflow
**Status:** Approved

---

## Summary

Replace the current Redis pub/sub + gzip file log system with a PostgreSQL-backed chunked log table. Logs are buffered in memory for 1.5 seconds, then flushed as a single row. The frontend polls a REST endpoint every 2 seconds for new chunks. Both the job monitor and workflow run monitor use the same `LogPanel` component with no code path differences.

---

## Motivation

The current system has two code paths (real-time WebSocket and archived gzip fallback), which causes missed-log edge cases and complex frontend logic. Storing logs in the DB gives a single durable source of truth, removes Redis as a log dependency, and eliminates the dual-mode display logic in the frontend.

---

## DB Schema

New table `job_log_chunks`:

```sql
CREATE TABLE job_log_chunks (
    id         BIGSERIAL PRIMARY KEY,
    job_id     UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    node_id    UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    chunk_seq  INTEGER NOT NULL,
    content    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (job_id, node_id, chunk_seq)
);
CREATE INDEX ON job_log_chunks (job_id, node_id, chunk_seq);
```

- `id` (bigserial): polling cursor — frontend queries `id > last_seen_id`
- `chunk_seq`: per-(job, node) counter; used for ordering and debugging
- `content`: newline-joined log lines for the chunk
- `node_id`: which node produced the logs — NOT NULL since every job runs on a specific node

`JobNode.log_file_url` column is removed entirely. The gzip file storage system is removed.

---

## Backend Changes

### job_runner.py

**Remove:**
- Redis `publish(f"job:{job_id}:logs", ...)` calls
- `_save_logs_to_storage()` — gzip compress and file write
- `JobNode.log_file_url` update code

**Add:**
- `_stream_and_chunk_logs(job_id, node_id, stdout_path)` — tails ansible-runner stdout, buffers lines, flushes to `job_log_chunks` every 1.5 seconds via async SQLAlchemy session. Final flush after ansible-runner exits to capture remaining buffered lines.

Flush logic:
1. Read lines from ansible-runner stdout asynchronously (0.05s sleep between reads)
2. Append each line to an in-memory buffer
3. Every 1.5 seconds (or on EOF), if buffer is non-empty: INSERT one `job_log_chunks` row, increment `chunk_seq`, clear buffer
4. On EOF: final flush of any remaining lines, then return

### New API endpoint

```
GET /api/v1/jobs/{job_id}/logs/chunks
```

Query params:
- `after` (int, default 0): return only chunks with `id > after`
- `node_id` (UUID, optional): filter to a specific node

Response: `list[JobLogChunkResponse]`

```python
class JobLogChunkResponse(BaseModel):
    id: int
    job_id: UUID
    node_id: UUID
    chunk_seq: int
    content: str
    created_at: datetime
```

### Removed endpoints

- `GET /api/v1/jobs/{job_id}/nodes/{node_id}/logs/content` — gzip decompress endpoint, no longer needed
- `WebSocket /ws/jobs/{job_id}` — log-only WebSocket, removed entirely

The workflow-run WebSocket (`/ws/workflow-runs/{run_id}`) is unaffected — it carries step lifecycle events, not logs.

---

## Frontend Changes

### New hook: `useJobLogsPoll`

Replaces `useJobLogsWS`. Polls `GET /jobs/{jobId}/logs/chunks?after={lastId}` every 2 seconds. Stops polling when the job reaches a terminal status (`success`, `failed`, `cancelled`). Accumulates lines across chunks for display.

File: `frontend/src/hooks/useJobLogsPoll.ts`

Interface:
```typescript
useJobLogsPoll(jobId: string | undefined): {
  lines: { node_id: string | null; content: string }[]
}
```

Polling stops when:
- `jobId` is undefined, OR
- The job query (keyed `['job', jobId]`) shows a terminal status AND at least one poll has returned empty (confirming no more chunks)

### LogPanel simplification

Remove from `LogPanel`:
- `useJobLogsWS` import and usage
- `staticLines`, `loadingStatic`, `staticLoaded` state variables
- `fetchAllLogs` archive fetch effect
- "Loading archived logs…" display branch

Add:
- `useJobLogsPoll(jobId)` — single hook, single code path

The component becomes stateless with respect to log sourcing: it receives `lines` from the hook and renders them. No difference between running and completed jobs.

### Removed files and functions

| Item | Location |
|------|----------|
| `useJobLogsWS` hook | `frontend/src/hooks/useJobLogsWS.ts` — delete file |
| `getJobNodeLogsContent` | `frontend/src/api/jobs.ts` — remove function |
| `JobLog` interface | `frontend/src/types/index.ts` — remove (was unused) |

### New API client function

```typescript
// frontend/src/api/jobs.ts
getJobLogChunks(jobId: string, after: number): Promise<JobLogChunk[]>
// GET /api/v1/jobs/{jobId}/logs/chunks?after={after}
```

New type in `frontend/src/types/index.ts`:
```typescript
export interface JobLogChunk {
  id: number
  job_id: string
  node_id: string
  chunk_seq: number
  content: string
  created_at: string
}
```

---

## Migration

New Alembic migration: `0005_add_job_log_chunks.py`

- Adds `job_log_chunks` table
- Drops `job_nodes.log_file_url` column
- Existing jobs will show empty log panels (acceptable — old logs are in files no longer served)

---

## What Is Removed

| Component | Reason |
|-----------|--------|
| Redis pub/sub log publishing | Replaced by DB writes |
| `_save_logs_to_storage()` | Replaced by DB writes |
| `job_nodes.log_file_url` | No longer used |
| `WebSocket /ws/jobs/{job_id}` | Replaced by polling |
| `useJobLogsWS.ts` | Replaced by `useJobLogsPoll.ts` |
| `getJobNodeLogsContent` | Replaced by `getJobLogChunks` |
| `JobLog` type | Was unused |

---

## Out of Scope

- Log search or filtering by content
- Log retention/cleanup policy
- Pagination of chunks (all chunks for a job fit in a single response for typical playbook runs)
- Log level tagging
