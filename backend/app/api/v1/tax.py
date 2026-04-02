from decimal import Decimal
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.dependencies import get_db, get_current_user
from app.models.user import User
from app.services.tax_engine import (
    build_tax_estimate, fetch_ytd_figures,
    fetch_rolling_12m_income, calculate_vat_status,
    TaxEstimate,
)
from app.services.forecaster import build_cashflow_forecast

router = APIRouter(tags=["tax & forecast"])


@router.get("/api/v1/tax/estimate")
async def tax_estimate(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Real-time Self Assessment estimate based on YTD transactions."""
    gross, expenses = await fetch_ytd_figures(current_user.tenant_schema, db)
    estimate = build_tax_estimate(gross, expenses)
    await _save_estimate(current_user.tenant_schema, estimate, db)
    return {
        "tax_year": estimate.tax_year,
        "gross_income": float(estimate.gross_income),
        "allowable_expenses": float(estimate.allowable_expenses),
        "net_profit": float(estimate.net_profit),
        "income_tax": float(estimate.income_tax),
        "ni_class2": float(estimate.ni_class2),
        "ni_class4": float(estimate.ni_class4),
        "total_ni": float(estimate.total_ni),
        "total_liability": float(estimate.total_liability),
        "effective_rate_pct": float(estimate.effective_rate),
        "set_aside_recommended": float(
            (estimate.total_liability / estimate.gross_income * 100)
            .quantize(Decimal("0.1"))
            if estimate.gross_income > 0 else Decimal("0")
        ),
    }

# In /api/v1/tax.py — add after building estimate:

async def _save_estimate(
    tenant_schema: str,
    estimate: TaxEstimate,
    db: AsyncSession,
):
    await db.execute(text(f"""
        INSERT INTO "{tenant_schema}".tax_estimates
            (tax_year, gross_income, allowable_expenses, net_profit,
             income_tax, ni_class2, ni_class4, total_liability,
             vat_rolling_12m)
        VALUES
            (:tax_year, :gross, :expenses, :net,
             :income_tax, :ni2, :ni4, :total, 0)
        ON CONFLICT DO NOTHING
    """), {
        "tax_year": estimate.tax_year,
        "gross": float(estimate.gross_income),
        "expenses": float(estimate.allowable_expenses),
        "net": float(estimate.net_profit),
        "income_tax": float(estimate.income_tax),
        "ni2": float(estimate.ni_class2),
        "ni4": float(estimate.ni_class4),
        "total": float(estimate.total_liability),
    })
    await db.commit()

@router.get("/api/v1/tax/breakdown")
async def tax_breakdown(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Detailed breakdown including payments on account deadlines."""
    gross, expenses = await fetch_ytd_figures(current_user.tenant_schema, db)
    estimate = build_tax_estimate(gross, expenses)
    it = estimate.income_tax_breakdown
    ni = estimate.ni_breakdown
    await _save_estimate(current_user.tenant_schema, estimate, db)

    return {
        "tax_year": estimate.tax_year,
        "income_summary": {
            "gross_income": float(estimate.gross_income),
            "allowable_expenses": float(estimate.allowable_expenses),
            "net_profit": float(estimate.net_profit),
        },
        "income_tax": {
            "personal_allowance": float(it.personal_allowance_used),
            "taxable_income": float(it.taxable_income),
            "basic_rate_20pct": float(it.basic_rate_tax),
            "higher_rate_40pct": float(it.higher_rate_tax),
            "additional_rate_45pct": float(it.additional_rate_tax),
            "total": float(it.total_income_tax),
        },
        "national_insurance": {
            "class2_flat_rate": float(ni.class2_annual),
            "class4_9pct_band": float(ni.class4_main),
            "class4_2pct_above_upper": float(ni.class4_upper),
            "total": float(ni.total_ni),
        },
        "total_liability": float(estimate.total_liability),
        "effective_rate_pct": float(estimate.effective_rate),
        "payments_on_account": {
            "january_31": float(estimate.payment_on_account_jan),
            "july_31": float(estimate.payment_on_account_jul),
            "note": "50% of current year liability, due Jan 31 and Jul 31",
        },
    }


@router.get("/api/v1/forecast/cashflow")
async def cashflow_forecast(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """13-week cash flow projection based on recent transaction patterns."""
    forecast = await build_cashflow_forecast(current_user.tenant_schema, db)

    return {
        "generated_at": forecast.generated_at,
        "summary": forecast.summary,
        "averages": {
            "weekly_income": float(forecast.avg_weekly_income),
            "weekly_expenses": float(forecast.avg_weekly_expenses),
            "weekly_net": float(
                forecast.avg_weekly_income - forecast.avg_weekly_expenses
            ),
        },
        "current_balance_proxy": float(forecast.current_balance_proxy),
        "weeks": [
            {
                "week_start": w.week_start,
                "week_end": w.week_end,
                "projected_income": float(w.projected_income),
                "projected_expenses": float(w.projected_expenses),
                "net": float(w.net),
                "cumulative_balance": float(w.cumulative_balance),
                "confidence": float(w.confidence),
                "alert": w.alert,
            }
            for w in forecast.weeks
        ],
    }


@router.get("/api/v1/forecast/vat")
async def vat_forecast(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """VAT threshold proximity check + rolling 12-month income."""
    schema = current_user.tenant_schema

    rolling_income = await fetch_rolling_12m_income(schema, db)

    # Get VAT registration status from financial profile
    result = await db.execute(text("""
        SELECT vat_registered FROM public.financial_profiles
        WHERE user_id = :user_id
    """), {"user_id": str(current_user.id)})
    profile = result.fetchone()
    vat_registered = bool(profile.vat_registered) if profile else False

    vat = calculate_vat_status(rolling_income, vat_registered)

    alert_messages = {
        "safe": "You are well within the VAT threshold.",
        "warning_80": (
            "⚡ You have used 80% of the VAT threshold. "
            "Consider preparing for VAT registration."
        ),
        "warning_95": (
            "⚠️ You have used 95% of the VAT threshold. "
            "VAT registration is likely required soon."
        ),
        "exceeded": (
            "🚨 You have exceeded the VAT threshold (£90,000). "
            "You must register for VAT immediately."
        ),
    }

    return {
        "rolling_12m_income": float(vat.rolling_12m_income),
        "vat_threshold": float(vat.threshold),
        "percentage_used": float(vat.percentage_used),
        "amount_remaining": float(vat.amount_remaining),
        "warning_level": vat.warning_level,
        "alert_message": alert_messages[vat.warning_level],
        "vat_registered": vat.vat_registered,
        "registration_deadline_note": (
            "You must register within 30 days of exceeding the threshold."
            if vat.warning_level == "exceeded" and not vat.vat_registered
            else None
        ),
    }

