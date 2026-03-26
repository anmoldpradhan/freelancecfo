"""Unit tests for pure service-layer logic — no DB, no HTTP."""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException


# ─── categoriser ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_categorise_empty_list():
    from app.services.categoriser import categorise_transactions
    result = await categorise_transactions([], [])
    assert result == []


@pytest.mark.asyncio
async def test_categorise_success():
    from app.services.categoriser import categorise_transactions
    with patch("app.services.categoriser.model") as mock_model:
        mock_response = MagicMock()
        mock_response.text = '[{"index": 1, "category_name": "Client Income", "confidence": 0.95}]'
        mock_model.generate_content = MagicMock(return_value=mock_response)

        transactions = [{"id": "1", "description": "Wire transfer received", "amount": 1000}]
        categories = [{"id": "cat1", "name": "Client Income", "type": "income"}]

        result = await categorise_transactions(transactions, categories)

    assert result[0]["category_name"] == "Client Income"
    assert result[0]["confidence"] == 0.95
    assert result[0]["category_id"] == "cat1"


@pytest.mark.asyncio
async def test_categorise_markdown_fences():
    """Gemini sometimes wraps JSON in ```json fences — strip them."""
    from app.services.categoriser import categorise_transactions
    with patch("app.services.categoriser.model") as mock_model:
        wrapped = '```json\n[{"index": 1, "category_name": "Client Income", "confidence": 0.90}]\n```'
        mock_response = MagicMock()
        mock_response.text = wrapped
        mock_model.generate_content = MagicMock(return_value=mock_response)

        transactions = [{"id": "1", "description": "Payment", "amount": 500}]
        categories = [{"id": "cat1", "name": "Client Income", "type": "income"}]

        result = await categorise_transactions(transactions, categories)

    assert result[0]["category_name"] == "Client Income"


@pytest.mark.asyncio
async def test_categorise_out_of_bounds_index():
    """Gemini returning an index beyond the list length should not crash."""
    from app.services.categoriser import categorise_transactions
    with patch("app.services.categoriser.model") as mock_model:
        mock_response = MagicMock()
        mock_response.text = '[{"index": 99, "category_name": "Client Income", "confidence": 0.9}]'
        mock_model.generate_content = MagicMock(return_value=mock_response)

        transactions = [{"id": "1", "description": "Payment", "amount": 100}]
        categories = [{"id": "cat1", "name": "Client Income", "type": "income"}]

        result = await categorise_transactions(transactions, categories)

    # Original transaction gets fallback — out-of-bounds index is silently ignored
    assert result[0].get("category_name") == "Client Income"  # fallback category


# ─── statement_parser — parse_csv edge cases ────────────────────────────────

def test_parse_csv_exception_row_skipped():
    """A row with an unparseable date is silently skipped."""
    from app.services.statement_parser import parse_csv
    csv_bytes = (
        b"date,description,amount\n"
        b"not_a_date,Bad row,100.00\n"
        b"2024-03-01,Valid payment,50.00"
    )
    result = parse_csv(csv_bytes)
    assert len(result) == 1
    assert result[0]["description"] == "Valid payment"


# ─── statement_parser — _try_parse_text_line ─────────────────────────────────

def test_try_parse_text_line_match():
    from app.services.statement_parser import _try_parse_text_line
    line = "01/03/2024  Amazon AWS  -£49.99"
    result = _try_parse_text_line(line)
    assert result is not None
    assert result["description"] == "Amazon AWS"
    assert result["amount"] == -49.99
    assert result["source"] == "pdf"
    assert result["date"] == "2024-03-01"


def test_try_parse_text_line_no_match():
    from app.services.statement_parser import _try_parse_text_line
    result = _try_parse_text_line("not a transaction line at all")
    assert result is None


def test_try_parse_text_line_plain_amount():
    from app.services.statement_parser import _try_parse_text_line
    line = "15-06-2024  Office supplies  123.45"
    result = _try_parse_text_line(line)
    assert result is not None
    assert result["amount"] == 123.45


