from pydantic import BaseModel
from typing import Optional


class ProfileResponse(BaseModel):
    trading_name: Optional[str]
    base_currency: str
    vat_registered: bool
    utr_number: Optional[str]
    stripe_account_id: Optional[str]
    telegram_chat_id: Optional[str] = None

    model_config = {"from_attributes": True}


class ProfileUpdate(BaseModel):
    trading_name: Optional[str] = None
    base_currency: Optional[str] = None
    vat_registered: Optional[bool] = None
    utr_number: Optional[str] = None
    telegram_chat_id: Optional[str] = None