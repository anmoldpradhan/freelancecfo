import pytest
import json
from unittest.mock import patch, MagicMock, AsyncMock
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.dependencies import get_db, get_current_user


def make_mock_user():
    user = MagicMock()
    user.id = "test-user-id"
    user.email = "test@example.com"
    user.tenant_schema = "tenant_test"
    user.is_active = True
    return user


@pytest.mark.asyncio
async def test_onboard_stripe_not_configured():
    """Returns 503 when Stripe key missing."""
    mock_user = make_mock_user()
    app.dependency_overrides[get_current_user] = lambda: mock_user

    with patch("app.api.v1.stripe_webhooks.settings") as mock_settings:
        mock_settings.stripe_secret_key = ""
        mock_settings.stripe_webhook_secret = "whsec_test"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/stripe/onboard")

    assert response.status_code == 503
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_webhook_missing_secret():
    """Returns 503 when webhook secret missing."""
    with patch("app.api.v1.stripe_webhooks.settings") as mock_settings:
        mock_settings.stripe_webhook_secret = ""
        mock_settings.stripe_secret_key = "sk_test_fake"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/v1/stripe/webhook",
                content=b'{"type":"test"}',
            )

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_webhook_invalid_signature():
    """Rejects webhook with bad signature."""
    import stripe

    with patch("app.api.v1.stripe_webhooks.settings") as mock_settings:
        mock_settings.stripe_webhook_secret = "whsec_test"
        mock_settings.stripe_secret_key = "sk_test_fake"

        with patch.object(
            stripe.Webhook,
            "construct_event",
            side_effect=stripe.error.SignatureVerificationError("bad sig", "sig_header"),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                response = await ac.post(
                    "/api/v1/stripe/webhook",
                    content=b'{"type":"test"}',
                    headers={"stripe-signature": "bad_sig"},
                )

    assert response.status_code == 400
    assert "signature" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_webhook_payment_succeeded():
    """Valid webhook triggers transaction creation."""
    import stripe

    mock_event = {
        "type": "payment_intent.succeeded",
        "id": "evt_test_123",
        "data": {
            "object": {
                "id": "pi_test_123",
                "amount_received": 150000,  # £1500.00 in pence
                "currency": "gbp",
                "description": "Invoice payment",
                "on_behalf_of": "acct_test_123",
                "transfer_data": {},
            }
        }
    }

    mock_db = AsyncMock()
    mock_user_row = MagicMock()
    mock_user_row.id = "user-uuid"
    mock_user_row.tenant_schema = "tenant_test"

    mock_cat_row = MagicMock()
    mock_cat_row.id = "cat-uuid"

    mock_result_user = MagicMock()
    mock_result_user.fetchone.return_value = mock_user_row

    mock_result_cat = MagicMock()
    mock_result_cat.fetchone.return_value = mock_cat_row

    mock_db.execute = AsyncMock(
        side_effect=[mock_result_user, mock_result_cat, MagicMock()]
    )
    mock_db.commit = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.api.v1.stripe_webhooks.settings") as mock_settings:
        mock_settings.stripe_webhook_secret = "whsec_test"
        mock_settings.stripe_secret_key = "sk_test_fake"

        with patch.object(stripe.Webhook, "construct_event", return_value=mock_event):
            with patch("app.api.v1.stripe_webhooks.redis_client") as mock_redis:
                mock_redis.publish = AsyncMock()

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as ac:
                    response = await ac.post(
                        "/api/v1/stripe/webhook",
                        content=b'{"fake": "payload"}',
                        headers={"stripe-signature": "valid_sig"},
                    )

    assert response.status_code == 200
    assert response.json()["received"] is True
    assert response.json()["event_type"] == "payment_intent.succeeded"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_webhook_unknown_event_type():
    """Unknown event types are accepted but ignored."""
    import stripe

    mock_event = {
        "type": "customer.created",
        "id": "evt_test_456",
        "data": {"object": {}}
    }

    mock_db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.api.v1.stripe_webhooks.settings") as mock_settings:
        mock_settings.stripe_webhook_secret = "whsec_test"
        mock_settings.stripe_secret_key = "sk_test_fake"

        with patch.object(stripe.Webhook, "construct_event", return_value=mock_event):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                response = await ac.post(
                    "/api/v1/stripe/webhook",
                    content=b'{"fake": "payload"}',
                    headers={"stripe-signature": "valid_sig"},
                )

    assert response.status_code == 200
    assert response.json()["event_type"] == "customer.created"
    app.dependency_overrides.clear()


# ── WebSocket manager unit tests ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_websocket_manager_connect_disconnect():
    from app.core.websocket_manager import WebSocketManager

    manager = WebSocketManager()
    mock_ws = AsyncMock()

    await manager.connect(mock_ws, "user-123")
    assert "user-123" in manager._connections
    assert mock_ws in manager._connections["user-123"]

    manager.disconnect(mock_ws, "user-123")
    assert "user-123" not in manager._connections


@pytest.mark.asyncio
async def test_websocket_manager_send_to_user():
    from app.core.websocket_manager import WebSocketManager

    manager = WebSocketManager()
    mock_ws = AsyncMock()
    await manager.connect(mock_ws, "user-456")

    await manager.send_to_user("user-456", {"type": "payment_received", "amount": 500})
    mock_ws.send_json.assert_called_once_with(
        {"type": "payment_received", "amount": 500}
    )


@pytest.mark.asyncio
async def test_websocket_manager_send_to_nonexistent_user():
    """Sending to a user with no connections should not crash."""
    from app.core.websocket_manager import WebSocketManager

    manager = WebSocketManager()
    # No exception should be raised
    await manager.send_to_user("ghost-user", {"type": "test"})