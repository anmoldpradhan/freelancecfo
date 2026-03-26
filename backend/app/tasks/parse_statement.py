from datetime import date as date_type
from app.tasks.celery_app import celery_app
from app.services.statement_parser import parse_csv, parse_pdf


def _coerce_date(value) -> date_type:
    if isinstance(value, date_type):
        return value
    return date_type.fromisoformat(str(value))


def _make_session_factory():
    """
    Creates a fresh engine + session factory bound to the current event loop.
    Must be called inside asyncio.run() — never at module level.
    """
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from app.core.config import settings
    engine = create_async_engine(settings.database_url)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


@celery_app.task(name="parse_statement_csv", bind=True, max_retries=3)
def parse_csv_task(self, file_bytes_hex: str, tenant_schema: str, user_id: str):
    """
    Parses a CSV file and stores transactions in the tenant schema.
    file_bytes_hex: file contents encoded as hex string (Celery can't send raw bytes)
    bind=True: gives access to self for retry logic
    """
    try:
        from app.services.categoriser import categorise_transactions
        import asyncio
        from sqlalchemy import text

        file_bytes = bytes.fromhex(file_bytes_hex)
        transactions = parse_csv(file_bytes)

        if not transactions:
            return {"status": "complete", "imported": 0, "message": "No transactions found"}

        # Run async DB operations in sync Celery task.
        # Fresh engine created inside asyncio.run() so it binds to the correct loop.
        async def _save():
            SessionLocal, engine = _make_session_factory()
            async with SessionLocal() as db:  # noqa: engine disposed via GC on loop close
                # Fetch categories for this tenant
                result = await db.execute(
                    text(f'SELECT id, name, type FROM "{tenant_schema}".categories')
                )
                categories = [
                    {"id": str(r.id), "name": r.name, "type": r.type}
                    for r in result.fetchall()
                ]

                # Categorise with Claude
                categorised = await categorise_transactions(transactions, categories)

                # Insert into DB
                inserted = 0
                for t in categorised:
                    await db.execute(text(f"""
                        INSERT INTO "{tenant_schema}".transactions
                            (date, description, amount, currency,
                             category_id, confidence, source, is_confirmed)
                        VALUES
                            (:date, :description, :amount, 'GBP',
                             :category_id, :confidence, 'csv',
                             :is_confirmed)
                    """), {
                        "date": _coerce_date(t["date"]),
                        "description": t["description"],
                        "amount": t["amount"],
                        "category_id": t.get("category_id"),
                        "confidence": t.get("confidence", 1.0),
                        # Auto-confirm if Claude is highly confident
                        "is_confirmed": t.get("confidence", 0) >= 0.75,
                    })
                    inserted += 1

                await db.commit()
                return inserted

        count = asyncio.run(_save())
        return {"status": "complete", "imported": count}

    except Exception as exc:
        # Retry up to 3 times with exponential backoff
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


@celery_app.task(name="parse_statement_pdf", bind=True, max_retries=3)
def parse_pdf_task(self, file_bytes_hex: str, tenant_schema: str, user_id: str):
    """Same flow as CSV but uses PDF parser."""
    try:
        from app.services.categoriser import categorise_transactions
        import asyncio
        from sqlalchemy import text

        file_bytes = bytes.fromhex(file_bytes_hex)
        transactions = parse_pdf(file_bytes)

        if not transactions:
            return {"status": "complete", "imported": 0, "message": "No transactions parsed from PDF"}

        async def _save():
            SessionLocal, _ = _make_session_factory()
            async with SessionLocal() as db:
                result = await db.execute(
                    text(f'SELECT id, name, type FROM "{tenant_schema}".categories')
                )
                categories = [
                    {"id": str(r.id), "name": r.name, "type": r.type}
                    for r in result.fetchall()
                ]
                categorised = await categorise_transactions(transactions, categories)

                inserted = 0
                for t in categorised:
                    await db.execute(text(f"""
                        INSERT INTO "{tenant_schema}".transactions
                            (date, description, amount, currency,
                             category_id, confidence, source, is_confirmed)
                        VALUES
                            (:date, :description, :amount, 'GBP',
                             :category_id, :confidence, 'pdf',
                             :is_confirmed)
                    """), {
                        "date": _coerce_date(t["date"]),
                        "description": t["description"],
                        "amount": t["amount"],
                        "category_id": t.get("category_id"),
                        "confidence": t.get("confidence", 1.0),
                        "is_confirmed": t.get("confidence", 0) >= 0.75,
                    })
                    inserted += 1

                await db.commit()
                return inserted

        count = asyncio.run(_save())
        return {"status": "complete", "imported": count}

    except Exception as exc:
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)