"""
UK Self Assessment tax calculator for 2025/26 tax year.

Covers:
- Income tax bands (personal allowance, basic, higher, additional)
- NI Class 2 (flat weekly rate for self-employed)
- NI Class 4 (percentage of profits between thresholds)
- Payments on account (50% of previous year's bill, due Jan + Jul)
- VAT threshold warning (£90,000 rolling 12 months)

All figures are 2025/26 HMRC published rates.
Sources: https://www.gov.uk/income-tax-rates
         https://www.gov.uk/self-employed-national-insurance-rates
"""
import logging
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)

# ── 2025/26 Tax constants ─────────────────────────────────────────────────────

PERSONAL_ALLOWANCE = Decimal("12_570")       # no tax below this
BASIC_RATE_LIMIT = Decimal("50_270")         # 20% up to here
HIGHER_RATE_LIMIT = Decimal("125_140")       # 40% up to here
ADDITIONAL_RATE_THRESHOLD = Decimal("125_140")  # 45% above this

BASIC_RATE = Decimal("0.20")
HIGHER_RATE = Decimal("0.40")
ADDITIONAL_RATE = Decimal("0.45")

# Personal allowance tapers by £1 for every £2 over £100k
PA_TAPER_THRESHOLD = Decimal("100_000")

# NI Class 2 — flat weekly rate (self-employed)
NI_CLASS2_WEEKLY = Decimal("3.45")
NI_CLASS2_WEEKS = Decimal("52")
NI_CLASS2_SMALL_PROFITS_THRESHOLD = Decimal("12_570")

# NI Class 4 — percentage of profits
NI_CLASS4_LOWER = Decimal("12_570")    # lower profits limit
NI_CLASS4_UPPER = Decimal("50_270")    # upper profits limit
NI_CLASS4_MAIN_RATE = Decimal("0.09")  # 9% between lower and upper
NI_CLASS4_UPPER_RATE = Decimal("0.02") # 2% above upper

# VAT
VAT_THRESHOLD = Decimal("90_000")       # £90,000 rolling 12 months
VAT_WARN_80_PCT = VAT_THRESHOLD * Decimal("0.80")
VAT_WARN_95_PCT = VAT_THRESHOLD * Decimal("0.95")

TAX_YEAR = "2025/26"
TAX_YEAR_START = date(2025, 4, 6)
TAX_YEAR_END = date(2026, 4, 5)


# ── Data classes for structured results ──────────────────────────────────────

@dataclass
class IncomeTaxBreakdown:
    gross_income: Decimal
    allowable_expenses: Decimal
    net_profit: Decimal
    personal_allowance_used: Decimal
    taxable_income: Decimal
    basic_rate_tax: Decimal
    higher_rate_tax: Decimal
    additional_rate_tax: Decimal
    total_income_tax: Decimal


@dataclass
class NIBreakdown:
    net_profit: Decimal
    class2_annual: Decimal
    class4_main: Decimal
    class4_upper: Decimal
    total_ni: Decimal


@dataclass
class TaxEstimate:
    tax_year: str
    gross_income: Decimal
    allowable_expenses: Decimal
    net_profit: Decimal
    income_tax: Decimal
    ni_class2: Decimal
    ni_class4: Decimal
    total_ni: Decimal
    total_liability: Decimal
    effective_rate: Decimal
    payment_on_account_jan: Decimal
    payment_on_account_jul: Decimal
    income_tax_breakdown: IncomeTaxBreakdown
    ni_breakdown: NIBreakdown


@dataclass
class VATStatus:
    rolling_12m_income: Decimal
    threshold: Decimal
    percentage_used: Decimal
    warning_level: str          # "safe" | "warning_80" | "warning_95" | "exceeded"
    amount_remaining: Decimal
    vat_registered: bool


# ── Core calculation functions ────────────────────────────────────────────────

def _effective_personal_allowance(net_profit: Decimal) -> Decimal:
    """
    Personal allowance tapers to zero for income over £125,140.
    Reduces by £1 for every £2 over £100,000.
    """
    if net_profit <= PA_TAPER_THRESHOLD:
        return PERSONAL_ALLOWANCE
    reduction = (net_profit - PA_TAPER_THRESHOLD) / Decimal("2")
    allowance = PERSONAL_ALLOWANCE - reduction
    return max(Decimal("0"), allowance)


