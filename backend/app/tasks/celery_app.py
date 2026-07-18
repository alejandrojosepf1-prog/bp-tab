from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "bp_tab_betting",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.scrape_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "scrape-active-tournaments": {
            "task": "app.tasks.scrape_tasks.scrape_all_active_tournaments",
            "schedule": settings.scrape_interval_seconds,
        },
    },
)
