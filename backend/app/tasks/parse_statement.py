from app.tasks.celery_app import celery_app


@celery_app.task(name="parse_statement")
def parse_statement(file_path: str, tenant_schema: str) -> dict:
    """Placeholder — Week 3 will implement CSV/PDF parsing."""
    return {"status": "not_implemented", "file": file_path}