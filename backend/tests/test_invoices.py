import uuid
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.dependencies import get_db, get_current_user


def make_mock_user():
    user = MagicMock()
    user.id = "test-user-id"
    user.tenant_schema = "tenant_test"
    user.is_active = True
    return user


SAMPLE_INVOICE_PAYLOAD = {
    "client_name": "ACME Ltd",
    "client_email": "accounts@acme.com",
    "line_items": [
        {"description": "Web development", "quantity": 10, "unit_price": 150.00},
        {"description": "Design work", "quantity": 5, "unit_price": 80.00},
    ],
    "tax_rate": 20.0,
    "currency": "GBP",
    "issued_date": "2024-03-01",
    "due_date": "2024-03-31",
}


def make_mock_invoice_row():
    row = MagicMock()
    row.id = uuid.uuid4()
    row.invoice_number = "INV-TEST-123456"
    row.client_name = "ACME Ltd"
    row.client_email = "accounts@acme.com"
    row.line_items = [
        {"description": "Web development", "quantity": 10, "unit_price": 150.0}
    ]
    row.subtotal = 1900.00
    row.tax_rate = 20.0
    row.total = 2280.00
    row.currency = "GBP"
    row.status = "draft"
    row.issued_date = "2024-03-01"
    row.due_date = "2024-03-31"
    row.paid_date = None
    row.pdf_s3_key = None
    return row


@pytest.mark.asyncio
async def test_create_invoice():
    mock_user = make_mock_user()
    app.dependency_overrides[get_current_user] = lambda: mock_user

    mock_row = make_mock_invoice_row()
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = mock_row
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post("/api/v1/invoices", json=SAMPLE_INVOICE_PAYLOAD)

    assert response.status_code == 201
    data = response.json()
    assert data["client_name"] == "ACME Ltd"
    assert data["status"] == "draft"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_invoice_empty_line_items():
    mock_user = make_mock_user()
    app.dependency_overrides[get_current_user] = lambda: mock_user

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post("/api/v1/invoices", json={
            **SAMPLE_INVOICE_PAYLOAD,
            "line_items": [],
        })

    assert response.status_code == 422
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_invoice_invalid_tax_rate():
    mock_user = make_mock_user()
    app.dependency_overrides[get_current_user] = lambda: mock_user

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post("/api/v1/invoices", json={
            **SAMPLE_INVOICE_PAYLOAD,
            "tax_rate": 150.0,
        })

    assert response.status_code == 422
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_status_invalid():
    mock_user = make_mock_user()
    app.dependency_overrides[get_current_user] = lambda: mock_user

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.patch(
            "/api/v1/invoices/some-uuid/status",
            json={"status": "invalid_status"},
        )

    assert response.status_code == 422
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_send_voided_invoice():
    mock_user = make_mock_user()
    app.dependency_overrides[get_current_user] = lambda: mock_user

    mock_row = MagicMock()
    mock_row.status = "void"
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = mock_row
    mock_db.execute = AsyncMock(return_value=mock_result)
    app.dependency_overrides[get_db] = lambda: mock_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post(f"/api/v1/invoices/{uuid.uuid4()}/send")

    assert response.status_code == 400
    assert "void" in response.json()["detail"].lower()
    app.dependency_overrides.clear()


def test_generate_pdf_produces_bytes():
    from app.services.invoice_engine import generate_pdf
    invoice_data = {
        "invoice_number": "INV-TEST-001",
        "client_name": "Test Client",
        "client_email": "test@example.com",
        "line_items": [
            {"description": "Dev work", "quantity": 5, "unit_price": 100.0}
        ],
        "subtotal": 500.0,
        "tax_rate": 20.0,
        "total": 600.0,
        "currency": "GBP",
        "status": "draft",
        "issued_date": "2024-03-01",
        "due_date": "2024-03-31",
        "trading_name": "Test Co",
        "from_name": "Jane Developer",
        "from_address": "123 Code St\nLondon",
        "vat_number": None,
    }
    fake_pdf = b"%PDF-1.4 fake pdf content for testing purposes only padding"
    with patch("app.services.invoice_engine.HTML") as mock_html:
        mock_html.return_value.write_pdf.return_value = fake_pdf
        pdf_bytes = generate_pdf(invoice_data)

    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes[:4] == b"%PDF"


