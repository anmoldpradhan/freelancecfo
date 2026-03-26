import io
import pandas as pd
import pdfplumber
from datetime import date
from decimal import Decimal


def parse_csv(file_bytes: bytes) -> list[dict]:
    """
    Parses a bank statement CSV.
    Handles common UK bank formats (Monzo, Starling, HSBC, Lloyds).
    Returns normalised list of transaction dicts.
    """
    df = pd.read_csv(io.BytesIO(file_bytes))

    # Normalise column names — lowercase, strip spaces
    df.columns = df.columns.str.lower().str.strip()

    # Map common column name variations to our standard names
    column_aliases = {
        "date": ["date", "transaction date", "value date"],
        "description": ["description", "merchant", "narrative", "details", "payee"],
        "amount": ["amount", "value", "debit/credit", "transaction amount"],
    }

    renamed = {}
    for standard, aliases in column_aliases.items():
        for alias in aliases:
            if alias in df.columns:
                renamed[alias] = standard
                break

    df = df.rename(columns=renamed)

    # Validate required columns exist
    required = {"date", "description", "amount"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"CSV missing required columns: {missing}. "
            f"Found columns: {list(df.columns)}"
        )

    transactions = []
    for _, row in df.iterrows():
        try:
            # Parse amount — remove currency symbols and commas
            raw_amount = str(row["amount"]).replace("£", "").replace(",", "").replace(" ", "").strip()
            amount = Decimal(raw_amount)

            # Parse date — try common UK formats
            parsed_date = pd.to_datetime(row["date"], dayfirst=True).date()

            transactions.append({
                "date": parsed_date.isoformat(),
                "description": str(row["description"]).strip(),
                "amount": float(amount),
                "source": "csv",
            })
        except (ValueError, TypeError):
            # Skip malformed rows silently
            continue

    return transactions


def parse_pdf(file_bytes: bytes) -> list[dict]:
    """
    Extracts transactions from a PDF bank statement.
    Uses heuristics to identify transaction rows.
    """
    transactions = []

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            # Try structured table extraction first
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if not row or len(row) < 3:
                        continue
                    parsed = _try_parse_pdf_row(row)
                    if parsed:
                        transactions.append(parsed)

            # Fallback: raw text line parsing if no tables found
            if not tables:
                text = page.extract_text() or ""
                for line in text.split("\n"):
                    parsed = _try_parse_text_line(line)
                    if parsed:
                        transactions.append(parsed)

    return transactions


def _try_parse_pdf_row(row: list) -> dict | None:
    """Attempts to extract a transaction from a table row."""
    try:
        # Look for a date in any cell
        date_val = None
        for cell in row:
            if cell:
                try:
                    date_val = pd.to_datetime(str(cell), dayfirst=True).date()
                    break
                except Exception:
                    continue

        if not date_val:
            return None

        # Look for an amount (number) in any cell
        amount = None
        for cell in reversed(row):  # amounts usually at the end
            if cell:
                cleaned = str(cell).replace("£", "").replace(",", "").strip()
                try:
                    amount = float(cleaned)
                    break
                except ValueError:
                    continue

        if amount is None or amount == 0:
            return None

        # Description is everything that isn't date or amount
        description = " ".join(
            str(c) for c in row
            if c and str(c).strip() not in [str(date_val), str(amount)]
        ).strip()

        return {
            "date": date_val.isoformat(),
            "description": description or "Unknown",
            "amount": amount,
            "source": "pdf",
        }
    except Exception:
        return None


def _try_parse_text_line(line: str) -> dict | None:
    """Last resort: parse a raw text line for date + amount pattern."""
    import re
    # Match pattern like: "01/03/2024  Some Description  -£123.45"
    pattern = r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})\s+(.+?)\s+([-]?£?[\d,]+\.\d{2})"
    match = re.search(pattern, line)
    if not match:
        return None
    try:
        parsed_date = pd.to_datetime(match.group(1), dayfirst=True).date()
        description = match.group(2).strip()
        amount = float(match.group(3).replace("£", "").replace(",", ""))
        return {
            "date": parsed_date.isoformat(),
            "description": description,
            "amount": amount,
            "source": "pdf",
        }
    except Exception:
        return None