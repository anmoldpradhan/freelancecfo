"""drop unused cash_flow_forecasts table from all tenant schemas

Revision ID: c4f9e3b2a1d0
Revises: b3e8f2a1d9c0
Create Date: 2026-04-06 00:00:00.000000

The cash_flow_forecasts table was never used — forecasts are computed
on-the-fly from transactions in the forecast service.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4f9e3b2a1d0'
down_revision: Union[str, None] = 'b3e8f2a1d9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(sa.text("SELECT tenant_schema FROM users"))
    schemas = [row[0] for row in result.fetchall()]

    for schema in schemas:
        conn.execute(sa.text(f"""
            DROP TABLE IF EXISTS "{schema}".cash_flow_forecasts
        """))


def downgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(sa.text("SELECT tenant_schema FROM users"))
    schemas = [row[0] for row in result.fetchall()]

    for schema in schemas:
        conn.execute(sa.text(f"""
            CREATE TABLE IF NOT EXISTS "{schema}".cash_flow_forecasts (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                forecast_date DATE NOT NULL,
                projected_income NUMERIC(12,2) DEFAULT 0,
                projected_expenses NUMERIC(12,2) DEFAULT 0,
                confidence NUMERIC(4,3) DEFAULT 0.500,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
