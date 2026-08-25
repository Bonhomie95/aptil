"""Celery application. Broker + result backend on Redis.

The beat schedule below is what actually drives the product loop: without a
periodic trigger, discovery/matching/apply are unreachable code and the shared
job pool stays permanently empty.

Run the scheduler alongside the worker:
    celery -A app.workers.celery_app.celery beat --loglevel=info
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery = Celery(
    "aptil",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.workers.tasks.cv_parsing",
        "app.workers.tasks.email",
        "app.workers.tasks.discovery",
        "app.workers.tasks.apply",
        "app.workers.tasks.sourcing",
        "app.workers.tasks.tailoring",
        "app.workers.tasks.scheduler",
    ],
)

celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    # Browser automation can legitimately take minutes; warn before the hard kill
    # so a task can still record why it stopped.
    task_soft_time_limit=540,
    task_time_limit=600,
    worker_max_tasks_per_child=100,
    # Redeliver a task if the worker dies mid-flight rather than losing it.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    result_expires=3600,
    timezone="UTC",
    enable_utc=True,
)


def _build_beat_schedule() -> dict:
    """Periodic jobs, each disabled by setting its interval to 0."""
    schedule: dict = {}
    # Not gated on sourcing_jobs alone: the shipped default boards and the
    # demand-driven queries are both sources, and requiring the operator to
    # hand-write SOURCING_JOBS_JSON before ANY discovery ran meant a fresh
    # deployment silently discovered nothing, forever.
    has_sources = settings.sourcing_jobs or settings.SOURCING_WEB_SEARCH
    if settings.SOURCING_INTERVAL_MINUTES > 0 and has_sources:
        schedule["sourcing-sweep"] = {
            "task": "scheduler.run_all_sources",
            "schedule": crontab(
                minute=f"*/{min(settings.SOURCING_INTERVAL_MINUTES, 59)}"
            )
            if settings.SOURCING_INTERVAL_MINUTES < 60
            else crontab(minute=0, hour=f"*/{settings.SOURCING_INTERVAL_MINUTES // 60}"),
        }
    if settings.MATCHING_INTERVAL_MINUTES > 0:
        schedule["matching-sweep"] = {
            "task": "scheduler.match_all_users",
            "schedule": crontab(
                minute=f"*/{min(settings.MATCHING_INTERVAL_MINUTES, 59)}"
            )
            if settings.MATCHING_INTERVAL_MINUTES < 60
            else crontab(minute=15, hour=f"*/{settings.MATCHING_INTERVAL_MINUTES // 60}"),
        }
    if settings.APPLY_INTERVAL_MINUTES > 0:
        schedule["apply-sweep"] = {
            "task": "scheduler.enqueue_all_users",
            "schedule": crontab(minute=f"*/{min(settings.APPLY_INTERVAL_MINUTES, 59)}")
            if settings.APPLY_INTERVAL_MINUTES < 60
            else crontab(minute=30, hour=f"*/{settings.APPLY_INTERVAL_MINUTES // 60}"),
        }
        # Continuously clear anything Aptil could not complete, so the dashboard
        # only ever holds real applications.
        schedule["purge-unapplicable"] = {
            "task": "scheduler.purge_unapplicable",
            "schedule": crontab(minute=f"*/{min(settings.APPLY_INTERVAL_MINUTES, 59)}")
            if settings.APPLY_INTERVAL_MINUTES < 60
            else crontab(minute=45, hour=f"*/{settings.APPLY_INTERVAL_MINUTES // 60}"),
        }
    return schedule


celery.conf.beat_schedule = _build_beat_schedule()
