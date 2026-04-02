"""
90-day cash flow forecaster.

Method:
  1. Calculate average weekly income + expenses from last 90 days
  2. Project forward 13 weeks (91 days)
  3. Apply a simple confidence decay — further out = less certain
  4. Flag weeks where cumulative balance goes negative

This is a linear trend forecast — good enough for freelancers.
For Week 8 we can upgrade to seasonal decomposition if needed.
"""
import logging
from dataclasses import dataclass
from decimal import Decimal
from datetime import date, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)

FORECAST_WEEKS = 13       # 91 days
LOOKBACK_DAYS = 90        # historical window for averages
BASE_CONFIDENCE = Decimal("0.85")
CONFIDENCE_DECAY = Decimal("0.01")   # confidence drops 1% per week out


@dataclass
class WeeklyForecast:
    week_start: str
    week_end: str
    projected_income: Decimal
    projected_expenses: Decimal
    net: Decimal
    cumulative_balance: Decimal
    confidence: Decimal
    alert: str    # "" | "low_balance" | "negative_balance"


@dataclass
class CashFlowForecast:
    generated_at: str
    lookback_days: int
    avg_weekly_income: Decimal
    avg_weekly_expenses: Decimal
    current_balance_proxy: Decimal   # YTD net as balance proxy
    weeks: list[WeeklyForecast]
    summary: str


async def build_cashflow_forecast(
    tenant_schema: str,
    db: AsyncSession,
) -> CashFlowForecast:
    """
    Builds a 13-week cash flow forecast from transaction history.
    Returns a CashFlowForecast dataclass.
    Safe — returns zero-based forecast on any DB error.
    """
    today = date.today()
    lookback_start = today - timedelta(days=LOOKBACK_DAYS)

    try:
        # ── Historical weekly averages ────────────────────────────────────────
        result = await db.execute(text(f"""
            SELECT
                COALESCE(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0)
                    AS total_income,
                COALESCE(SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END), 0)
                    AS total_expenses,
                COUNT(DISTINCT DATE_TRUNC('week', date)) AS weeks_with_data
            FROM "{tenant_schema}".transactions
            WHERE date >= :start
        """), {"start": lookback_start})
        row = result.fetchone()

        total_income = Decimal(str(row.total_income))
        total_expenses = Decimal(str(row.total_expenses))
        # Use actual weeks with data, min 1 to avoid division by zero
        weeks_with_data = max(int(row.weeks_with_data or 1), 1)

        avg_weekly_income = (total_income / weeks_with_data).quantize(Decimal("0.01"))
        avg_weekly_expenses = (total_expenses / weeks_with_data).quantize(Decimal("0.01"))

        # ── Current balance proxy (YTD net) ──────────────────────────────────
        tax_year_start = date(today.year, 4, 6) \
            if today.month >= 4 \
            else date(today.year - 1, 4, 6)

        bal_result = await db.execute(text(f"""
            SELECT COALESCE(SUM(amount), 0) AS ytd_net
            FROM "{tenant_schema}".transactions
            WHERE date >= :start
        """), {"start": tax_year_start})
        bal_row = bal_result.fetchone()
        current_balance = Decimal(str(bal_row.ytd_net))

    except Exception as e:
        logger.error("Cashflow forecast DB error: %s", e)
        avg_weekly_income = Decimal("0")
        avg_weekly_expenses = Decimal("0")
        current_balance = Decimal("0")
        weeks_with_data = 0

    # ── Build weekly projections ──────────────────────────────────────────────
    weeks = []
    cumulative = current_balance

    for week_num in range(FORECAST_WEEKS):
        week_start = today + timedelta(weeks=week_num)
        week_end = week_start + timedelta(days=6)

        confidence = max(
            Decimal("0.40"),
            BASE_CONFIDENCE - (CONFIDENCE_DECAY * week_num)
        )

        net = avg_weekly_income - avg_weekly_expenses
        cumulative += net

        # Determine alert level
        if cumulative < 0:
            alert = "negative_balance"
        elif cumulative < avg_weekly_expenses * 2:
            alert = "low_balance"
        else:
            alert = ""

        weeks.append(WeeklyForecast(
            week_start=week_start.isoformat(),
            week_end=week_end.isoformat(),
            projected_income=avg_weekly_income,
            projected_expenses=avg_weekly_expenses,
            net=net.quantize(Decimal("0.01")),
            cumulative_balance=cumulative.quantize(Decimal("0.01")),
            confidence=confidence,
            alert=alert,
        ))

    # ── Summary text ──────────────────────────────────────────────────────────
    negative_weeks = sum(1 for w in weeks if w.alert == "negative_balance")
    low_weeks = sum(1 for w in weeks if w.alert == "low_balance")

    if negative_weeks > 0:
        summary = (
            f"⚠️ Cash flow alert: {negative_weeks} week(s) projected with "
            f"negative balance in the next 13 weeks. Consider chasing "
            f"outstanding invoices."
        )
    elif low_weeks > 0:
        summary = (
            f"⚡ Cash flow caution: {low_weeks} week(s) with low balance "
            f"projected. Monitor closely."
        )
    else:
        summary = (
            f"✅ Cash flow looks stable over the next 13 weeks based on "
            f"recent trends."
        )

    from datetime import datetime
    return CashFlowForecast(
        generated_at=datetime.utcnow().isoformat(),
        lookback_days=LOOKBACK_DAYS,
        avg_weekly_income=avg_weekly_income,
        avg_weekly_expenses=avg_weekly_expenses,
        current_balance_proxy=current_balance.quantize(Decimal("0.01")),
        weeks=weeks,
        summary=summary,
    )