def calculate_income_tax(net_profit: Decimal) -> IncomeTaxBreakdown:
    """
    Calculates income tax on net profit using 2025/26 bands.
    Net profit = gross income - allowable expenses (for self-employed).
    """
    net_profit = max(Decimal("0"), net_profit)
    pa = _effective_personal_allowance(net_profit)
    taxable = max(Decimal("0"), net_profit - pa)

    # Basic rate band: PA to £50,270
    basic_band = max(Decimal("0"), min(taxable, BASIC_RATE_LIMIT - pa))
    basic_tax = basic_band * BASIC_RATE

    # Higher rate band: £50,270 to £125,140
    higher_band_top = HIGHER_RATE_LIMIT - pa
    higher_band = max(Decimal("0"), min(taxable - basic_band, higher_band_top - basic_band))
    higher_tax = higher_band * HIGHER_RATE

    # Additional rate: above £125,140
    additional_band = max(Decimal("0"), taxable - (higher_band_top))
    additional_tax = additional_band * ADDITIONAL_RATE

    total = basic_tax + higher_tax + additional_tax

    return IncomeTaxBreakdown(
        gross_income=net_profit,
        allowable_expenses=Decimal("0"),  # caller sets this
        net_profit=net_profit,
        personal_allowance_used=min(pa, net_profit),
        taxable_income=taxable,
        basic_rate_tax=basic_tax.quantize(Decimal("0.01"), ROUND_HALF_UP),
        higher_rate_tax=higher_tax.quantize(Decimal("0.01"), ROUND_HALF_UP),
        additional_rate_tax=additional_tax.quantize(Decimal("0.01"), ROUND_HALF_UP),
        total_income_tax=total.quantize(Decimal("0.01"), ROUND_HALF_UP),
    )


def calculate_ni(net_profit: Decimal) -> NIBreakdown:
    """
    Calculates NI Class 2 + Class 4 for self-employed.
    Class 2: flat weekly rate if profit > small profits threshold.
    Class 4: 9% on profit between £12,570 and £50,270; 2% above.
    """
    net_profit = max(Decimal("0"), net_profit)

    # Class 2
    if net_profit >= NI_CLASS2_SMALL_PROFITS_THRESHOLD:
        class2 = NI_CLASS2_WEEKLY * NI_CLASS2_WEEKS
    else:
        class2 = Decimal("0")

    # Class 4 main rate (9% between lower and upper)
    class4_main_base = max(
        Decimal("0"),
        min(net_profit, NI_CLASS4_UPPER) - NI_CLASS4_LOWER
    )
    class4_main = class4_main_base * NI_CLASS4_MAIN_RATE

    # Class 4 upper rate (2% above £50,270)
    class4_upper_base = max(Decimal("0"), net_profit - NI_CLASS4_UPPER)
    class4_upper = class4_upper_base * NI_CLASS4_UPPER_RATE

    total_ni = class2 + class4_main + class4_upper

    return NIBreakdown(
        net_profit=net_profit,
        class2_annual=class2.quantize(Decimal("0.01"), ROUND_HALF_UP),
        class4_main=class4_main.quantize(Decimal("0.01"), ROUND_HALF_UP),
        class4_upper=class4_upper.quantize(Decimal("0.01"), ROUND_HALF_UP),
        total_ni=total_ni.quantize(Decimal("0.01"), ROUND_HALF_UP),
    )


def calculate_payments_on_account(total_liability: Decimal) -> tuple[Decimal, Decimal]:
    """
    Payments on account = 50% of previous year's tax bill.
    Due: 31 January and 31 July.
    Only applies if total liability > £1,000.
    Returns (january_payment, july_payment).
    """
    if total_liability < Decimal("1000"):
        return Decimal("0"), Decimal("0")
    payment = (total_liability * Decimal("0.5")).quantize(
        Decimal("0.01"), ROUND_HALF_UP
    )
    return payment, payment


