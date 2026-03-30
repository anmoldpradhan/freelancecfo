from pydantic import BaseModel
from typing import Optional


class OnboardingResponse(BaseModel):
    url: str
    message: str


class WebhookResponse(BaseModel):
    received: bool
    event_type: str 