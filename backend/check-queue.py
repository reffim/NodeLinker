import redis
import json
from app.core.config import settings

r = redis.Redis.from_url(settings.REDIS_URL)
print(f"REDIS_URL: {settings.REDIS_URL}")
print(f"Celery queue length: {r.llen('celery')}")

tasks = r.lrange('celery', 0, -1)
for i, task in enumerate(tasks):
    task_data = json.loads(task)
    headers = task_data.get('headers', {})
    print(f"Task {i}: {headers.get('task')}")
