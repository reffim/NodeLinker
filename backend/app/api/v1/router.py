from fastapi import APIRouter

from app.api.v1 import auth, jobs, nodes, playbooks

router = APIRouter(prefix="/api/v1")

router.include_router(auth.router)
router.include_router(nodes.router)
router.include_router(playbooks.router)
router.include_router(jobs.router)
