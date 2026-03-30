from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from datetime import date
from decimal import Decimal
import uuid


class LineItem(BaseModel):
    description: str
    quantity: Decimal
    unit_price: Decimal

    @property
    def total(self) -> Decimal:
        return self.quantity * self.unit_price


class InvoiceCreate(BaseModel):
    client_name: str
    client_email: Optional[EmailStr] = None
    line_items: list[LineItem]
    tax_rate: Decimal = Decimal("0.00")   # VAT rate e.g. 20.00 for 20%
    currency: str = "GBP"
    issued_date: Optional[date] = None
    due_date: Optional[date] = None
    send_immediately: bool = False        # if True, email on creation

    @field_validator("line_items")
    @classmethod
    def at_least_one_item(cls, v: list) -> list:
        if not v:
            raise ValueError("Invoice must have at least one line item")
        return v

    @field_validator("tax_rate")
    @classmethod
    def valid_tax_rate(cls, v: Decimal) -> Decimal:
        if v < 0 or v > 100:
            raise ValueError("Tax rate must be between 0 and 100")
        return v


class InvoiceStatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: str) -> str:
        allowed = {"draft", "sent", "paid", "overdue", "void"}
        if v not in allowed:
            raise ValueError(f"Status must be one of {allowed}")
        return v


class InvoiceResponse(BaseModel):
    id: uuid.UUID
    invoice_number: str
    client_name: str
    client_email: Optional[str]
    line_items: list[dict]
    subtotal: Decimal
    tax_rate: Decimal
    total: Decimal
    currency: str
    status: str
    issued_date: Optional[date]
    due_date: Optional[date]
    paid_date: Optional[date]
    pdf_s3_key: Optional[str]
    # Sender fields — populated from user profile when rendering PDF
    from_name: Optional[str] = None
    from_address: Optional[str] = None
    vat_number: Optional[str] = None
    trading_name: Optional[str] = None

    model_config = {"from_attributes": True}