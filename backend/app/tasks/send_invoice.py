import asyncio
import logging

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _make_session_factory():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from app.core.config import settings
    engine = create_async_engine(settings.database_url)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


@celery_app.task(name="send_invoice", bind=True, max_retries=3)
def send_invoice_task(
    self,
    invoice_id: str,
    tenant_schema: str,
    user_id: str,
):
    """
    Generates PDF, uploads to S3, sends email, updates invoice record.
    Runs async DB calls via asyncio.run() inside the sync Celery task.
    """
    try:
        from sqlalchemy import text
        from app.services.invoice_engine import (
            generate_pdf, upload_pdf_to_s3, send_invoice_email
        )

        async def _process():
            AsyncSessionLocal, engine = _make_session_factory()
            try:
                async with AsyncSessionLocal() as db:
                    # Fetch invoice
                    result = await db.execute(text(f"""
                        SELECT * FROM "{tenant_schema}".invoices
                        WHERE id = :id
                    """), {"id": invoice_id})
                    row = result.fetchone()

                    if not row:
                        logger.error("Invoice %s not found in %s", invoice_id, tenant_schema)
                        return

                    # Fetch trading name from financial profile
                    profile_result = await db.execute(text("""
                        SELECT fp.trading_name FROM public.financial_profiles fp
                        JOIN public.users u ON u.id = fp.user_id
                        WHERE u.tenant_schema = :schema
                    """), {"schema": tenant_schema})
                    profile = profile_result.fetchone()
                    trading_name = profile.trading_name if profile else "FreelanceCFO"

                    invoice_data = {
                        "invoice_number": row.invoice_number,
                        "client_name": row.client_name,
                        "client_email": row.client_email,
                        "line_items": row.line_items,
                        "subtotal": float(row.subtotal),
                        "tax_rate": float(row.tax_rate),
                        "total": float(row.total),
                        "currency": row.currency,
                        "status": row.status,
                        "issued_date": str(row.issued_date) if row.issued_date else "",
                        "due_date": str(row.due_date) if row.due_date else "",
                        "trading_name": trading_name,
                    }

                    # Generate + upload PDF
                    pdf_bytes = generate_pdf(invoice_data)
                    s3_key = upload_pdf_to_s3(pdf_bytes, row.invoice_number)

                    # Send email if client email exists
                    email_sent = False
                    if row.client_email:
                        email_sent = send_invoice_email(
                            to_email=row.client_email,
                            client_name=row.client_name,
                            invoice_number=row.invoice_number,
                            total=float(row.total),
                            currency=row.currency,
                            pdf_bytes=pdf_bytes,
                            trading_name=trading_name,
                        )

                    # Update invoice record
                    new_status = "sent" if email_sent else row.status
                    await db.execute(text(f"""
                        UPDATE "{tenant_schema}".invoices
                        SET pdf_s3_key = :s3_key,
                            status = :status
                        WHERE id = :id
                    """), {
                        "s3_key": s3_key,
                        "status": new_status,
                        "id": invoice_id,
                    })
                    await db.commit()
                    logger.info("Invoice %s processed | email=%s", invoice_id, email_sent)
            finally:
                await engine.dispose()

        asyncio.run(_process())

    except Exception as exc:
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


@celery_app.task(name="tasks.check_overdue_invoices", bind=True, max_retries=2)
def check_overdue_invoices(self):
    """
    Runs daily at 9am.
    Finds all sent invoices past due_date → marks overdue.
    Sends a chase email drafted by Gemini.
    """
    try:
        asyncio.run(_check_all_tenants_overdue())
    except Exception as exc:
        logger.error("Overdue check failed: %s", exc)
        raise self.retry(exc=exc, countdown=300)


async def _check_all_tenants_overdue():
    from sqlalchemy import text
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
            await _process_tenant_overdue(
                str(user.id), user.email,
                user.tenant_schema, user.trading_name or "Freelancer"
            )
        except Exception as e:
            logger.error("Overdue check failed for %s: %s", user.id, e)


async def _process_tenant_overdue(
    user_id: str, email: str,
    tenant_schema: str, trading_name: str
):
    from datetime import date
    from sqlalchemy import text

    today = date.today()
    AsyncSessionLocal, engine = _make_session_factory()
    try:
        async with AsyncSessionLocal() as db:
            # Mark sent invoices past due_date as overdue
            result = await db.execute(text(f"""
                UPDATE "{tenant_schema}".invoices
                SET status = 'overdue'
                WHERE status = 'sent'
                  AND due_date < :today
                RETURNING id, invoice_number, client_name,
                          client_email, total, due_date
            """), {"today": today})
            newly_overdue = result.fetchall()
            await db.commit()
    finally:
        await engine.dispose()

    if not newly_overdue:
        return

    logger.info(
        "%d invoice(s) marked overdue for tenant %s",
        len(newly_overdue), tenant_schema
    )

    # Send chase email for each newly overdue invoice
    for inv in newly_overdue:
        if inv.client_email:
            await _send_chase_email(inv, trading_name)


