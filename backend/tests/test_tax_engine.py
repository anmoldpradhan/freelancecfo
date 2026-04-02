import pytest
from decimal import Decimal
from app.services.tax_engine import (
    calculate_income_tax,
    calculate_ni,
    calculate_payments_on_account,
    build_tax_estimate,
    calculate_vat_status,
    _effective_personal_allowance,
    PERSONAL_ALLOWANCE,
    VAT_THRESHOLD,
)


# ── Personal allowance taper ──────────────────────────────────────────────────

def test_personal_allowance_below_taper():
    pa = _effective_personal_allowance(Decimal("50_000"))
    assert pa == PERSONAL_ALLOWANCE


def test_personal_allowance_tapers_at_100k():
    pa = _effective_personal_allowance(Decimal("100_000"))
    assert pa == PERSONAL_ALLOWANCE


def test_personal_allowance_tapers_at_110k():
    # £10k over threshold → PA reduces by £5k
    pa = _effective_personal_allowance(Decimal("110_000"))
    assert pa == PERSONAL_ALLOWANCE - Decimal("5_000")


def test_personal_allowance_zero_above_125140():
    pa = _effective_personal_allowance(Decimal("130_000"))
    assert pa == Decimal("0")


# ── Income tax ────────────────────────────────────────────────────────────────

def test_income_tax_zero_below_personal_allowance():
    result = calculate_income_tax(Decimal("10_000"))
    assert result.total_income_tax == Decimal("0")


def test_income_tax_basic_rate_only():
    # £30,000 net profit — all in basic rate band
    result = calculate_income_tax(Decimal("30_000"))
    expected_taxable = Decimal("30_000") - Decimal("12_570")
    expected_tax = (expected_taxable * Decimal("0.20")).quantize(Decimal("0.01"))
    assert result.total_income_tax == expected_tax
    assert result.higher_rate_tax == Decimal("0")


def test_income_tax_crosses_into_higher_rate():
    result = calculate_income_tax(Decimal("60_000"))
    assert result.higher_rate_tax > Decimal("0")
    assert result.basic_rate_tax > Decimal("0")
    assert result.additional_rate_tax == Decimal("0")


def test_income_tax_all_three_bands():
    result = calculate_income_tax(Decimal("150_000"))
    assert result.basic_rate_tax > Decimal("0")
    assert result.higher_rate_tax > Decimal("0")
    assert result.additional_rate_tax > Decimal("0")


def test_income_tax_zero_profit():
    result = calculate_income_tax(Decimal("0"))
    assert result.total_income_tax == Decimal("0")


# ── National Insurance ────────────────────────────────────────────────────────

def test_ni_zero_below_small_profits_threshold():
    result = calculate_ni(Decimal("10_000"))
    assert result.class2_annual == Decimal("0")
    assert result.class4_main == Decimal("0")


def test_ni_class2_above_threshold():
    result = calculate_ni(Decimal("15_000"))
    # Class 2: £3.45 × 52 = £179.40
    assert result.class2_annual == Decimal("179.40")


def test_ni_class4_main_rate():
    # £30,000 profit → class4 = (30000-12570) × 9% = £1,568.70
    result = calculate_ni(Decimal("30_000"))
    expected = ((Decimal("30_000") - Decimal("12_570")) * Decimal("0.09")).quantize(Decimal("0.01"))
    assert result.class4_main == expected


def test_ni_class4_upper_rate():
    # £60,000 profit → some at 2% above upper limit
    result = calculate_ni(Decimal("60_000"))
    assert result.class4_upper > Decimal("0")


def test_ni_zero_profit():
    result = calculate_ni(Decimal("0"))
    assert result.total_ni == Decimal("0")


# ── Payments on account ───────────────────────────────────────────────────────

def test_payments_on_account_below_threshold():
    jan, jul = calculate_payments_on_account(Decimal("999"))
    assert jan == Decimal("0")
    assert jul == Decimal("0")


def test_payments_on_account_above_threshold():
    jan, jul = calculate_payments_on_account(Decimal("2_000"))
    assert jan == Decimal("1_000")
    assert jul == Decimal("1_000")


def test_payments_on_account_exactly_1000():
    # Exactly £1000 — boundary case, should trigger PoA
    jan, jul = calculate_payments_on_account(Decimal("1_000"))
    assert jan == Decimal("500")


# ── Full estimate ─────────────────────────────────────────────────────────────

def test_build_tax_estimate_typical_freelancer():
    # £45k income, £5k expenses → £40k net profit
    estimate = build_tax_estimate(Decimal("45_000"), Decimal("5_000"))
    assert estimate.net_profit == Decimal("40_000.00")
    assert estimate.income_tax > Decimal("0")
    assert estimate.total_ni > Decimal("0")
    assert estimate.total_liability == estimate.income_tax + estimate.total_ni
    assert estimate.effective_rate > Decimal("0")


def test_build_tax_estimate_zero_income():
    estimate = build_tax_estimate(Decimal("0"), Decimal("0"))
    assert estimate.total_liability == Decimal("0")
    assert estimate.effective_rate == Decimal("0")


def test_build_tax_estimate_expenses_exceed_income():
    # Expenses > income → net profit clamped to 0
    estimate = build_tax_estimate(Decimal("10_000"), Decimal("15_000"))
    assert estimate.net_profit == Decimal("0.00")
    assert estimate.total_liability == Decimal("0.00")


# ── VAT status ────────────────────────────────────────────────────────────────

def test_vat_safe():
    status = calculate_vat_status(Decimal("50_000"), False)
    assert status.warning_level == "safe"
    assert status.amount_remaining == Decimal("40_000.00")


def test_vat_warning_80():
    status = calculate_vat_status(Decimal("73_000"), False)
    assert status.warning_level == "warning_80"


def test_vat_warning_95():
    status = calculate_vat_status(Decimal("86_500"), False)
    assert status.warning_level == "warning_95"


def test_vat_exceeded():
    status = calculate_vat_status(Decimal("95_000"), False)
    assert status.warning_level == "exceeded"
    assert status.amount_remaining == Decimal("0.00")


def test_vat_boundary_exactly_at_threshold():
    status = calculate_vat_status(VAT_THRESHOLD, False)
    assert status.warning_level == "exceeded"


def test_vat_registered_flag():
    status = calculate_vat_status(Decimal("50_000"), True)
    assert status.vat_registered is True