def test_calculate_totals():
    from app.api.v1.invoices import _calculate_totals
    from app.schemas.invoice import LineItem
    from decimal import Decimal

    items = [
        LineItem(description="Dev", quantity=Decimal("10"), unit_price=Decimal("150")),
        LineItem(description="Design", quantity=Decimal("5"), unit_price=Decimal("80")),
    ]
    subtotal, total = _calculate_totals(items, Decimal("20"))
    assert subtotal == 1900.0
    assert total == 2280.0


def test_s3_upload_skipped_without_config():
    from app.services.invoice_engine import upload_pdf_to_s3
    result = upload_pdf_to_s3(b"%PDF-fake", "INV-TEST-001")
    assert result == ""   # returns empty string, no crash


def test_s3_upload_with_config():
    from app.services.invoice_engine import upload_pdf_to_s3
    with patch("app.services.invoice_engine.settings") as mock_settings, \
         patch("app.services.invoice_engine.boto3") as mock_boto3:
        mock_settings.aws_s3_bucket = "test-bucket"
        mock_settings.aws_access_key_id = "AKIATEST"
        mock_settings.aws_secret_access_key = "secret"
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3
        result = upload_pdf_to_s3(b"%PDF-fake", "INV-TEST-002")
    assert result == "invoices/INV-TEST-002.pdf"
    mock_s3.put_object.assert_called_once()


def test_s3_upload_failure_returns_empty():
    from app.services.invoice_engine import upload_pdf_to_s3
    with patch("app.services.invoice_engine.settings") as mock_settings, \
         patch("app.services.invoice_engine.boto3") as mock_boto3:
        mock_settings.aws_s3_bucket = "test-bucket"
        mock_settings.aws_access_key_id = "AKIATEST"
        mock_settings.aws_secret_access_key = "secret"
        mock_boto3.client.return_value.put_object.side_effect = Exception("S3 error")
        result = upload_pdf_to_s3(b"%PDF-fake", "INV-TEST-003")
    assert result == ""


def test_download_pdf_from_s3():
    from app.services.invoice_engine import download_pdf_from_s3
    with patch("app.services.invoice_engine.settings") as mock_settings, \
         patch("app.services.invoice_engine.boto3") as mock_boto3:
        mock_settings.aws_s3_bucket = "test-bucket"
        mock_settings.aws_access_key_id = "AKIATEST"
        mock_settings.aws_secret_access_key = "secret"
        mock_boto3.client.return_value.get_object.return_value = {
            "Body": MagicMock(read=lambda: b"%PDF-downloaded")
        }
        result = download_pdf_from_s3("invoices/INV-TEST-001.pdf")
    assert result == b"%PDF-downloaded"


def test_send_invoice_email_no_config():
    from app.services.invoice_engine import send_invoice_email
    with patch("app.services.invoice_engine.settings") as mock_settings:
        mock_settings.sendgrid_api_key = None
        result = send_invoice_email("a@b.com", "Client", "INV-001", 100.0, "GBP", b"pdf")
    assert result is False


def test_send_invoice_email_success():
    from app.services.invoice_engine import send_invoice_email
    with patch("app.services.invoice_engine.settings") as mock_settings, \
         patch("app.services.invoice_engine.SendGridAPIClient") as mock_sg:
        mock_settings.sendgrid_api_key = "SG.test"
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_sg.return_value.send.return_value = mock_response
        result = send_invoice_email("a@b.com", "Client", "INV-001", 100.0, "GBP", b"%PDF-fake")
    assert result is True


def test_send_invoice_email_failure():
    from app.services.invoice_engine import send_invoice_email
    with patch("app.services.invoice_engine.settings") as mock_settings, \
         patch("app.services.invoice_engine.SendGridAPIClient") as mock_sg:
        mock_settings.sendgrid_api_key = "SG.test"
        mock_sg.return_value.send.side_effect = Exception("SendGrid error")
        result = send_invoice_email("a@b.com", "Client", "INV-001", 100.0, "GBP", b"%PDF-fake")
    assert result is False


