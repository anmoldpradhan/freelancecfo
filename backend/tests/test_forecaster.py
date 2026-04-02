import pytest
from unittest.mock import AsyncMock, MagicMock
from decimal import Decimal
from app.services.forecaster import (
    build_cashflow_forecast,
    FORECAST_WEEKS,
    BASE_CONFIDENCE,
)


@pytest.mark.asyncio
async def test_forecast_returns_13_weeks():
    mock_db = AsyncMock()

    tx_row = MagicMock()
    tx_row.total_income = 4000
    tx_row.total_expenses = 1500
    tx_row.weeks_with_data = 4

    bal_row = MagicMock()
    bal_row.ytd_net = 8000

    mock_result_tx = MagicMock()
    mock_result_tx.fetchone.return_value = tx_row

    mock_result_bal = MagicMock()
    mock_result_bal.fetchone.return_value = bal_row

    mock_db.execute = AsyncMock(
        side_effect=[mock_result_tx, mock_result_bal]
    )

    forecast = await build_cashflow_forecast("tenant_test", mock_db)

    assert len(forecast.weeks) == FORECAST_WEEKS


@pytest.mark.asyncio
async def test_forecast_confidence_decays():
    mock_db = AsyncMock()

    tx_row = MagicMock()
    tx_row.total_income = 2000
    tx_row.total_expenses = 800
    tx_row.weeks_with_data = 4

    bal_row = MagicMock()
    bal_row.ytd_net = 5000

    mock_result = MagicMock()
    mock_result.fetchone.side_effect = [tx_row, bal_row]

    mock_db.execute = AsyncMock(return_value=mock_result)

    forecast = await build_cashflow_forecast("tenant_test", mock_db)

    # First week should have higher confidence than last
    assert forecast.weeks[0].confidence >= forecast.weeks[-1].confidence


@pytest.mark.asyncio
async def test_forecast_negative_balance_alert():
    mock_db = AsyncMock()

    # Expenses exceed income → cumulative goes negative
    tx_row = MagicMock()
    tx_row.total_income = 500
    tx_row.total_expenses = 2000
    tx_row.weeks_with_data = 4

    bal_row = MagicMock()
    bal_row.ytd_net = 100   # very low starting balance

    mock_result = MagicMock()
    mock_result.fetchone.side_effect = [tx_row, bal_row]

    mock_db.execute = AsyncMock(return_value=mock_result)

    forecast = await build_cashflow_forecast("tenant_test", mock_db)

    alerts = [w.alert for w in forecast.weeks]
    assert "negative_balance" in alerts
    assert "alert" in forecast.summary.lower() or "⚠️" in forecast.summary


@pytest.mark.asyncio
async def test_forecast_handles_db_error():
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=Exception("DB down"))

    forecast = await build_cashflow_forecast("tenant_test", mock_db)

    # Should not raise — returns zero-based forecast
    assert len(forecast.weeks) == FORECAST_WEEKS
    assert forecast.avg_weekly_income == Decimal("0")


@pytest.mark.asyncio
async def test_forecast_positive_summary_when_healthy():
    mock_db = AsyncMock()

    tx_row = MagicMock()
    tx_row.total_income = 5000
    tx_row.total_expenses = 1000
    tx_row.weeks_with_data = 4

    bal_row = MagicMock()
    bal_row.ytd_net = 20_000

    mock_result = MagicMock()
    mock_result.fetchone.side_effect = [tx_row, bal_row]

    mock_db.execute = AsyncMock(return_value=mock_result)

    forecast = await build_cashflow_forecast("tenant_test", mock_db)

    assert "✅" in forecast.summary


def test_forecast_week_fields():
    """Ensure WeeklyForecast dataclass has all expected fields."""
    from app.services.forecaster import WeeklyForecast
    w = WeeklyForecast(
        week_start="2025-01-01",
        week_end="2025-01-07",
        projected_income=Decimal("1000"),
        projected_expenses=Decimal("400"),
        net=Decimal("600"),
        cumulative_balance=Decimal("1600"),
        confidence=Decimal("0.85"),
        alert="",
    )
    assert w.net == Decimal("600")
    assert w.alert == ""