async def _send_chase_email(invoice, trading_name: str):
    """Sends a polite payment chase email."""
    from app.tasks.weekly_digest import _send_email

    subject = f"Payment Reminder — Invoice {invoice.invoice_number}"
    body = f"""
    <p>Dear {invoice.client_name},</p>
    <p>I hope this message finds you well.</p>
    <p>I'm writing to follow up on invoice
       <strong>{invoice.invoice_number}</strong>
       for <strong>£{float(invoice.total):,.2f}</strong>,
       which was due on <strong>{invoice.due_date}</strong>.</p>
    <p>If you have already sent payment, please disregard this message.
       Otherwise, I'd be grateful if you could arrange payment
       at your earliest convenience.</p>
    <p>Please don't hesitate to get in touch if you have any questions.</p>
    <p>Best regards,<br>{trading_name}</p>
    """
    _send_email(
        to_email=invoice.client_email,
        subject=subject,
        html_body=body,
    )


@celery_app.task(name="tasks.payment_on_account_reminder")
def payment_on_account_reminder():
    """
    Runs Jan 20 and Jul 20.
    Reminds users their payment on account is due in 11 days (Jan 31 / Jul 31).
    """
    asyncio.run(_send_poa_reminders())


async def _send_poa_reminders():
    from sqlalchemy import text
    from app.services.tax_engine import fetch_ytd_figures, build_tax_estimate
    from app.tasks.weekly_digest import _send_email
    from datetime import date

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

            for user in users:
                try:
                    gross, expenses = await fetch_ytd_figures(user.tenant_schema, db)
                    estimate = build_tax_estimate(gross, expenses)
                    jan = float(estimate.payment_on_account_jan)
                    jul = float(estimate.payment_on_account_jul)

                    if jan == 0:
                        continue  # below PoA threshold

                    month = date.today().month
                    due_date = "31 January" if month == 1 else "31 July"
                    amount = jan if month == 1 else jul

                    _send_email(
                        to_email=user.email,
                        subject=f"⏰ Payment on Account Due {due_date}",
                        html_body=f"""
                        <h2>Payment on Account Reminder</h2>
                        <p>Your next payment on account is due on
                           <strong>{due_date}</strong>.</p>
                        <p>Estimated amount:
                           <strong>£{amount:,.2f}</strong></p>
                        <p>This is 50% of your estimated
                           {estimate.tax_year} tax liability.</p>
                        <p>Pay via:
                           <a href="https://www.gov.uk/pay-self-assessment-tax-bill">
                           HMRC online</a></p>
                        """,
                    )
                    logger.info("PoA reminder sent to %s", user.email)
                except Exception as e:
                    logger.error("PoA reminder failed for %s: %s", user.id, e)
    finally:
        await engine.dispose()


@celery_app.task(name="tasks.vat_threshold_check")
def vat_threshold_check():
    """Weekly VAT proximity check — emails users approaching £90k threshold."""
    asyncio.run(_check_all_vat())


async def _check_all_vat():
    from sqlalchemy import text
    from app.services.tax_engine import (
        fetch_rolling_12m_income, calculate_vat_status
    )
    from app.tasks.weekly_digest import _send_email
    from decimal import Decimal

    AsyncSessionLocal, engine = _make_session_factory()
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(text("""
                SELECT u.id, u.email, u.tenant_schema,
                       fp.trading_name, fp.vat_registered
                FROM public.users u
                JOIN public.financial_profiles fp ON fp.user_id = u.id
                WHERE u.is_active = TRUE
            """))
            users = result.fetchall()

            for user in users:
                try:
                    rolling = await fetch_rolling_12m_income(user.tenant_schema, db)
                    vat = calculate_vat_status(rolling, bool(user.vat_registered))

                    if vat.warning_level == "safe":
                        continue  # no email needed

                    messages = {
                        "warning_80": (
                            "⚡ VAT Warning",
                            f"You've used {vat.percentage_used}% of the "
                            f"£90,000 VAT threshold "
                            f"(£{float(rolling):,.2f} rolling 12 months). "
                            f"£{float(vat.amount_remaining):,.2f} remaining."
                        ),
                        "warning_95": (
                            "⚠️ VAT Threshold Alert",
                            f"You've reached {vat.percentage_used}% of the VAT "
                            f"threshold. You may need to register soon. "
                            f"Only £{float(vat.amount_remaining):,.2f} remaining."
                        ),
                        "exceeded": (
                            "🚨 VAT Registration Required",
                            f"Your rolling 12-month income (£{float(rolling):,.2f}) "
                            f"has exceeded the £90,000 VAT threshold. "
                            f"You must register for VAT within 30 days."
                        ),
                    }

                    subject, body_text = messages[vat.warning_level]
                    _send_email(
                        to_email=user.email,
                        subject=subject,
                        html_body=f"<p>{body_text}</p>",
                    )
                    logger.info(
                        "VAT alert sent | user=%s level=%s",
                        user.id, vat.warning_level
                    )
                except Exception as e:
                    logger.error("VAT check failed for %s: %s", user.id, e)
    finally:
        await engine.dispose()