@pytest.mark.asyncio
async def test_list_invoices():
    mock_user = make_mock_user()
    app.dependency_overrides[get_current_user] = lambda: mock_user

    mock_row = make_mock_invoice_row()
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row]
    mock_db.execute = AsyncMock(return_value=mock_result)
    app.dependency_overrides[get_db] = lambda: mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/v1/invoices")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["client_name"] == "ACME Ltd"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_invoices_with_status_filter():
    mock_user = make_mock_user()
    app.dependency_overrides[get_current_user] = lambda: mock_user

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)
    app.dependency_overrides[get_db] = lambda: mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/v1/invoices?status=paid")

    assert response.status_code == 200
    assert response.json() == []
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_invoice_pdf_not_found():
    mock_user = make_mock_user()
    app.dependency_overrides[get_current_user] = lambda: mock_user

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)
    app.dependency_overrides[get_db] = lambda: mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get(f"/api/v1/invoices/{uuid.uuid4()}/pdf")

    assert response.status_code == 404
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_invoice_pdf_generates():
    mock_user = make_mock_user()
    mock_user.email = "owner@test.com"
    app.dependency_overrides[get_current_user] = lambda: mock_user

    mock_row = make_mock_invoice_row()
    mock_row.pdf_s3_key = None

    profile_row = MagicMock()
    profile_row.trading_name = "Test Co"

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=[
        MagicMock(**{"fetchone.return_value": mock_row}),   # invoice lookup
        MagicMock(**{"fetchone.return_value": profile_row}), # profile lookup
    ])
    app.dependency_overrides[get_db] = lambda: mock_db

    fake_pdf = b"%PDF-1.4 test"
    with patch("app.api.v1.invoices.generate_pdf", return_value=fake_pdf):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get(f"/api/v1/invoices/{uuid.uuid4()}/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_invoice_status_to_paid():
    mock_user = make_mock_user()
    app.dependency_overrides[get_current_user] = lambda: mock_user

    mock_row = make_mock_invoice_row()
    mock_row.status = "paid"
    mock_row.paid_date = "2024-03-15"
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = mock_row
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.patch(
            f"/api/v1/invoices/{uuid.uuid4()}/status",
            json={"status": "paid"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "paid"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_invoice_status_not_found():
    mock_user = make_mock_user()
    app.dependency_overrides[get_current_user] = lambda: mock_user

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.patch(
            f"/api/v1/invoices/{uuid.uuid4()}/status",
            json={"status": "sent"},
        )

    assert response.status_code == 404
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_send_invoice_success():
    mock_user = make_mock_user()
    app.dependency_overrides[get_current_user] = lambda: mock_user

    mock_row = MagicMock()
    mock_row.status = "draft"
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = mock_row
    mock_db.execute = AsyncMock(return_value=mock_result)
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.api.v1.invoices.send_invoice_task") as mock_task:
        mock_task.delay.return_value = MagicMock(id="task-abc")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(f"/api/v1/invoices/{uuid.uuid4()}/send")

    assert response.status_code == 202
    assert "task_id" in response.json()
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_send_invoice_not_found():
    mock_user = make_mock_user()
    app.dependency_overrides[get_current_user] = lambda: mock_user

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)
    app.dependency_overrides[get_db] = lambda: mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post(f"/api/v1/invoices/{uuid.uuid4()}/send")

    assert response.status_code == 404
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_invoice_send_immediately():
    mock_user = make_mock_user()
    app.dependency_overrides[get_current_user] = lambda: mock_user

    mock_row = make_mock_invoice_row()
    mock_row.id = uuid.uuid4()
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = mock_row
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.api.v1.invoices.send_invoice_task") as mock_task:
        mock_task.delay.return_value = MagicMock(id="task-xyz")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post("/api/v1/invoices", json={
                **SAMPLE_INVOICE_PAYLOAD,
                "send_immediately": True,
            })

    assert response.status_code == 201
    mock_task.delay.assert_called_once()
    app.dependency_overrides.clear()