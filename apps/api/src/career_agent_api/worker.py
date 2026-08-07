import os

from celery import Celery

celery_app = Celery(
    "career_agent_api",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    enable_utc=True,
    timezone="UTC",
    task_track_started=True,
)


@celery_app.task(name="career_agent.health")
def health() -> dict[str, str]:
    """Infrastructure-only smoke task; it accepts and returns no user data."""
    return {"status": "ok"}
