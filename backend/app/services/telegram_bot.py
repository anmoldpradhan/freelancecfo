"""
FreelanceCFO Telegram Bot

Commands:
  /start   — welcome message
  /help    — list commands
  /summary — financial snapshot (requires linked account)
  /tax     — current tax estimate
  /chat    — ask the AI CFO anything (just type after /chat)

Architecture:
  - python-telegram-bot runs in its own thread via run_polling()
  - DB calls use asyncio.run() since the bot handlers are sync
  - Each Telegram user is matched to a FreelanceCFO account via
    their telegram_chat_id stored in financial_profiles
  - If no account linked, bot prompts them to register on web
"""

import logging
import asyncio
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logger = logging.getLogger(__name__)


# ── Helper: fetch user by telegram chat_id ────────────────────────────────────

async def _get_user_by_telegram_id(chat_id: int):
    """
    Looks up FreelanceCFO user linked to this Telegram chat ID.
    Returns (user_row, tenant_schema) or (None, None).
    """
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import text

    async with AsyncSessionLocal() as db:
        result = await db.execute(text("""
            SELECT u.id, u.email, u.tenant_schema
            FROM public.users u
            JOIN public.financial_profiles fp ON fp.user_id = u.id
            WHERE fp.telegram_chat_id = :chat_id
            AND u.is_active = TRUE
        """), {"chat_id": str(chat_id)})
        row = result.fetchone()
        if row:
            return row, row.tenant_schema
        return None, None


async def _get_financial_summary(tenant_schema: str) -> str:
    """Builds a short financial summary for Telegram messages."""
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import text
    from datetime import date, timedelta

    seven_days_ago = date.today() - timedelta(days=7)
    tax_year_start = (
        date(date.today().year, 4, 6)
        if date.today().month >= 4
        else date(date.today().year - 1, 4, 6)
    )

    try:
        async with AsyncSessionLocal() as db:
            # Last 7 days
            week_result = await db.execute(text(f"""
                SELECT
                    COALESCE(SUM(CASE WHEN amount > 0
                        THEN amount ELSE 0 END), 0) AS income,
                    COALESCE(SUM(CASE WHEN amount < 0
                        THEN ABS(amount) ELSE 0 END), 0) AS expenses
                FROM "{tenant_schema}".transactions
                WHERE date >= :start
            """), {"start": seven_days_ago})
            week = week_result.fetchone()

            # YTD
            ytd_result = await db.execute(text(f"""
                SELECT
                    COALESCE(SUM(CASE WHEN amount > 0
                        THEN amount ELSE 0 END), 0) AS income,
                    COALESCE(SUM(CASE WHEN amount < 0
                        THEN ABS(amount) ELSE 0 END), 0) AS expenses
                FROM "{tenant_schema}".transactions
                WHERE date >= :start
            """), {"start": tax_year_start})
            ytd = ytd_result.fetchone()

            # Outstanding invoices
            inv_result = await db.execute(text(f"""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'overdue')
                        AS overdue_count,
                    COALESCE(SUM(total) FILTER (
                        WHERE status IN ('sent','overdue')), 0)
                        AS outstanding
                FROM "{tenant_schema}".invoices
            """))
            inv = inv_result.fetchone()

        week_net = float(week.income) - float(week.expenses)
        ytd_net = float(ytd.income) - float(ytd.expenses)

        return (
            f"📊 *Financial Summary*\n\n"
            f"*This week*\n"
            f"  Income: £{float(week.income):,.2f}\n"
            f"  Expenses: £{float(week.expenses):,.2f}\n"
            f"  Net: £{week_net:+,.2f}\n\n"
            f"*Year to date*\n"
            f"  Income: £{float(ytd.income):,.2f}\n"
            f"  Expenses: £{float(ytd.expenses):,.2f}\n"
            f"  Net profit: £{ytd_net:+,.2f}\n\n"
            f"*Invoices*\n"
            f"  Outstanding: £{float(inv.outstanding):,.2f}\n"
            f"  Overdue: {int(inv.overdue_count)}"
            + (
                "\n\n⚠️ *You have overdue invoices!*"
                if int(inv.overdue_count) > 0
                else ""
            )
        )
    except Exception as e:
        logger.error("Financial summary error: %s", e)
        return "❌ Could not load financial data. Please try again."


async def _get_tax_summary(tenant_schema: str) -> str:
    """Returns a short tax estimate summary."""
    try:
        from app.services.tax_engine import fetch_ytd_figures, build_tax_estimate
        from app.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            gross, expenses = await fetch_ytd_figures(tenant_schema, db)

        estimate = build_tax_estimate(gross, expenses)

        return (
            f"🧾 *Tax Estimate — {estimate.tax_year}*\n\n"
            f"  Gross income: £{float(estimate.gross_income):,.2f}\n"
            f"  Allowable expenses: £{float(estimate.allowable_expenses):,.2f}\n"
            f"  Net profit: £{float(estimate.net_profit):,.2f}\n\n"
            f"  Income tax: £{float(estimate.income_tax):,.2f}\n"
            f"  NI Class 2: £{float(estimate.ni_class2):,.2f}\n"
            f"  NI Class 4: £{float(estimate.ni_class4):,.2f}\n\n"
            f"  *Total liability: £{float(estimate.total_liability):,.2f}*\n"
            f"  Effective rate: {float(estimate.effective_rate):.1f}%\n\n"
            f"  Jan payment on account: "
            f"£{float(estimate.payment_on_account_jan):,.2f}\n"
            f"  Jul payment on account: "
            f"£{float(estimate.payment_on_account_jul):,.2f}"
        )
    except Exception as e:
        logger.error("Tax summary error: %s", e)
        return "❌ Could not load tax data. Please try again."


