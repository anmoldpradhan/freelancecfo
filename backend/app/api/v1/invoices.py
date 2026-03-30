import uuid
from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional
import io
import json

from app.core.dependencies import get_db, get_current_user
from app.models.user import User
from app.schemas.invoice import (
    InvoiceCreate, InvoiceResponse, InvoiceStatusUpdate
)
from app.services.invoice_engine import generate_pdf, download_pdf_from_s3
from app.tasks.send_invoice import send_invoice_task

router = APIRouter(prefix="/api/v1/invoices", tags=["invoices"])


def _generate_invoice_number(tenant_schema: str) -> str:
    """Simple invoice number: INV-{schema_suffix}-{timestamp}"""
    import time
    suffix = tenant_schema.replace("tenant_", "")[:6].upper()
    ts = str(int(time.time()))[-6:]
    return f"INV-{suffix}-{ts}"


def _calculate_totals(line_items: list, tax_rate: Decimal) -> tuple:
    """Returns (subtotal, total) as floats."""
    subtotal = sum(
        float(item.quantity) * float(item.unit_price)
        for item in line_items
    )
    tax_amount = subtotal * float(tax_rate) / 100
    total = subtotal + tax_amount
    return subtotal, total


@router.post("", response_model=InvoiceResponse, status_code=201)
async def create_invoice(
    payload: InvoiceCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    schema = current_user.tenant_schema
    invoice_number = _generate_invoice_number(schema)
    subtotal, total = _calculate_totals(payload.line_items, payload.tax_rate)

    line_items_json = json.dumps([
        {
            "description": item.description,
            "quantity": float(item.quantity),
            "unit_price": float(item.unit_price),
        }
        for item in payload.line_items
    ])

    result = await db.execute(text(f"""
        INSERT INTO "{schema}".invoices
            (invoice_number, client_name, client_email, line_items,
             subtotal, tax_rate, total, currency, status,
             issued_date, due_date)
        VALUES
            (:invoice_number, :client_name, :client_email, CAST(:line_items AS jsonb),
             :subtotal, :tax_rate, :total, :currency, 'draft',
             :issued_date, :due_date)
        RETURNING id, invoice_number, client_name, client_email, line_items,
                  subtotal, tax_rate, total, currency, status,
                  issued_date, due_date, paid_date, pdf_s3_key
    """), {
        "invoice_number": invoice_number,
        "client_name": payload.client_name,
        "client_email": str(payload.client_email) if payload.client_email else None,
        "line_items": line_items_json,
        "subtotal": subtotal,
        "tax_rate": float(payload.tax_rate),
        "total": total,
        "currency": payload.currency,
        "issued_date": payload.issued_date or date.today(),
        "due_date": payload.due_date,
    })

    await db.commit()
    row = result.fetchone()

    # Fire async send task if requested
    if payload.send_immediately and payload.client_email:
        send_invoice_task.delay(
            str(row.id),
            schema,
            str(current_user.id),
        )

    return InvoiceResponse(
        id=row.id,
        invoice_number=row.invoice_number,
        client_name=row.client_name,
        client_email=row.client_email,
        line_items=row.line_items if isinstance(row.line_items, list) else [],
        subtotal=row.subtotal,
        tax_rate=row.tax_rate,
        total=row.total,
        currency=row.currency,
        status=row.status,
        issued_date=row.issued_date,
        due_date=row.due_date,
        paid_date=row.paid_date,
        pdf_s3_key=row.pdf_s3_key,
    )


@router.get("", response_model=list[InvoiceResponse])
async def list_invoices(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    schema = current_user.tenant_schema
    offset = (page - 1) * page_size

    filters = []
    params = {"limit": page_size, "offset": offset}

    if status:
        filters.append("status = :status")
        params["status"] = status

    where = "WHERE " + " AND ".join(filters) if filters else ""

    result = await db.execute(text(f"""
        SELECT id, invoice_number, client_name, client_email, line_items,
               subtotal, tax_rate, total, currency, status,
               issued_date, due_date, paid_date, pdf_s3_key
        FROM "{schema}".invoices
        {where}
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
    """), params)

    rows = result.fetchall()
    return [InvoiceResponse(
        id=r.id,
        invoice_number=r.invoice_number,
        client_name=r.client_name,
        client_email=r.client_email,
        line_items=r.line_items if isinstance(r.line_items, list) else [],
        subtotal=r.subtotal,
        tax_rate=r.tax_rate,
        total=r.total,
        currency=r.currency,
        status=r.status,
        issued_date=r.issued_date,
        due_date=r.due_date,
        paid_date=r.paid_date,
        pdf_s3_key=r.pdf_s3_key,
    ) for r in rows]


@router.get("/{invoice_id}/pdf")
async def get_invoice_pdf(
    invoice_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Streams PDF to browser.
    If S3 key exists: downloads from S3.
    Otherwise: regenerates from DB data on the fly.
    """
    schema = current_user.tenant_schema

    result = await db.execute(text(f"""
        SELECT * FROM "{schema}".invoices WHERE id = :id
    """), {"id": str(invoice_id)})
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if row.pdf_s3_key:
        try:
            pdf_bytes = download_pdf_from_s3(row.pdf_s3_key)
        except Exception:
            pdf_bytes = None
    else:
        pdf_bytes = None

    # Regenerate if S3 not available
    if not pdf_bytes:
        # Fetch sender details from user's financial profile
        profile_result = await db.execute(text("""
            SELECT trading_name
            FROM financial_profiles
            WHERE user_id = :user_id
        """), {"user_id": str(current_user.id)})
        profile = profile_result.fetchone()

        trading_name = profile.trading_name if profile and profile.trading_name else ""

        invoice_data = {
            "invoice_number": row.invoice_number,
            "client_name": row.client_name,
            "client_email": row.client_email,
            "line_items": row.line_items or [],
            "subtotal": float(row.subtotal),
            "tax_rate": float(row.tax_rate),
            "total": float(row.total),
            "currency": row.currency,
            "status": row.status,
            "issued_date": str(row.issued_date) if row.issued_date else "",
            "due_date": str(row.due_date) if row.due_date else "",
            "from_name": trading_name or current_user.email,
            "from_address": "",
            "vat_number": "",
            "trading_name": trading_name,
        }
        pdf_bytes = generate_pdf(invoice_data)

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename={row.invoice_number}.pdf"
        },
    )


@router.patch("/{invoice_id}/status", response_model=InvoiceResponse)
async def update_invoice_status(
    invoice_id: uuid.UUID,
    payload: InvoiceStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    schema = current_user.tenant_schema

    paid_date_clause = ""
    params = {
        "status": payload.status,
        "id": str(invoice_id),
    }

    if payload.status == "paid":
        paid_date_clause = ", paid_date = CURRENT_DATE"

    result = await db.execute(text(f"""
        UPDATE "{schema}".invoices
        SET status = :status {paid_date_clause}
        WHERE id = :id
        RETURNING id, invoice_number, client_name, client_email, line_items,
                  subtotal, tax_rate, total, currency, status,
                  issued_date, due_date, paid_date, pdf_s3_key
    """), params)

    await db.commit()
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Invoice not found")

    return InvoiceResponse(
        id=row.id,
        invoice_number=row.invoice_number,
        client_name=row.client_name,
        client_email=row.client_email,
        line_items=row.line_items if isinstance(row.line_items, list) else [],
        subtotal=row.subtotal,
        tax_rate=row.tax_rate,
        total=row.total,
        currency=row.currency,
        status=row.status,
        issued_date=row.issued_date,
        due_date=row.due_date,
        paid_date=row.paid_date,
        pdf_s3_key=row.pdf_s3_key,
    )


@router.post("/{invoice_id}/send", status_code=202)
async def send_invoice(
    invoice_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Queues invoice for PDF generation + email delivery."""
    schema = current_user.tenant_schema

    result = await db.execute(text(f"""
        SELECT id, status FROM "{schema}".invoices WHERE id = :id
    """), {"id": str(invoice_id)})
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if row.status == "void":
        raise HTTPException(status_code=400, detail="Cannot send a voided invoice")

    task = send_invoice_task.delay(
        str(invoice_id),
        schema,
        str(current_user.id),
    )

    return {"task_id": task.id, "message": "Invoice queued for delivery"}