import uuid

from fastapi import WebSocket
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.v1.router import router as v1_router
from app.api.v1.nodes import node_status_ws
from app.ws.jobs import job_log_ws
from app.ws.workflow_runs import workflow_run_ws

app = FastAPI(
    title=settings.APP_NAME,
    description="NodeLinker – Infrastructure Automation Platform",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router)

# WebSocket endpoints (canonical paths per architecture spec)
app.add_api_websocket_route("/ws/nodes", node_status_ws)


@app.websocket("/ws/jobs/{job_id}")
async def job_log_websocket(websocket: WebSocket, job_id: uuid.UUID) -> None:
    await job_log_ws(websocket, job_id)


@app.websocket("/ws/workflow-runs/{run_id}")
async def workflow_run_websocket(websocket: WebSocket, run_id: uuid.UUID) -> None:
    await workflow_run_ws(websocket, run_id)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
