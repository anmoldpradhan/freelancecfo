import uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def generate_tenant_schema() -> str:
    """Creates a unique schema name like tenant_a3f2b1c4d5e6..."""
    return f"tenant_{uuid.uuid4().hex}"


async def provision_tenant_schema(schema_name: str, db: AsyncSession) -> None:
    """
    Creates the private schema for a new user and all their tables.
    Called once during registration — never again for that user.
    """
    # CREATE SCHEMA IF NOT EXISTS is safe to call multiple times
    await db.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))

    # Transactions table
    await db.execute(text(f"""
        CREATE TABLE IF NOT EXISTS "{schema_name}".categories (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(100) NOT NULL,
            type VARCHAR(10) NOT NULL CHECK (type IN ('income', 'expense')),
            is_system BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """))

    await db.execute(text(f"""
        CREATE TABLE IF NOT EXISTS "{schema_name}".transactions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            date DATE NOT NULL,
            description TEXT,
            amount NUMERIC(12,2) NOT NULL,
            currency VARCHAR(3) DEFAULT 'GBP',
            category_id UUID REFERENCES "{schema_name}".categories(id),
            confidence NUMERIC(4,3) DEFAULT 1.000,
            source VARCHAR(20) DEFAULT 'manual'
                CHECK (source IN ('stripe','csv','pdf','manual')),
            stripe_payment_id VARCHAR(255),
            is_confirmed BOOLEAN DEFAULT FALSE,
            notes TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """))

    await db.execute(text(f"""
        CREATE TABLE IF NOT EXISTS "{schema_name}".invoices (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            invoice_number VARCHAR(50) UNIQUE NOT NULL,
            client_name VARCHAR(255) NOT NULL,
            client_email VARCHAR(255),
            line_items JSONB DEFAULT '[]',
            subtotal NUMERIC(12,2) DEFAULT 0,
            tax_rate NUMERIC(5,2) DEFAULT 0,
            total NUMERIC(12,2) DEFAULT 0,
            currency VARCHAR(3) DEFAULT 'GBP',
            status VARCHAR(20) DEFAULT 'draft'
                CHECK (status IN ('draft','sent','paid','overdue','void')),
            issued_date DATE,
            due_date DATE,
            paid_date DATE,
            pdf_s3_key VARCHAR(500),
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """))

    await db.execute(text(f"""
        CREATE TABLE IF NOT EXISTS "{schema_name}".tax_estimates (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tax_year VARCHAR(10) NOT NULL,
            gross_income NUMERIC(12,2) DEFAULT 0,
            allowable_expenses NUMERIC(12,2) DEFAULT 0,
            net_profit NUMERIC(12,2) DEFAULT 0,
            income_tax NUMERIC(12,2) DEFAULT 0,
            ni_class2 NUMERIC(12,2) DEFAULT 0,
            ni_class4 NUMERIC(12,2) DEFAULT 0,
            total_liability NUMERIC(12,2) DEFAULT 0,
            vat_rolling_12m NUMERIC(12,2) DEFAULT 0,
            calculated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """))

    await db.execute(text(f"""
        CREATE TABLE IF NOT EXISTS "{schema_name}".cfo_conversations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            messages JSONB DEFAULT '[]',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """))

    await db.execute(text(f"""
        CREATE TABLE IF NOT EXISTS "{schema_name}".cash_flow_forecasts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            forecast_date DATE NOT NULL,
            projected_income NUMERIC(12,2) DEFAULT 0,
            projected_expenses NUMERIC(12,2) DEFAULT 0,
            confidence NUMERIC(4,3) DEFAULT 0.500,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """))

    # Seed default categories for this tenant
    await db.execute(text(f"""
        INSERT INTO "{schema_name}".categories (name, type, is_system) VALUES
            ('Client Income', 'income', TRUE),
            ('Freelance Payment', 'income', TRUE),
            ('Software & Subscriptions', 'expense', TRUE),
            ('Office & Equipment', 'expense', TRUE),
            ('Travel', 'expense', TRUE),
            ('Marketing', 'expense', TRUE),
            ('Professional Fees', 'expense', TRUE),
            ('Uncategorised', 'expense', TRUE)
        ON CONFLICT DO NOTHING
    """))

    await db.commit()