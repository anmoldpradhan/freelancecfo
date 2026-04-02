"""Tests for /api/v1/profile endpoints."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.dependencies import get_db, get_current_user


def _make_mock_user():
    user = MagicMock()
    user.id = "test-user-id"
    user.tenant_schema = "tenant_test"
    user.is_active = True
    return user


def _make_profile_row(**kwargs):
    defaults = dict(
        trading_name="Test Trading Ltd",
        base_currency="GBP",
        vat_registered=False,
        utr_number=None,
        stripe_account_id=None,
        telegram_chat_id=None,
    )
    defaults.update(kwargs)
    row = MagicMock()
    for k, v in defaults.items():
        setattr(row, k, v)
    return row


def _make_client(mock_user, mock_db):
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: mock_user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ── GET /api/v1/profile ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_profile_success():
    user = _make_mock_user()
    row = _make_profile_row(telegram_chat_id="12345")

    mock_result = MagicMock()
    mock_result.fetchone.return_value = row

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    async with _make_client(user, mock_db) as client:
        resp = await client.get("/api/v1/profile")

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["base_currency"] == "GBP"
    assert data["telegram_chat_id"] == "12345"


@pytest.mark.asyncio
async def test_get_profile_not_found():
    user = _make_mock_user()

    mock_result = MagicMock()
    mock_result.fetchone.return_value = None

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    async with _make_client(user, mock_db) as client:
        resp = await client.get("/api/v1/profile")

    app.dependency_overrides.clear()
    assert resp.status_code == 404


# ── PATCH /api/v1/profile ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_patch_profile_success():
    user = _make_mock_user()
    updated_row = _make_profile_row(
        trading_name="New Name Ltd",
        telegram_chat_id="99999",
    )

    mock_result = MagicMock()
    mock_result.fetchone.return_value = updated_row

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    async with _make_client(user, mock_db) as client:
        resp = await client.patch("/api/v1/profile", json={
            "trading_name": "New Name Ltd",
            "telegram_chat_id": "99999",
        })

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert data["trading_name"] == "New Name Ltd"


@pytest.mark.asyncio
async def test_patch_profile_telegram_chat_id_included_in_db_write():
    """Regression: telegram_chat_id must be in the SET clause, not added after commit."""
    user = _make_mock_user()
    updated_row = _make_profile_row(telegram_chat_id="55555")

    mock_result = MagicMock()
    mock_result.fetchone.return_value = updated_row

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    async with _make_client(user, mock_db) as client:
        await client.patch("/api/v1/profile", json={"telegram_chat_id": "55555"})

    app.dependency_overrides.clear()

    # The SQL execute must have been called before commit (not after)
    execute_call_index = mock_db.method_calls.index(
        next(c for c in mock_db.method_calls if "execute" in str(c))
    )
    commit_call_index = mock_db.method_calls.index(
        next(c for c in mock_db.method_calls if "commit" in str(c))
    )
    assert execute_call_index < commit_call_index

    # And the SQL string must contain telegram_chat_id
    sql_text = str(mock_db.execute.call_args[0][0])
    assert "telegram_chat_id" in sql_text


@pytest.mark.asyncio
async def test_patch_profile_no_fields_returns_400():
    user = _make_mock_user()
    mock_db = AsyncMock()

    async with _make_client(user, mock_db) as client:
        resp = await client.patch("/api/v1/profile", json={})

    app.dependency_overrides.clear()
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_patch_profile_currency_uppercased():
    user = _make_mock_user()
    updated_row = _make_profile_row(base_currency="EUR")

    mock_result = MagicMock()
    mock_result.fetchone.return_value = updated_row

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    async with _make_client(user, mock_db) as client:
        await client.patch("/api/v1/profile", json={"base_currency": "eur"})

    app.dependency_overrides.clear()

    sql_params = mock_db.execute.call_args[0][1]
    assert sql_params["base_currency"] == "EUR"
