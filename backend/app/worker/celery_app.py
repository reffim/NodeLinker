from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "nodelinker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.worker.tasks.health_probe",
        "app.worker.tasks.job_runner",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "probe-all-nodes": {
            "task": "app.worker.tasks.health_probe.probe_all_nodes",
            "schedule": 30.0,  # every 30 seconds
        },
    },
)
