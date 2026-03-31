import pytest
import json
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.dependencies import get_db, get_current_user


def make_mock_user():
    user = MagicMock()
    user.id = "test-user-id"
    user.tenant_schema = "tenant_test"
    user.is_active = True
    return user


# ── Context injector tests ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_financial_context_returns_string():
    from app.services.context_injector import build_financial_context

    mock_db = AsyncMock()
    mock_result = MagicMock()

    # Simulate all 4 DB queries returning empty results
    empty_row = MagicMock()
    empty_row.income_90d = 0
    empty_row.expenses_90d = 0
    empty_row.tx_count = 0
    empty_row.avg_income_tx = 0
    empty_row.ytd_income = 0
    empty_row.ytd_expenses = 0
    empty_row.sent_count = 0
    empty_row.overdue_count = 0
    empty_row.outstanding_amount = 0

    mock_result.fetchone.return_value = empty_row
    mock_result.fetchall.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    context = await build_financial_context("tenant_test", mock_db)

    assert isinstance(context, str)
    assert "FINANCIAL CONTEXT" in context
    assert "£0.00" in context


@pytest.mark.asyncio
async def test_build_financial_context_handles_db_error():
    from app.services.context_injector import build_financial_context

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=Exception("DB error"))

    context = await build_financial_context("tenant_test", mock_db)
    assert "unavailable" in context.lower()


# ── CFO service tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_full_response_returns_string():
    from app.services.ai_cfo import chat_full_response

    mock_response = MagicMock()
    mock_response.text = "Your net profit for the last 90 days is £2,450."

    with patch("app.services.ai_cfo.model") as mock_model:
        mock_chat = MagicMock()
        mock_chat.send_message.return_value = mock_response
        mock_model.start_chat.return_value = mock_chat

        result = await chat_full_response(
            user_message="What's my net profit?",
            financial_context="Income: £3000, Expenses: £550",
            conversation_history=[],
        )

    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_chat_full_response_handles_api_error():
    from app.services.ai_cfo import chat_full_response

    with patch("app.services.ai_cfo.model") as mock_model:
        mock_chat = MagicMock()
        mock_chat.send_message.side_effect = Exception("API error")
        mock_model.start_chat.return_value = mock_chat

        result = await chat_full_response(
            user_message="What's my profit?",
            financial_context="",
            conversation_history=[],
        )

    assert result is None  # on error, returns None so caller can raise 503


def test_messages_to_gemini_history():
    from app.services.ai_cfo import _messages_to_gemini_history

    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]
    result = _messages_to_gemini_history(messages)
    assert result[0]["role"] == "user"
    assert result[1]["role"] == "model"  # assistant → model
    assert result[0]["parts"] == ["Hello"]


def test_messages_to_gemini_history_truncates():
    from app.services.ai_cfo import _messages_to_gemini_history, MAX_HISTORY_MESSAGES

    # Create 30 messages — should be truncated to MAX_HISTORY_MESSAGES
    messages = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
        for i in range(30)
    ]
    result = _messages_to_gemini_history(messages)
    assert len(result) <= MAX_HISTORY_MESSAGES


def test_sanitise_message():
    from app.services.ai_cfo import _sanitise_message, MAX_MESSAGE_LENGTH

    long_msg = "x" * 3000
    assert len(_sanitise_message(long_msg)) <= MAX_MESSAGE_LENGTH

    control_chars = "hello\x00\x01world"
    assert "\x00" not in _sanitise_message(control_chars)


# ── _get_or_create_conversation unit tests ────────────────────────────────────

