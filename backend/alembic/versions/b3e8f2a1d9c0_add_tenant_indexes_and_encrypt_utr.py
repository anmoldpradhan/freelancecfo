"""add tenant indexes and encrypt utr column

Revision ID: b3e8f2a1d9c0
Revises: 56e1deed04bf
Create Date: 2026-04-04 00:00:00.000000

Adds performance indexes to all existing tenant schemas:
  - transactions(date DESC)       -- primary list query sort
  - transactions(category_id)     -- category filter
  - invoices(status)              -- status filter
  - invoices(due_date)            -- overdue check + scheduled tasks

Also widens utr_number to TEXT to accommodate Fernet-encrypted values.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3e8f2a1d9c0'
down_revision: Union[str, None] = '56e1deed04bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Widen utr_number to TEXT for Fernet-encrypted values
    op.alter_column('financial_profiles', 'utr_number',
                    existing_type=sa.String(255),
                    type_=sa.Text(),
                    existing_nullable=True)

    # Apply indexes to every existing tenant schema
    result = conn.execute(sa.text("SELECT tenant_schema FROM users"))
    schemas = [row[0] for row in result.fetchall()]

    for schema in schemas:
        conn.execute(sa.text(f"""
            CREATE INDEX IF NOT EXISTS idx_transactions_date
            ON "{schema}".transactions (date DESC)
        """))
        conn.execute(sa.text(f"""
            CREATE INDEX IF NOT EXISTS idx_transactions_category
            ON "{schema}".transactions (category_id)
        """))
        conn.execute(sa.text(f"""
            CREATE INDEX IF NOT EXISTS idx_invoices_status
            ON "{schema}".invoices (status)
        """))
        conn.execute(sa.text(f"""
            CREATE INDEX IF NOT EXISTS idx_invoices_due_date
            ON "{schema}".invoices (due_date)
        """))


def downgrade() -> None:
    conn = op.get_bind()

    op.alter_column('financial_profiles', 'utr_number',
                    existing_type=sa.Text(),
                    type_=sa.String(255),
                    existing_nullable=True)

    result = conn.execute(sa.text("SELECT tenant_schema FROM users"))
    schemas = [row[0] for row in result.fetchall()]

    for schema in schemas:
        conn.execute(sa.text(f'DROP INDEX IF EXISTS "{schema}".idx_transactions_date'))
        conn.execute(sa.text(f'DROP INDEX IF EXISTS "{schema}".idx_transactions_category'))
        conn.execute(sa.text(f'DROP INDEX IF EXISTS "{schema}".idx_invoices_status'))
        conn.execute(sa.text(f'DROP INDEX IF EXISTS "{schema}".idx_invoices_due_date'))
