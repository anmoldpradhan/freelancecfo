from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import date
from decimal import Decimal
import uuid


class TransactionCreate(BaseModel):
    date: date
    description: str
    amount: Decimal  # positive = income, negative = expense
    currency: str = "GBP"
    category_id: Optional[uuid.UUID] = None
    notes: Optional[str] = None
    source: str = "manual"

    @field_validator("amount")
    @classmethod
    def amount_not_zero(cls, v: Decimal) -> Decimal:
        if v == 0:
            raise ValueError("Amount cannot be zero")
        return v

    @field_validator("currency")
    @classmethod
    def currency_uppercase(cls, v: str) -> str:
        return v.upper()


class TransactionResponse(BaseModel):
    id: uuid.UUID
    date: date
    description: str
    amount: Decimal
    currency: str
    category_id: Optional[uuid.UUID]
    confidence: Optional[Decimal]
    source: str
    is_confirmed: bool
    notes: Optional[str]

    model_config = {"from_attributes": True}


class TransactionConfirm(BaseModel):
    category_id: uuid.UUID


class ImportResponse(BaseModel):
    task_id: str
    message: str
    status: str = "processing"