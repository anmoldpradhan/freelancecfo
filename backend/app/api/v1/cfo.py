import uuid
import json
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.dependencies import get_db, get_current_user
from app.models.user import User
from app.schemas.cfo import CFOChatRequest, CFOChatResponse, CFOHistoryResponse, CFOMessage
from app.services.ai_cfo import chat_full_response
from app.services.context_injector import build_financial_context

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/cfo", tags=["cfo"])


async def _get_or_create_conversation(
    tenant_schema: str,
    conversation_id,  # uuid.UUID | None
    db: AsyncSession,
) -> tuple[str, list[dict]]:
    """
    Fetches existing conversation or creates a new one.
    Returns (conversation_id, message_history).
    """
    if conversation_id:
        result = await db.execute(text(f"""
            SELECT id, messages FROM "{tenant_schema}".cfo_conversations
            WHERE id = :id
        """), {"id": str(conversation_id)})
        row = result.fetchone()
        if row:
            messages = row.messages if isinstance(row.messages, list) else []
            return str(row.id), messages

    # Create new conversation
    new_id = str(uuid.uuid4())
    await db.execute(text(f"""
        INSERT INTO "{tenant_schema}".cfo_conversations (id, messages)
        VALUES (:id, '[]'::jsonb)
    """), {"id": new_id})
    await db.commit()
    return new_id, []


async def _save_messages(
    tenant_schema: str,
    conversation_id: str,
    user_message: str,
    assistant_response: str,
    db: AsyncSession,
):
    """Appends user + assistant messages to conversation history."""
    now = datetime.now(timezone.utc).isoformat()

    result = await db.execute(text(f"""
        SELECT messages FROM "{tenant_schema}".cfo_conversations
        WHERE id = :id
    """), {"id": conversation_id})
    row = result.fetchone()
    messages = row.messages if row and isinstance(row.messages, list) else []

    messages.append({"role": "user", "content": user_message, "timestamp": now})
    messages.append({"role": "assistant", "content": assistant_response, "timestamp": now})

    await db.execute(text(f"""
        UPDATE "{tenant_schema}".cfo_conversations
        SET messages = CAST(:messages AS jsonb),
            updated_at = NOW()
        WHERE id = :id
    """), {
        "messages": json.dumps(messages),
        "id": conversation_id,
    })
    await db.commit()


@router.post("/chat", response_model=CFOChatResponse)
async def cfo_chat(
    payload: CFOChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """REST endpoint — returns full response at once."""
    schema = current_user.tenant_schema

    # Get conversation history
    conv_id, history = await _get_or_create_conversation(
        schema, payload.conversation_id, db
    )

    # Build financial context
    financial_context = await build_financial_context(schema, db)

    # Get Gemini response
    response_text = await chat_full_response(
        user_message=payload.message,
        financial_context=financial_context,
        conversation_history=history,
    )

    if response_text is None:
        raise HTTPException(
            status_code=503,
            detail="AI service unavailable. Please try again in a moment.",
        )

    # Save to DB only on success
    await _save_messages(schema, conv_id, payload.message, response_text, db)

    return CFOChatResponse(
        response=response_text,
        conversation_id=conv_id,
    )


@router.get("/history", response_model=list[CFOHistoryResponse])
async def get_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    schema = current_user.tenant_schema

    result = await db.execute(text(f"""
        SELECT id, messages, created_at, updated_at
        FROM "{schema}".cfo_conversations
        ORDER BY updated_at DESC
        LIMIT 20
    """))
    rows = result.fetchall()

    return [
        CFOHistoryResponse(
            conversation_id=str(r.id),
            messages=[CFOMessage(**m) for m in (r.messages or [])],
            created_at=str(r.created_at),
            updated_at=str(r.updated_at),
        )
        for r in rows
    ]


@router.delete("/history", status_code=204)
async def clear_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    schema = current_user.tenant_schema
    await db.execute(text(f"""
        DELETE FROM "{schema}".cfo_conversations
    """))
    await db.commit()
    return None