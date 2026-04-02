"""
Unit tests for telegram_bot service.
All Telegram and DB calls are mocked — no network or DB required.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_update(chat_id: int = 12345, text: str = "hello"):
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.message.reply_text = AsyncMock()
    update.message.text = text
    return update


def _make_context(args=None):
    ctx = MagicMock()
    ctx.args = args
    return ctx


def _mock_user(email: str = "user@example.com", schema: str = "tenant_abc"):
    user = MagicMock()
    user.email = email
    user.tenant_schema = schema
    return user


# ── _get_user_by_telegram_id ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_user_by_telegram_id_found():
    from app.services.telegram_bot import _get_user_by_telegram_id

    mock_row = MagicMock()
    mock_row.tenant_schema = "tenant_abc"

    mock_result = MagicMock()
    mock_result.fetchone.return_value = mock_row

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.db.session.AsyncSessionLocal", return_value=mock_cm):
        user, schema = await _get_user_by_telegram_id(12345)

    assert user is mock_row
    assert schema == "tenant_abc"


@pytest.mark.asyncio
async def test_get_user_by_telegram_id_not_found():
    from app.services.telegram_bot import _get_user_by_telegram_id

    mock_result = MagicMock()
    mock_result.fetchone.return_value = None

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.db.session.AsyncSessionLocal", return_value=mock_cm):
        user, schema = await _get_user_by_telegram_id(99999)

    assert user is None
    assert schema is None


# ── start_command ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_command_linked_user():
    from app.services.telegram_bot import start_command

    update = _make_update()
    ctx = _make_context()
    user = _mock_user()

    with patch("app.services.telegram_bot._get_user_by_telegram_id",
               new_callable=AsyncMock, return_value=(user, "tenant_abc")):
        await start_command(update, ctx)

    update.message.reply_text.assert_called_once()
    assert "Welcome back" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_start_command_unlinked_user():
    from app.services.telegram_bot import start_command

    update = _make_update(chat_id=99999)
    ctx = _make_context()

    with patch("app.services.telegram_bot._get_user_by_telegram_id",
               new_callable=AsyncMock, return_value=(None, None)):
        await start_command(update, ctx)

    update.message.reply_text.assert_called_once()
    text = update.message.reply_text.call_args[0][0]
    assert "Chat ID" in text
    assert "99999" in text


# ── help_command ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_help_command():
    from app.services.telegram_bot import help_command

    update = _make_update()
    ctx = _make_context()

    await help_command(update, ctx)

    update.message.reply_text.assert_called_once()
    text = update.message.reply_text.call_args[0][0]
    assert "/summary" in text
    assert "/tax" in text


# ── summary_command ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_summary_command_not_linked():
    from app.services.telegram_bot import summary_command

    update = _make_update()
    ctx = _make_context()

    with patch("app.services.telegram_bot._get_user_by_telegram_id",
               new_callable=AsyncMock, return_value=(None, None)):
        await summary_command(update, ctx)

    # _send_not_linked is called → reply_text called once
    update.message.reply_text.assert_called_once()
    assert "not linked" in update.message.reply_text.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_summary_command_linked():
    from app.services.telegram_bot import summary_command

    update = _make_update()
    ctx = _make_context()
    user = _mock_user()

    with patch("app.services.telegram_bot._get_user_by_telegram_id",
               new_callable=AsyncMock, return_value=(user, "tenant_abc")), \
         patch("app.services.telegram_bot._get_financial_summary",
               new_callable=AsyncMock, return_value="📊 *Financial Summary*\n\nNet: £100"):
        await summary_command(update, ctx)

    assert update.message.reply_text.call_count == 2  # "⏳ Loading..." + summary


# ── tax_command ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tax_command_not_linked():
    from app.services.telegram_bot import tax_command

    update = _make_update()
    ctx = _make_context()

    with patch("app.services.telegram_bot._get_user_by_telegram_id",
               new_callable=AsyncMock, return_value=(None, None)):
        await tax_command(update, ctx)

    update.message.reply_text.assert_called_once()
    assert "not linked" in update.message.reply_text.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_tax_command_linked():
    from app.services.telegram_bot import tax_command

    update = _make_update()
    ctx = _make_context()
    user = _mock_user()

    with patch("app.services.telegram_bot._get_user_by_telegram_id",
               new_callable=AsyncMock, return_value=(user, "tenant_abc")), \
         patch("app.services.telegram_bot._get_tax_summary",
               new_callable=AsyncMock, return_value="🧾 *Tax Estimate*"):
        await tax_command(update, ctx)

    assert update.message.reply_text.call_count == 2


# ── chat_command ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_command_no_args():
    from app.services.telegram_bot import chat_command

    update = _make_update()
    ctx = _make_context(args=[])

    await chat_command(update, ctx)

    update.message.reply_text.assert_called_once()
    assert "Usage" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_chat_command_with_question():
    from app.services.telegram_bot import chat_command

    update = _make_update()
    ctx = _make_context(args=["What", "is", "my", "tax?"])

    with patch("app.services.telegram_bot._handle_cfo_question",
               new_callable=AsyncMock) as mock_cfo:
        await chat_command(update, ctx)

    mock_cfo.assert_called_once_with(update, "What is my tax?")


# ── handle_message ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_message_delegates_to_cfo():
    from app.services.telegram_bot import handle_message

    update = _make_update(text="How much do I owe in tax?")
    ctx = _make_context()

    with patch("app.services.telegram_bot._handle_cfo_question",
               new_callable=AsyncMock) as mock_cfo:
        await handle_message(update, ctx)

    mock_cfo.assert_called_once_with(update, "How much do I owe in tax?")


# ── _handle_cfo_question ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_cfo_question_linked_user():
    from app.services.telegram_bot import _handle_cfo_question

    update = _make_update()
    user = _mock_user()

    with patch("app.services.telegram_bot._get_user_by_telegram_id",
               new_callable=AsyncMock, return_value=(user, "tenant_abc")), \
         patch("app.services.ai_cfo.chat_full_response",
               new_callable=AsyncMock, return_value="Your tax liability is £5,000."), \
         patch("app.services.context_injector.build_financial_context",
               new_callable=AsyncMock, return_value="context"), \
         patch("app.db.session.AsyncSessionLocal") as mock_sl:
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_sl.return_value = mock_cm

        await _handle_cfo_question(update, "What is my tax?")

    # "🤔 Thinking..." + actual answer
    assert update.message.reply_text.call_count == 2


@pytest.mark.asyncio
async def test_handle_cfo_question_unlinked_user():
    from app.services.telegram_bot import _handle_cfo_question

    update = _make_update()

    with patch("app.services.telegram_bot._get_user_by_telegram_id",
               new_callable=AsyncMock, return_value=(None, None)), \
         patch("app.services.ai_cfo.chat_full_response",
               new_callable=AsyncMock, return_value="General advice here."):
        await _handle_cfo_question(update, "Give me advice")

    assert update.message.reply_text.call_count == 2


@pytest.mark.asyncio
async def test_handle_cfo_question_long_response():
    """Responses > 4096 chars are split into chunks."""
    from app.services.telegram_bot import _handle_cfo_question

    update = _make_update()
    long_response = "A" * 5000

    with patch("app.services.telegram_bot._get_user_by_telegram_id",
               new_callable=AsyncMock, return_value=(None, None)), \
         patch("app.services.ai_cfo.chat_full_response",
               new_callable=AsyncMock, return_value=long_response):
        await _handle_cfo_question(update, "Tell me everything")

    # "🤔 Thinking..." + 2 chunks (5000 / 4000 = 2)
    assert update.message.reply_text.call_count == 3


@pytest.mark.asyncio
async def test_handle_cfo_question_ai_error():
    """An AI error results in an apology message, not a crash."""
    from app.services.telegram_bot import _handle_cfo_question

    update = _make_update()

    with patch("app.services.telegram_bot._get_user_by_telegram_id",
               new_callable=AsyncMock, return_value=(None, None)), \
         patch("app.services.ai_cfo.chat_full_response",
               new_callable=AsyncMock, side_effect=Exception("AI error")):
        await _handle_cfo_question(update, "Crash me")

    last_call = update.message.reply_text.call_args[0][0]
    assert "Sorry" in last_call or "try again" in last_call


# ── _get_financial_summary ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_financial_summary_success():
    from app.services.telegram_bot import _get_financial_summary

    mock_week = MagicMock()
    mock_week.income = 3000
    mock_week.expenses = 500

    mock_ytd = MagicMock()
    mock_ytd.income = 30000
    mock_ytd.expenses = 5000

    mock_inv = MagicMock()
    mock_inv.outstanding = 2000
    mock_inv.overdue_count = 1

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=[
        MagicMock(fetchone=MagicMock(return_value=mock_week)),
        MagicMock(fetchone=MagicMock(return_value=mock_ytd)),
        MagicMock(fetchone=MagicMock(return_value=mock_inv)),
    ])

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.db.session.AsyncSessionLocal", return_value=mock_cm):
        result = await _get_financial_summary("tenant_abc")

    assert "Financial Summary" in result
    assert "overdue" in result.lower()


@pytest.mark.asyncio
async def test_get_financial_summary_db_error():
    from app.services.telegram_bot import _get_financial_summary

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=Exception("DB down"))

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.db.session.AsyncSessionLocal", return_value=mock_cm):
        result = await _get_financial_summary("tenant_abc")

    assert "Could not load" in result


# ── _get_tax_summary ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_tax_summary_success():
    from app.services.telegram_bot import _get_tax_summary
    from decimal import Decimal

    mock_estimate = MagicMock()
    mock_estimate.tax_year = "2024/25"
    mock_estimate.gross_income = Decimal("50000")
    mock_estimate.allowable_expenses = Decimal("5000")
    mock_estimate.net_profit = Decimal("45000")
    mock_estimate.income_tax = Decimal("6486")
    mock_estimate.ni_class2 = Decimal("179.40")
    mock_estimate.ni_class4 = Decimal("2926.53")
    mock_estimate.total_liability = Decimal("9591.93")
    mock_estimate.effective_rate = Decimal("21.3")
    mock_estimate.payment_on_account_jan = Decimal("4795.97")
    mock_estimate.payment_on_account_jul = Decimal("4795.97")

    mock_db = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.db.session.AsyncSessionLocal", return_value=mock_cm), \
         patch("app.services.tax_engine.fetch_ytd_figures",
               new_callable=AsyncMock,
               return_value=(Decimal("50000"), Decimal("5000"))), \
         patch("app.services.tax_engine.build_tax_estimate",
               return_value=mock_estimate):
        result = await _get_tax_summary("tenant_abc")

    assert "Tax Estimate" in result
    assert "2024/25" in result


@pytest.mark.asyncio
async def test_get_tax_summary_error():
    from app.services.telegram_bot import _get_tax_summary

    with patch("app.services.tax_engine.fetch_ytd_figures",
               new_callable=AsyncMock, side_effect=Exception("DB error")):
        result = await _get_tax_summary("tenant_abc")

    assert "Could not load" in result


# ── run_bot ───────────────────────────────────────────────────────────────────

def test_run_bot_no_token_exits_early():
    from app.services.telegram_bot import run_bot

    with patch("app.core.config.settings") as mock_settings:
        mock_settings.telegram_bot_token = ""
        run_bot()


def test_run_bot_starts_polling():
    from app.services.telegram_bot import run_bot

    mock_app = MagicMock()
    mock_builder = MagicMock()
    mock_builder.token.return_value = mock_builder
    mock_builder.build.return_value = mock_app

    with patch("app.core.config.settings") as mock_settings, \
         patch("app.services.telegram_bot.Application") as mock_Application:
        mock_settings.telegram_bot_token = "123:fake_token"
        mock_Application.builder.return_value = mock_builder

        run_bot()

    mock_app.run_polling.assert_called_once()
    assert mock_app.add_handler.call_count == 6
