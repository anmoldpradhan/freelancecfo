import pytest
from unittest.mock import patch, AsyncMock, MagicMock, call
from datetime import date


def _make_mock_factory(mock_db):
    """Returns a (session_factory, engine) pair backed by mock_db."""
    mock_engine = AsyncMock()
    mock_session = MagicMock()
    mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_session, mock_engine


# ── Weekly digest ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_user_digest_no_sendgrid():
    """Digest runs without crashing when SendGrid not configured."""
    from app.tasks.weekly_digest import _send_user_digest

    mock_row = MagicMock()
    mock_row.week_income = 1500
    mock_row.week_expenses = 400
    mock_row.tx_count = 8

    mock_inv = MagicMock()
    mock_inv.sent_count = 2
    mock_inv.overdue_count = 1
    mock_inv.outstanding = 3000

    mock_result_tx = MagicMock()
    mock_result_tx.fetchone.return_value = mock_row

    mock_result_inv = MagicMock()
    mock_result_inv.fetchone.return_value = mock_inv

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        side_effect=[mock_result_tx, mock_result_inv]
    )

    mock_session, mock_engine = _make_mock_factory(mock_db)

    with patch("app.tasks.weekly_digest._make_session_factory",
               return_value=(mock_session, mock_engine)):
        with patch("app.tasks.weekly_digest._send_email") as mock_email:
            await _send_user_digest(
                user_id="uid",
                email="test@example.com",
                tenant_schema="tenant_test",
                trading_name="Test Co",
            )
            mock_email.assert_called_once()
            call_kwargs = mock_email.call_args
            assert "test@example.com" in str(call_kwargs)


def test_send_email_skips_without_sendgrid():
    """_send_email returns silently when SendGrid key not set."""
    from app.tasks.weekly_digest import _send_email

    with patch("app.core.config.settings") as mock_settings:
        mock_settings.sendgrid_api_key = ""
        _send_email("test@example.com", "Subject", "<p>Body</p>")


# ── Overdue invoice checker ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_process_tenant_overdue_no_invoices():
    """No overdue invoices → no emails sent."""
    from app.tasks.send_invoice import _process_tenant_overdue

    mock_result = MagicMock()
    mock_result.fetchall.return_value = []

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    mock_session, mock_engine = _make_mock_factory(mock_db)

    with patch("app.tasks.send_invoice._make_session_factory",
               return_value=(mock_session, mock_engine)):
        with patch("app.tasks.send_invoice._send_chase_email") as mock_chase:
            await _process_tenant_overdue(
                "uid", "test@example.com", "tenant_test", "Test Co"
            )
            mock_chase.assert_not_called()


@pytest.mark.asyncio
async def test_process_tenant_overdue_sends_chase():
    """Overdue invoices trigger chase emails."""
    from app.tasks.send_invoice import _process_tenant_overdue

    mock_invoice = MagicMock()
    mock_invoice.invoice_number = "INV-001"
    mock_invoice.client_name = "ACME Ltd"
    mock_invoice.client_email = "acme@example.com"
    mock_invoice.total = 1500
    mock_invoice.due_date = date(2024, 1, 1)

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_invoice]

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    mock_session, mock_engine = _make_mock_factory(mock_db)

    with patch("app.tasks.send_invoice._make_session_factory",
               return_value=(mock_session, mock_engine)):
        with patch("app.tasks.send_invoice._send_chase_email",
                   new_callable=AsyncMock) as mock_chase:
            await _process_tenant_overdue(
                "uid", "test@example.com", "tenant_test", "Test Co"
            )
            mock_chase.assert_called_once_with(mock_invoice, "Test Co")


# ── VAT threshold check ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_vat_check_safe_no_email():
    """No email sent when VAT level is safe."""
    from app.tasks.send_invoice import _check_all_vat
    from decimal import Decimal

    mock_user = MagicMock()
    mock_user.id = "uid"
    mock_user.email = "test@example.com"
    mock_user.tenant_schema = "tenant_test"
    mock_user.trading_name = "Test Co"
    mock_user.vat_registered = False

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_user]

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    mock_session, mock_engine = _make_mock_factory(mock_db)

    with patch("app.tasks.send_invoice._make_session_factory",
               return_value=(mock_session, mock_engine)):
        with patch("app.services.tax_engine.fetch_rolling_12m_income",
                   new_callable=AsyncMock,
                   return_value=Decimal("40000")):
            with patch("app.tasks.weekly_digest._send_email") as mock_email:
                await _check_all_vat()
                mock_email.assert_not_called()


@pytest.mark.asyncio
async def test_vat_check_exceeded_sends_email():
    """Email sent when VAT threshold exceeded."""
    from app.tasks.send_invoice import _check_all_vat
    from decimal import Decimal

    mock_user = MagicMock()
    mock_user.id = "uid"
    mock_user.email = "test@example.com"
    mock_user.tenant_schema = "tenant_test"
    mock_user.trading_name = "Test Co"
    mock_user.vat_registered = False

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_user]

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    mock_session, mock_engine = _make_mock_factory(mock_db)

    with patch("app.tasks.send_invoice._make_session_factory",
               return_value=(mock_session, mock_engine)):
        with patch("app.services.tax_engine.fetch_rolling_12m_income",
                   new_callable=AsyncMock,
                   return_value=Decimal("95000")):
            with patch("app.tasks.weekly_digest._send_email") as mock_email:
                await _check_all_vat()
                mock_email.assert_called_once()
                subject = mock_email.call_args[1]["subject"] \
                    if mock_email.call_args[1] \
                    else mock_email.call_args[0][1]
                assert "VAT" in subject


# ── Celery Beat schedule ──────────────────────────────────────────────────────

def test_beat_schedule_has_all_tasks():
    from app.tasks.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    expected_tasks = {
        "weekly-digest",
        "check-overdue-invoices",
        "payment-on-account-jan",
        "payment-on-account-jul",
        "vat-threshold-check",
    }
    assert expected_tasks.issubset(set(schedule.keys()))


def test_beat_schedule_task_names():
    from app.tasks.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    assert schedule["weekly-digest"]["task"] == "tasks.weekly_digest"
    assert schedule["check-overdue-invoices"]["task"] == "tasks.check_overdue_invoices"
