import uuid
import pytest
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


@pytest.fixture
def auth_client():
    """Client with auth bypassed — returns a fake user directly."""
    mock_user = make_mock_user()
    app.dependency_overrides[get_current_user] = lambda: mock_user

    import pytest_asyncio
    return mock_user


@pytest.mark.asyncio
async def test_create_transaction():
    mock_user = make_mock_user()
    app.dependency_overrides[get_current_user] = lambda: mock_user

    mock_row = MagicMock()
    mock_row.id = uuid.uuid4()
    mock_row.date = "2024-03-01"
    mock_row.description = "Test payment"
    mock_row.amount = 500.00
    mock_row.currency = "GBP"
    mock_row.category_id = None
    mock_row.confidence = 1.0
    mock_row.source = "manual"
    mock_row.is_confirmed = True
    mock_row.notes = None

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = mock_row
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    app.dependency_overrides[get_db] = lambda: mock_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post("/api/v1/transactions", json={
            "date": "2024-03-01",
            "description": "Test payment",
            "amount": 500.00,
            "currency": "GBP",
        })

    assert response.status_code == 201
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_import_csv_invalid_extension():
    mock_user = make_mock_user()
    app.dependency_overrides[get_current_user] = lambda: mock_user

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post(
            "/api/v1/transactions/import/csv",
            files={"file": ("statement.txt", b"date,desc,amount", "text/plain")},
        )

    assert response.status_code == 400
    assert "csv" in response.json()["detail"].lower()
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_import_csv_accepted():
    mock_user = make_mock_user()
    app.dependency_overrides[get_current_user] = lambda: mock_user

    csv_content = b"date,description,amount\n2024-03-01,Test payment,500.00"

    with patch("app.api.v1.transaction.parse_csv_task") as mock_task:
        mock_task.delay.return_value = MagicMock(id="fake-task-id")

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/v1/transactions/import/csv",
                files={"file": ("statement.csv", csv_content, "text/csv")},
            )

    assert response.status_code == 202
    assert "task_id" in response.json()
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_unauthenticated_request():
    """No token = 403."""
    app.dependency_overrides.clear()  # Remove any auth override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/v1/transactions")

    assert response.status_code == 403


def test_parse_csv_valid():
    from app.services.statement_parser import parse_csv
    csv_bytes = b"date,description,amount\n2024-03-01,Amazon AWS,- 49.99\n2024-03-02,Client Payment,1500.00"
    result = parse_csv(csv_bytes)
    assert len(result) == 2
    assert result[0]["description"] == "Amazon AWS"
    assert result[1]["amount"] == 1500.00


def test_parse_csv_missing_columns():
    from app.services.statement_parser import parse_csv
    csv_bytes = b"col1,col2\nfoo,bar"
    try:
        parse_csv(csv_bytes)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "missing" in str(e).lower()