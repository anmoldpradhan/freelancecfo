from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "freelancecfo",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Europe/London",
    enable_utc=True,
)

# Auto-discover tasks in the tasks/ directory
celery_app.autodiscover_tasks(["app.tasks"])