# ── Command handlers ──────────────────────────────────────────────────────────

async def start_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    chat_id = update.effective_chat.id
    user, _ = await _get_user_by_telegram_id(chat_id)

    keyboard = [["/summary", "/tax"], ["/chat", "/help"]]
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    if user:
        await update.message.reply_text(
            f"👋 Welcome back to *FreelanceCFO*!\n\n"
            f"Your account is linked ({user.email}).\n"
            f"What would you like to know?",
            parse_mode="Markdown",
            reply_markup=markup,
        )
    else:
        await update.message.reply_text(
            "👋 Welcome to *FreelanceCFO*!\n\n"
            "I'm your AI-powered financial assistant.\n\n"
            "To get started, link your account:\n"
            "1. Register at http://localhost:3000\n"
            "2. Go to Profile → copy your Chat ID\n"
            f"3. Your Telegram Chat ID is: `{chat_id}`\n\n"
            "Once linked, you can check your finances here anytime.",
            parse_mode="Markdown",
        )


async def help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "📖 *FreelanceCFO Commands*\n\n"
        "/summary — weekly financial snapshot\n"
        "/tax — current Self Assessment estimate\n"
        "/chat — ask the AI CFO anything\n"
        "/start — show welcome message\n\n"
        "Or just type any question and I'll answer it!",
        parse_mode="Markdown",
    )


async def summary_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    chat_id = update.effective_chat.id
    user, schema = await _get_user_by_telegram_id(chat_id)

    if not user:
        await _send_not_linked(update)
        return

    await update.message.reply_text("⏳ Loading your summary...")
    summary = await _get_financial_summary(schema)
    await update.message.reply_text(summary, parse_mode="Markdown")


async def tax_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    chat_id = update.effective_chat.id
    user, schema = await _get_user_by_telegram_id(chat_id)

    if not user:
        await _send_not_linked(update)
        return

    await update.message.reply_text("⏳ Calculating your tax estimate...")
    summary = await _get_tax_summary(schema)
    await update.message.reply_text(summary, parse_mode="Markdown")


async def chat_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """Handle /chat <question>"""
    if not context.args:
        await update.message.reply_text(
            "Usage: /chat <your question>\n"
            "Example: /chat What's my biggest expense this month?"
        )
        return

    question = " ".join(context.args)
    await _handle_cfo_question(update, question)


async def handle_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """Handle plain text messages as CFO questions."""
    question = update.message.text
    await _handle_cfo_question(update, question)


async def _handle_cfo_question(update: Update, question: str):
    """Shared handler for CFO questions from /chat or plain text."""
    chat_id = update.effective_chat.id
    user, schema = await _get_user_by_telegram_id(chat_id)

    await update.message.reply_text("🤔 Thinking...")

    try:
        from app.services.ai_cfo import chat_full_response
        from app.services.context_injector import build_financial_context
        from app.db.session import AsyncSessionLocal

        if user and schema:
            async with AsyncSessionLocal() as db:
                context_str = await build_financial_context(schema, db)
        else:
            context_str = (
                "No financial account linked. "
                "Provide general freelance financial advice."
            )

        response = await chat_full_response(
            user_message=question,
            financial_context=context_str,
            conversation_history=[],
        )

        # Telegram has 4096 char limit — split if needed
        if len(response) <= 4096:
            await update.message.reply_text(
                f"💼 {response}", parse_mode="Markdown"
            )
        else:
            # Send in chunks
            chunks = [
                response[i:i+4000]
                for i in range(0, len(response), 4000)
            ]
            for chunk in chunks:
                await update.message.reply_text(chunk)

    except Exception as e:
        logger.error("Telegram CFO error: %s", e)
        await update.message.reply_text(
            "Sorry, I couldn't process that. Please try again."
        )


async def _send_not_linked(update: Update):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        "⚠️ *Account not linked*\n\n"
        "To use financial features:\n"
        "1. Register at http://localhost:3000\n"
        "2. Go to Profile settings\n"
        f"3. Enter your Chat ID: `{chat_id}`\n\n"
        "You can still use /chat for general advice.",
        parse_mode="Markdown",
    )


# ── Entry point ───────────────────────────────────────────────────────────────

def run_bot():
    """Starts the bot with long polling. Blocks forever."""
    import sys
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    from app.core.config import settings

    if not settings.telegram_bot_token:
        logger.warning(
            "TELEGRAM_BOT_TOKEN not set — Telegram bot not started"
        )
        return

    logger.info("Starting Telegram bot...")

    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("summary", summary_command))
    application.add_handler(CommandHandler("tax", tax_command))
    application.add_handler(CommandHandler("chat", chat_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    logger.info("Telegram bot running — polling for messages")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    run_bot()