def build_tax_estimate(
    gross_income: Decimal,
    allowable_expenses: Decimal,
) -> TaxEstimate:
    """
    Master function — builds complete tax estimate from income + expenses.
    """
    net_profit = max(Decimal("0"), gross_income - allowable_expenses)

    it_breakdown = calculate_income_tax(net_profit)
    it_breakdown.gross_income = gross_income
    it_breakdown.allowable_expenses = allowable_expenses

    ni_breakdown = calculate_ni(net_profit)

    total_liability = it_breakdown.total_income_tax + ni_breakdown.total_ni
    jan_poa, jul_poa = calculate_payments_on_account(total_liability)

    effective_rate = (
        (total_liability / net_profit * 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
        if net_profit > 0 else Decimal("0")
    )

    return TaxEstimate(
        tax_year=TAX_YEAR,
        gross_income=gross_income.quantize(Decimal("0.01"), ROUND_HALF_UP),
        allowable_expenses=allowable_expenses.quantize(Decimal("0.01"), ROUND_HALF_UP),
        net_profit=net_profit.quantize(Decimal("0.01"), ROUND_HALF_UP),
        income_tax=it_breakdown.total_income_tax,
        ni_class2=ni_breakdown.class2_annual,
        ni_class4=ni_breakdown.class4_main + ni_breakdown.class4_upper,
        total_ni=ni_breakdown.total_ni,
        total_liability=total_liability.quantize(Decimal("0.01"), ROUND_HALF_UP),
        effective_rate=effective_rate,
        payment_on_account_jan=jan_poa,
        payment_on_account_jul=jul_poa,
        income_tax_breakdown=it_breakdown,
        ni_breakdown=ni_breakdown,
    )


# ── VAT calculation ───────────────────────────────────────────────────────────

def calculate_vat_status(
    rolling_12m_income: Decimal,
    vat_registered: bool,
) -> VATStatus:
    pct = (rolling_12m_income / VAT_THRESHOLD * 100).quantize(
        Decimal("0.1"), ROUND_HALF_UP
    ) if rolling_12m_income > 0 else Decimal("0")

    if rolling_12m_income >= VAT_THRESHOLD:
        level = "exceeded"
    elif rolling_12m_income >= VAT_WARN_95_PCT:
        level = "warning_95"
    elif rolling_12m_income >= VAT_WARN_80_PCT:
        level = "warning_80"
    else:
        level = "safe"

    remaining = max(Decimal("0"), VAT_THRESHOLD - rolling_12m_income)

    return VATStatus(
        rolling_12m_income=rolling_12m_income.quantize(Decimal("0.01"), ROUND_HALF_UP),
        threshold=VAT_THRESHOLD,
        percentage_used=pct,
        warning_level=level,
        amount_remaining=remaining.quantize(Decimal("0.01"), ROUND_HALF_UP),
        vat_registered=vat_registered,
    )


# ── Database fetch functions ──────────────────────────────────────────────────

async def fetch_ytd_figures(
    tenant_schema: str,
    db: AsyncSession,
) -> tuple[Decimal, Decimal]:
    """
    Returns (gross_income, allowable_expenses) for current tax year.
    Income = sum of positive transactions since Apr 6.
    Expenses = sum of absolute negative transactions since Apr 6.
    """
    today = date.today()
    tax_year_start = date(today.year, 4, 6) \
        if today.month >= 4 \
        else date(today.year - 1, 4, 6)

    try:
        result = await db.execute(text(f"""
            SELECT
                COALESCE(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0)
                    AS gross_income,
                COALESCE(SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END), 0)
                    AS allowable_expenses
            FROM "{tenant_schema}".transactions
            WHERE date >= :start
        """), {"start": tax_year_start})
        row = result.fetchone()
        return Decimal(str(row.gross_income)), Decimal(str(row.allowable_expenses))
    except Exception as e:
        logger.error("fetch_ytd_figures error: %s", e)
        return Decimal("0"), Decimal("0")


async def fetch_rolling_12m_income(
    tenant_schema: str,
    db: AsyncSession,
) -> Decimal:
    """Rolling 12-month income for VAT threshold check."""
    twelve_months_ago = date.today() - timedelta(days=365)
    try:
        result = await db.execute(text(f"""
            SELECT COALESCE(SUM(amount), 0) AS rolling_income
            FROM "{tenant_schema}".transactions
            WHERE amount > 0 AND date >= :start
        """), {"start": twelve_months_ago})
        row = result.fetchone()
        return Decimal(str(row.rolling_income))
    except Exception as e:
        logger.error("fetch_rolling_12m_income error: %s", e)
        return Decimal("0")