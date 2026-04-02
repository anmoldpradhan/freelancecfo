"""
Weekly digest — sent every Monday at 8am.
Summarises last 7 days: income, expenses, new invoices, outstanding balance.
One email per active user.
"""
import asyncio
import logging
from datetime import date, timedelta
from sqlalchemy import text
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _make_session_factory():
    """Creates a fresh async engine + session factory for each asyncio.run() call.
    Never reuse a module-level engine across Celery tasks — the event loop changes."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from app.core.config import settings
    engine = create_async_engine(settings.database_url)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


@celery_app.task(name="tasks.weekly_digest", bind=True, max_retries=2)
def weekly_digest(self):
    """Sends weekly financial summary to all active users."""
    try:
        asyncio.run(_send_all_digests())
    except Exception as exc:
        logger.error("Weekly digest failed: %s", exc)
        raise self.retry(exc=exc, countdown=300)


async def _send_all_digests():
    AsyncSessionLocal, engine = _make_session_factory()
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(text("""
                SELECT u.id, u.email, u.tenant_schema, fp.trading_name
                FROM public.users u
                JOIN public.financial_profiles fp ON fp.user_id = u.id
                WHERE u.is_active = TRUE
            """))
            users = result.fetchall()
    finally:
        await engine.dispose()

    for user in users:
        try:
            await _send_user_digest(
                user_id=str(user.id),
                email=user.email,
                tenant_schema=user.tenant_schema,
                trading_name=user.trading_name or "Freelancer",
            )
        except Exception as e:
            logger.error("Digest failed for user %s: %s", user.id, e)


async def _send_user_digest(
    user_id: str,
    email: str,
    tenant_schema: str,
    trading_name: str,
):
    seven_days_ago = date.today() - timedelta(days=7)
    AsyncSessionLocal, engine = _make_session_factory()
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(text(f"""
                SELECT
                    COALESCE(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0)
                        AS week_income,
                    COALESCE(SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END), 0)
                        AS week_expenses,
                    COUNT(*) AS tx_count
                FROM "{tenant_schema}".transactions
                WHERE date >= :start
            """), {"start": seven_days_ago})
            row = result.fetchone()

            inv_result = await db.execute(text(f"""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'sent') AS sent_count,
                    COUNT(*) FILTER (WHERE status = 'overdue') AS overdue_count,
                    COALESCE(SUM(total) FILTER (
                        WHERE status IN ('sent', 'overdue')
                    ), 0) AS outstanding
                FROM "{tenant_schema}".invoices
            """))
            inv = inv_result.fetchone()
    finally:
        await engine.dispose()

    week_income = float(row.week_income)
    week_expenses = float(row.week_expenses)
    net = week_income - week_expenses
    outstanding = float(inv.outstanding)
    overdue_count = int(inv.overdue_count)

    subject = "Your FreelanceCFO Weekly Digest"

    body = f"""
    <h2>Weekly Summary — {trading_name}</h2>
    <p><strong>Period:</strong> {seven_days_ago} to {date.today()}</p>

    <h3>This Week</h3>
    <ul>
      <li>Income: <strong>£{week_income:,.2f}</strong></li>
      <li>Expenses: <strong>£{week_expenses:,.2f}</strong></li>
      <li>Net: <strong>£{net:,.2f}</strong></li>
      <li>Transactions recorded: {int(row.tx_count)}</li>
    </ul>

    <h3>Invoices</h3>
    <ul>
      <li>Outstanding: £{outstanding:,.2f}</li>
      <li>Overdue: {overdue_count}</li>
    </ul>

    {"<p>⚠️ <strong>You have overdue invoices — consider sending a reminder.</strong></p>" if overdue_count > 0 else ""}

    <p><a href="http://localhost:3000">Open FreelanceCFO Dashboard</a></p>
    """

    _send_email(to_email=email, subject=subject, html_body=body)
    logger.info("Weekly digest sent to %s", email)


def _send_email(to_email: str, subject: str, html_body: str):
    """Sends email via SendGrid. Skips if not configured."""
    from app.core.config import settings
    if not settings.sendgrid_api_key:
        logger.warning("SendGrid not configured — digest email skipped for %s", to_email)
        return

    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail

    message = Mail(
        from_email="digest@freelancecfo.com",
        to_emails=to_email,
        subject=subject,
        html_content=html_body,
    )
    sg = SendGridAPIClient(settings.sendgrid_api_key)
    response = sg.send(message)
    logger.info("Email sent | to=%s status=%d", to_email, response.status_code)