@pytest.mark.asyncio
async def test_get_or_create_conversation_new():
    from app.api.v1.cfo import _get_or_create_conversation

    mock_db = AsyncMock()
    # fetchone returns None → no existing conversation → creates new
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    conv_id, history = await _get_or_create_conversation("tenant_test", None, mock_db)

    assert isinstance(conv_id, str)
    assert len(conv_id) == 36        # UUID format
    assert history == []
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_get_or_create_conversation_existing():
    from app.api.v1.cfo import _get_or_create_conversation
    import uuid

    existing_id = uuid.uuid4()
    mock_row = MagicMock()
    mock_row.id = existing_id
    mock_row.messages = [{"role": "user", "content": "Hello"}]

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = mock_row
    mock_db.execute = AsyncMock(return_value=mock_result)

    conv_id, history = await _get_or_create_conversation(
        "tenant_test", existing_id, mock_db
    )

    assert conv_id == str(existing_id)
    assert len(history) == 1
    mock_db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_save_messages():
    from app.api.v1.cfo import _save_messages

    mock_row = MagicMock()
    mock_row.messages = [{"role": "user", "content": "Previous message"}]

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = mock_row
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    await _save_messages(
        "tenant_test", "conv-123",
        "New user message", "AI response", mock_db
    )

    mock_db.commit.assert_called_once()
    # Two execute calls: SELECT then UPDATE
    assert mock_db.execute.call_count == 2


# ── CFO REST endpoint tests ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cfo_chat_endpoint():
    mock_user = make_mock_user()
    app.dependency_overrides[get_current_user] = lambda: mock_user

    mock_db = AsyncMock()

    # Mock conversation creation
    mock_conv_result = MagicMock()
    mock_conv_result.fetchone.return_value = None  # no existing conv

    # Mock financial context queries
    empty_row = MagicMock()
    for attr in ["income_90d","expenses_90d","tx_count","avg_income_tx",
                 "ytd_income","ytd_expenses","sent_count","overdue_count",
                 "outstanding_amount"]:
        setattr(empty_row, attr, 0)

    mock_ctx_result = MagicMock()
    mock_ctx_result.fetchone.return_value = empty_row
    mock_ctx_result.fetchall.return_value = []

    mock_db.execute = AsyncMock(return_value=mock_ctx_result)
    mock_db.commit = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.api.v1.cfo.chat_full_response",
               new_callable=AsyncMock,
               return_value="Your finances look healthy!"):
        with patch("app.api.v1.cfo.build_financial_context",
                   new_callable=AsyncMock,
                   return_value="mock context"):
            with patch("app.api.v1.cfo._get_or_create_conversation",
                       new_callable=AsyncMock,
                       return_value=("conv-uuid-123", [])):
                with patch("app.api.v1.cfo._save_messages",
                           new_callable=AsyncMock):

                    async with AsyncClient(
                        transport=ASGITransport(app=app), base_url="http://test"
                    ) as ac:
                        response = await ac.post("/api/v1/cfo/chat", json={
                            "message": "How am I doing financially?",
                        })

    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert "conversation_id" in data
    assert data["response"] == "Your finances look healthy!"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_cfo_history_empty():
    mock_user = make_mock_user()
    app.dependency_overrides[get_current_user] = lambda: mock_user

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)
    app.dependency_overrides[get_db] = lambda: mock_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/v1/cfo/history")

    assert response.status_code == 200
    assert response.json() == []
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_cfo_clear_history():
    mock_user = make_mock_user()
    app.dependency_overrides[get_current_user] = lambda: mock_user

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock())
    mock_db.commit = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.delete("/api/v1/cfo/history")

    assert response.status_code == 204
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_cfo_chat_returns_503_when_ai_fails():
    mock_user = make_mock_user()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: AsyncMock()

    with patch("app.api.v1.cfo.chat_full_response", new_callable=AsyncMock, return_value=None), \
         patch("app.api.v1.cfo.build_financial_context", new_callable=AsyncMock, return_value="ctx"), \
         patch("app.api.v1.cfo._get_or_create_conversation", new_callable=AsyncMock, return_value=("conv-id", [])):

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post("/api/v1/cfo/chat", json={"message": "Hello"})

    assert response.status_code == 503
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_cfo_chat_unauthenticated():
    app.dependency_overrides.clear()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post("/api/v1/cfo/chat", json={
            "message": "What's my profit?"
        })

    assert response.status_code == 403