"""
Builds the financial context block injected into every CFO system prompt.
Pulls real data from the tenant schema — last 90 days transactions,
outstanding invoices, YTD totals, and tax estimate.
"""
import logging
from datetime import date, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)


async def build_financial_context(
    tenant_schema: str,
    db: AsyncSession,
) -> str:
    """
    Returns a formatted string of the user's financial snapshot.
    Safe — returns minimal context on any DB error rather than crashing.
    """
    try:
        today = date.today()
        ninety_days_ago = today - timedelta(days=90)
        tax_year_start = date(today.year, 4, 6) \
            if today.month >= 4 \
            else date(today.year - 1, 4, 6)

        # ── Last 90 days transactions ─────────────────────────────────────────
        tx_result = await db.execute(text(f"""
            SELECT
                SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) as income_90d,
                SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) as expenses_90d,
                COUNT(*) as tx_count,
                AVG(CASE WHEN amount > 0 THEN amount END) as avg_income_tx
            FROM "{tenant_schema}".transactions
            WHERE date >= :start_date
        """), {"start_date": ninety_days_ago})
        tx = tx_result.fetchone()

        # ── YTD totals ────────────────────────────────────────────────────────
        ytd_result = await db.execute(text(f"""
            SELECT
                SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) as ytd_income,
                SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) as ytd_expenses
            FROM "{tenant_schema}".transactions
            WHERE date >= :tax_year_start
        """), {"tax_year_start": tax_year_start})
        ytd = ytd_result.fetchone()

        # ── Top expense categories (90 days, fallback to all-time) ───────────
        cat_result = await db.execute(text(f"""
            SELECT c.name, SUM(ABS(t.amount)) as total
            FROM "{tenant_schema}".transactions t
            JOIN "{tenant_schema}".categories c ON c.id = t.category_id
            WHERE t.amount < 0 AND t.date >= :start_date
            GROUP BY c.name
            ORDER BY total DESC
            LIMIT 5
        """), {"start_date": ninety_days_ago})
        top_categories = cat_result.fetchall()
        cat_window = "90 days"

        if not top_categories:
            cat_result = await db.execute(text(f"""
                SELECT c.name, SUM(ABS(t.amount)) as total
                FROM "{tenant_schema}".transactions t
                JOIN "{tenant_schema}".categories c ON c.id = t.category_id
                WHERE t.amount < 0
                GROUP BY c.name
                ORDER BY total DESC
                LIMIT 5
            """))
            top_categories = cat_result.fetchall()
            cat_window = "all time"

        # ── All-time summary ──────────────────────────────────────────────────
        alltime_result = await db.execute(text(f"""
            SELECT
                SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) as total_income,
                SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) as total_expenses,
                COUNT(*) as total_tx,
                MIN(date) as earliest_date,
                MAX(date) as latest_date
            FROM "{tenant_schema}".transactions
        """))
        alltime = alltime_result.fetchone()

        # ── Outstanding invoices ──────────────────────────────────────────────
        inv_result = await db.execute(text(f"""
            SELECT
                COUNT(*) FILTER (WHERE status = 'sent') as sent_count,
                COUNT(*) FILTER (WHERE status = 'overdue') as overdue_count,
                SUM(total) FILTER (WHERE status IN ('sent', 'overdue')) as outstanding_amount
            FROM "{tenant_schema}".invoices
        """))
        inv = inv_result.fetchone()

        # ── Latest tax estimate ───────────────────────────────────────────────
        tax_result = await db.execute(text(f"""
            SELECT total_liability, income_tax, ni_class2, ni_class4,
                   vat_rolling_12m, tax_year
            FROM "{tenant_schema}".tax_estimates
            ORDER BY calculated_at DESC
            LIMIT 1
        """))
        tax = tax_result.fetchone()

        # ── Format context block ──────────────────────────────────────────────
        income_90d = float(tx.income_90d or 0)
        expenses_90d = float(tx.expenses_90d or 0)
        net_90d = income_90d - expenses_90d
        ytd_income = float(ytd.ytd_income or 0)
        ytd_expenses = float(ytd.ytd_expenses or 0)
        ytd_net = ytd_income - ytd_expenses

        cat_lines = "\n".join(
            f"  - {r.name}: £{float(r.total):.2f}"
            for r in top_categories
        ) or "  - No expense data yet"

        outstanding = float(inv.outstanding_amount or 0)
        overdue = int(inv.overdue_count or 0)

        tax_section = ""
        if tax:
            tax_section = f"""
TAX ESTIMATE ({tax.tax_year}):
  Total liability: £{float(tax.total_liability):.2f}
  Income tax: £{float(tax.income_tax):.2f}
  NI Class 2: £{float(tax.ni_class2):.2f}
  NI Class 4: £{float(tax.ni_class4):.2f}
  VAT rolling 12m: £{float(tax.vat_rolling_12m):.2f}"""

        alltime_income = float(alltime.total_income or 0)
        alltime_expenses = float(alltime.total_expenses or 0)
        alltime_net = alltime_income - alltime_expenses
        alltime_range = (
            f"{alltime.earliest_date} to {alltime.latest_date}"
            if alltime.earliest_date else "no data"
        )

        context = f"""=== FINANCIAL CONTEXT (as of {today}) ===

ALL-TIME SUMMARY ({alltime_range}):
  Total income: £{alltime_income:.2f}
  Total expenses: £{alltime_expenses:.2f}
  Net: £{alltime_net:.2f}
  Transactions: {int(alltime.total_tx or 0)}

LAST 90 DAYS:
  Income: £{income_90d:.2f}
  Expenses: £{expenses_90d:.2f}
  Net: £{net_90d:.2f}
  Transactions: {int(tx.tx_count or 0)}

YEAR TO DATE (since {tax_year_start}):
  Income: £{ytd_income:.2f}
  Expenses: £{ytd_expenses:.2f}
  Net profit: £{ytd_net:.2f}

TOP EXPENSE CATEGORIES ({cat_window}):
{cat_lines}

OUTSTANDING INVOICES:
  Awaiting payment: {int(inv.sent_count or 0)} (£{outstanding:.2f})
  Overdue: {overdue}
{tax_section}
=== END FINANCIAL CONTEXT ==="""

        return context

    except Exception as e:
        logger.error("Failed to build financial context: %s", e)
        return "=== FINANCIAL CONTEXT: unavailable ==="


SYSTEM_PROMPT_TEMPLATE = """You are an expert AI CFO (Chief Financial Officer) \
assistant for UK freelancers and solo businesses. You provide clear, \
actionable financial advice grounded in the user's actual financial data.

Your capabilities:
- Analyse income, expenses, and cash flow trends
- Estimate UK Self Assessment tax liability (income tax + NI Class 2/4)
- Flag VAT threshold proximity (£90,000 rolling 12 months)
- Identify unusual spending patterns
- Forecast cash flow and highlight risks
- Advise on allowable expenses for UK self-employed
- Draft invoice follow-up messages

Always:
- Be specific and reference actual figures from the financial context
- Flag urgent issues (overdue invoices, VAT threshold, tax deadlines)
- Give advice relevant to UK tax law (2025/26 tax year)
- Keep responses concise and actionable
- If data is missing, say so and ask for it

{financial_context}"""