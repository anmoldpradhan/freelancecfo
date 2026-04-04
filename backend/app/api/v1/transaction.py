import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from typing import Optional
from datetime import date

from celery.result import AsyncResult

from app.core.dependencies import get_db, get_current_user
from app.models.user import User
from app.schemas.transaction import (
    TransactionCreate, TransactionResponse,
    TransactionConfirm, ImportResponse
)
from app.tasks.parse_statement import parse_csv_task, parse_pdf_task
from app.tasks.celery_app import celery_app

router = APIRouter(prefix="/api/v1/transactions", tags=["transactions"])


@router.get("", response_model=list[TransactionResponse])
async def list_transactions(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    category_id: Optional[uuid.UUID] = None,
    source: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    schema = current_user.tenant_schema
    offset = (page - 1) * page_size

    # Build filter clauses dynamically
    filters = []
    params = {"limit": page_size, "offset": offset}

    if category_id:
        filters.append("category_id = :category_id")
        params["category_id"] = str(category_id)
    if source:
        filters.append("source = :source")
        params["source"] = source
    if date_from:
        filters.append("date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        filters.append("date <= :date_to")
        params["date_to"] = date_to

    where_clause = "WHERE " + " AND ".join(filters) if filters else ""

    result = await db.execute(text(f"""
        SELECT id, date, description, amount, currency,
               category_id, confidence, source, is_confirmed, notes
        FROM "{schema}".transactions
        {where_clause}
        ORDER BY date DESC, created_at DESC
        LIMIT :limit OFFSET :offset
    """), params)

    rows = result.fetchall()
    return [TransactionResponse(
        id=r.id,
        date=r.date,
        description=r.description,
        amount=r.amount,
        currency=r.currency,
        category_id=r.category_id,
        confidence=r.confidence,
        source=r.source,
        is_confirmed=r.is_confirmed,
        notes=r.notes,
    ) for r in rows]


@router.post("", response_model=TransactionResponse, status_code=201)
async def create_transaction(
    payload: TransactionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    schema = current_user.tenant_schema

    try:
        result = await db.execute(text(f"""
            INSERT INTO "{schema}".transactions
                (date, description, amount, currency,
                 category_id, source, notes, is_confirmed, confidence)
            VALUES
                (:date, :description, :amount, :currency,
                 :category_id, :source, :notes, TRUE, 1.000)
            RETURNING id, date, description, amount, currency,
                      category_id, confidence, source, is_confirmed, notes
        """), {
            "date": payload.date,
            "description": payload.description,
            "amount": float(payload.amount),
            "currency": payload.currency,
            "category_id": str(payload.category_id) if payload.category_id else None,
            "source": payload.source,
            "notes": payload.notes,
        })
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="category_id does not exist")

    row = result.fetchone()

    return TransactionResponse(
        id=row.id,
        date=row.date,
        description=row.description,
        amount=row.amount,
        currency=row.currency,
        category_id=row.category_id,
        confidence=row.confidence,
        source=row.source,
        is_confirmed=row.is_confirmed,
        notes=row.notes,
    )


@router.patch("/{transaction_id}/confirm", response_model=TransactionResponse)
async def confirm_transaction(
    transaction_id: uuid.UUID,
    payload: TransactionConfirm,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """User confirms or corrects the AI-suggested category."""
    schema = current_user.tenant_schema

    try:
        result = await db.execute(text(f"""
            UPDATE "{schema}".transactions
            SET category_id = :category_id,
                is_confirmed = TRUE,
                confidence = 1.000
            WHERE id = :id
            RETURNING id, date, description, amount, currency,
                      category_id, confidence, source, is_confirmed, notes
        """), {
            "category_id": str(payload.category_id),
            "id": str(transaction_id),
        })
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="category_id does not exist")

    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return TransactionResponse(
        id=row.id,
        date=row.date,
        description=row.description,
        amount=row.amount,
        currency=row.currency,
        category_id=row.category_id,
        confidence=row.confidence,
        source=row.source,
        is_confirmed=row.is_confirmed,
        notes=row.notes,
    )


@router.post("/import/csv", response_model=ImportResponse, status_code=202)
async def import_csv(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """
    Accepts a CSV file, hands it to Celery for async processing.
    Returns immediately with a task_id — client polls for completion.
    202 Accepted = "I've received this and am working on it"
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv")

    contents = await file.read()

    # Celery can't serialise raw bytes — encode as hex string
    task = parse_csv_task.delay(
        contents.hex(),
        current_user.tenant_schema,
        str(current_user.id),
    )

    return ImportResponse(
        task_id=task.id,
        message=f"Processing {file.filename}. Check /tasks/{task.id} for status.",
    )


@router.post("/import/pdf", response_model=ImportResponse, status_code=202)
async def import_pdf(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a .pdf")

    contents = await file.read()

    task = parse_pdf_task.delay(
        contents.hex(),
        current_user.tenant_schema,
        str(current_user.id),
    )

    return ImportResponse(
        task_id=task.id,
        message=f"Processing {file.filename}. Check /tasks/{task.id} for status.",
    )


@router.get("/tasks/{task_id}")
async def get_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Polls Celery task status for CSV/PDF import jobs.
    Frontend calls this after receiving task_id from import endpoint.
    """
    result = AsyncResult(task_id, app=celery_app)

    if result.state == "PENDING":
        return {"task_id": task_id, "status": "pending", "result": None}
    elif result.state == "SUCCESS":
        return {"task_id": task_id, "status": "complete", "result": result.result}
    elif result.state == "FAILURE":
        return {"task_id": task_id, "status": "failed",
                "result": str(result.result)}
    else:
        return {"task_id": task_id, "status": result.state, "result": None}
    

@router.get("/categories")
async def list_categories(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns all categories for this tenant."""
    schema = current_user.tenant_schema
    result = await db.execute(text(f"""
        SELECT id, name, type, is_system
        FROM "{schema}".categories
        ORDER BY type, name
    """))
    rows = result.fetchall()
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "type": r.type,
            "is_system": r.is_system,
        }
        for r in rows
    ]


@router.post("/categories", status_code=201)
async def create_category(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Creates a custom category for this tenant."""
    schema = current_user.tenant_schema
    name = payload.get("name", "").strip()
    cat_type = payload.get("type", "expense")

    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if cat_type not in ("income", "expense"):
        raise HTTPException(status_code=400, detail="Type must be income or expense")

    result = await db.execute(text(f"""
        INSERT INTO "{schema}".categories (name, type, is_system)
        VALUES (:name, :type, FALSE)
        RETURNING id, name, type, is_system
    """), {"name": name, "type": cat_type})
    await db.commit()
    row = result.fetchone()
    return {"id": str(row.id), "name": row.name,
            "type": row.type, "is_system": row.is_system}