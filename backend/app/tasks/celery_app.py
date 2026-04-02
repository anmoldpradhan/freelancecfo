from celery import Celery
from celery.schedules import crontab
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
    # ── Beat schedule ─────────────────────────────────────────────────────────
    beat_schedule={
        # Every Monday at 8am London time
        "weekly-digest": {
            "task": "tasks.weekly_digest",
            "schedule": crontab(hour=8, minute=0, day_of_week=1),
        },
        # Every day at 9am — mark overdue invoices + send chase emails
        "check-overdue-invoices": {
            "task": "tasks.check_overdue_invoices",
            "schedule": crontab(hour=9, minute=0),
        },
        # Jan 20 and Jul 20 — payment on account reminders
        "payment-on-account-jan": {
            "task": "tasks.payment_on_account_reminder",
            "schedule": crontab(hour=9, minute=0, day_of_month=20, month_of_year=1),
        },
        "payment-on-account-jul": {
            "task": "tasks.payment_on_account_reminder",
            "schedule": crontab(hour=9, minute=0, day_of_month=20, month_of_year=7),
        },
        # Every Sunday at 7am — VAT threshold check
        "vat-threshold-check": {
            "task": "tasks.vat_threshold_check",
            "schedule": crontab(hour=7, minute=0, day_of_week=0),
        },
    },
)

celery_app.conf.imports = [
    "app.tasks.parse_statement",
    "app.tasks.send_invoice",
    "app.tasks.weekly_digest",
]