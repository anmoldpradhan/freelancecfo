"""
Telegram bot for FreelanceCFO.
Commands:
  /start  — welcome + link account instructions
  /chat   — ask the AI CFO a question
  /summary — get financial snapshot

Run standalone: python -m app.services.telegram_bot
"""
import asyncio
import logging
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)

from app.core.config import settings

logger = logging.getLogger(__name__)

# Maps telegram user_id → FreelanceCFO user context
# In production: store this in Redis with user's JWT
_telegram_sessions: dict[int, dict] = {}


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to *FreelanceCFO*!\n\n"
        "I'm your AI-powered financial assistant.\n\n"
        "Commands:\n"
        "• /chat <question> — ask your CFO anything\n"
        "• /summary — get your financial snapshot\n\n"
        "To link your account, visit the FreelanceCFO dashboard.",
        parse_mode="Markdown",
    )


async def chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /chat <question>"""
    if not context.args:
        await update.message.reply_text(
            "Usage: /chat <your question>\n"
            "Example: /chat What's my net profit this month?"
        )
        return

    question = " ".join(context.args)
    await update.message.reply_text("🤔 Thinking...")

    try:
        from app.services.ai_cfo import chat_full_response
        response = await chat_full_response(
            user_message=question,
            financial_context="No financial data linked yet.",
            conversation_history=[],
        )
        await update.message.reply_text(f"💼 {response}")
    except Exception as e:
        logger.error("Telegram chat error: %s", e)
        await update.message.reply_text(
            "Sorry, I couldn't process that. Please try again."
        )


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /summary — shows financial snapshot."""
    await update.message.reply_text(
        "📊 *Financial Summary*\n\n"
        "Link your FreelanceCFO account on the dashboard "
        "to see your real financial data here.",
        parse_mode="Markdown",
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plain text messages (treated as CFO questions)."""
    question = update.message.text
    await update.message.reply_text("🤔 Thinking...")

    try:
        from app.services.ai_cfo import chat_full_response
        response = await chat_full_response(
            user_message=question,
            financial_context="No financial data linked yet.",
            conversation_history=[],
        )
        await update.message.reply_text(f"💼 {response}")
    except Exception as e:
        logger.error("Telegram message error: %s", e)
        await update.message.reply_text("Sorry, please try again.")


def run_bot():
    """Entry point — runs the bot with long polling."""
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not set — bot not started")
        return

    app = Application.builder().token(settings.telegram_bot_token).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("chat", chat_command))
    app.add_handler(CommandHandler("summary", summary_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Telegram bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    run_bot()