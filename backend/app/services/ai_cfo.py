"""
CFO chat service using Gemini 2.0 Flash-Lite.
Supports both full-response (REST) and streaming (WebSocket) modes.
Conversation history stored in PostgreSQL tenant schema.
"""
import json
import logging
import uuid
import asyncio
from datetime import datetime
from typing import AsyncGenerator
import google.generativeai as genai

from app.core.config import settings
from app.services.context_injector import SYSTEM_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)

genai.configure(api_key=settings.gemini_api_key)
model = genai.GenerativeModel("gemini-2.5-flash-lite")

MAX_HISTORY_MESSAGES = 20   # keep last 20 messages in context window
MAX_MESSAGE_LENGTH = 2000   # prevent token bloat from very long inputs


def _sanitise_message(text: str) -> str:
    """Basic input sanitisation — truncate and strip control chars."""
    import re
    cleaned = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    return cleaned.strip()[:MAX_MESSAGE_LENGTH]


def _build_system_prompt(financial_context: str) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(financial_context=financial_context)


def _messages_to_gemini_history(messages: list[dict]) -> list[dict]:
    """
    Converts our stored message format to Gemini's expected format.
    Our format: [{"role": "user"|"assistant", "content": "..."}]
    Gemini format: [{"role": "user"|"model", "parts": ["..."]}]
    Note: Gemini uses "model" not "assistant"
    """
    history = []
    for msg in messages[-MAX_HISTORY_MESSAGES:]:
        role = "model" if msg["role"] == "assistant" else "user"
        history.append({
            "role": role,
            "parts": [msg["content"]],
        })
    return history


async def chat_full_response(
    user_message: str,
    financial_context: str,
    conversation_history: list[dict],
) -> str | None:
    """
    Sends message to Gemini and returns complete response as string.
    Returns None on failure so the caller can skip saving to history.
    Used by REST endpoint.
    """
    sanitised = _sanitise_message(user_message)
    system_prompt = _build_system_prompt(financial_context)

    # Gemini handles system prompt via first user message if no system role
    history = _messages_to_gemini_history(conversation_history)

    try:
        chat = model.start_chat(history=history)

        # Prepend system prompt to first message if no history
        if not history:
            full_message = f"{system_prompt}\n\nUser: {sanitised}"
        else:
            full_message = sanitised

        response = await asyncio.to_thread(
            chat.send_message, full_message
        )

        return response.text

    except Exception as e:
        logger.exception("Gemini CFO chat error: %s", e)
        return None


async def chat_streaming(
    user_message: str,
    financial_context: str,
    conversation_history: list[dict],
) -> AsyncGenerator[str, None]:
    """
    Streams Gemini response token by token.
    Used by WebSocket endpoint — yields text chunks as they arrive.
    """
    sanitised = _sanitise_message(user_message)
    system_prompt = _build_system_prompt(financial_context)
    history = _messages_to_gemini_history(conversation_history)

    try:
        chat = model.start_chat(history=history)

        if not history:
            full_message = f"{system_prompt}\n\nUser: {sanitised}"
        else:
            full_message = sanitised

        # generate_content with stream=True returns an iterator
        response_iter = await asyncio.to_thread(
            model.generate_content,
            full_message,
            stream=True,
        )

        for chunk in response_iter:
            if chunk.text:
                yield chunk.text
                await asyncio.sleep(0)  # yield control to event loop

    except Exception as e:
        logger.exception("Gemini streaming error: %s", e)
        yield "I'm having trouble connecting. Please try again."