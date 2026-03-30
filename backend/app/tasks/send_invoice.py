from app.tasks.celery_app import celery_app
import logging

logger = logging.getLogger(__name__)


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
        import asyncio
        from sqlalchemy import text
        from app.db.session import AsyncSessionLocal
        from app.services.invoice_engine import (
            generate_pdf, upload_pdf_to_s3, send_invoice_email
        )

        async def _process():
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

        asyncio.run(_process())

    except Exception as exc:
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)