# ─── statement_parser — _try_parse_pdf_row ───────────────────────────────────

def test_try_parse_pdf_row_valid():
    from app.services.statement_parser import _try_parse_pdf_row
    row = ["01/03/2024", "Amazon AWS", "49.99"]
    result = _try_parse_pdf_row(row)
    assert result is not None
    assert result["amount"] == 49.99
    assert result["source"] == "pdf"
    assert "Amazon AWS" in result["description"]


def test_try_parse_pdf_row_no_date():
    from app.services.statement_parser import _try_parse_pdf_row
    row = ["not a date", "description text", "49.99"]
    result = _try_parse_pdf_row(row)
    assert result is None


def test_try_parse_pdf_row_no_amount():
    from app.services.statement_parser import _try_parse_pdf_row
    row = ["01/03/2024", "description", "no amount here"]
    result = _try_parse_pdf_row(row)
    assert result is None


def test_try_parse_pdf_row_zero_amount():
    from app.services.statement_parser import _try_parse_pdf_row
    row = ["01/03/2024", "description", "0"]
    result = _try_parse_pdf_row(row)
    assert result is None


def test_try_parse_pdf_row_short_row():
    from app.services.statement_parser import _try_parse_pdf_row
    result = _try_parse_pdf_row([None, None])
    assert result is None


# ─── statement_parser — parse_pdf ────────────────────────────────────────────

def test_parse_pdf_with_tables():
    from app.services.statement_parser import parse_pdf
    with patch("app.services.statement_parser.pdfplumber") as mock_pdfplumber:
        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [
            [["01/03/2024", "Amazon AWS", "49.99"]]
        ]
        mock_pdfplumber.open.return_value.__enter__.return_value.pages = [mock_page]

        result = parse_pdf(b"fake pdf content")

    assert len(result) >= 1
    assert result[0]["source"] == "pdf"


def test_parse_pdf_no_tables_text_fallback():
    from app.services.statement_parser import parse_pdf
    with patch("app.services.statement_parser.pdfplumber") as mock_pdfplumber:
        mock_page = MagicMock()
        mock_page.extract_tables.return_value = []
        mock_page.extract_text.return_value = "01/03/2024  Amazon AWS  -£49.99"
        mock_pdfplumber.open.return_value.__enter__.return_value.pages = [mock_page]

        result = parse_pdf(b"fake pdf content")

    assert len(result) >= 1


def test_parse_pdf_empty_pages():
    from app.services.statement_parser import parse_pdf
    with patch("app.services.statement_parser.pdfplumber") as mock_pdfplumber:
        mock_pdfplumber.open.return_value.__enter__.return_value.pages = []
        result = parse_pdf(b"fake pdf content")
    assert result == []


# ─── dependencies — get_current_user ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_current_user_invalid_token():
    from app.core.dependencies import get_current_user
    mock_creds = MagicMock()
    mock_creds.credentials = "not.a.valid.token"
    mock_db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=mock_creds, db=mock_db)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_wrong_token_type():
    """Passing a refresh token (type != access) should be rejected."""
    from app.core.dependencies import get_current_user
    from app.core.security import create_refresh_token
    mock_creds = MagicMock()
    mock_creds.credentials = create_refresh_token(str(uuid.uuid4()))
    mock_db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=mock_creds, db=mock_db)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_user_not_found():
    from app.core.dependencies import get_current_user
    from app.core.security import create_access_token
    mock_creds = MagicMock()
    mock_creds.credentials = create_access_token(str(uuid.uuid4()))

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=mock_creds, db=mock_db)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_success():
    from app.core.dependencies import get_current_user
    from app.core.security import create_access_token
    user_id = str(uuid.uuid4())
    mock_creds = MagicMock()
    mock_creds.credentials = create_access_token(user_id)

    mock_user = MagicMock()
    mock_user.is_active = True
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_user
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await get_current_user(credentials=mock_creds, db=mock_db)
    assert result == mock_user
