import uuid
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class CFOMessage(BaseModel):
    role: str        # "user" or "assistant"
    content: str
    timestamp: Optional[str] = None


class CFOChatRequest(BaseModel):
    message: str
    conversation_id: Optional[uuid.UUID] = None   # None = start new conversation


class CFOChatResponse(BaseModel):
    response: str
    conversation_id: str
    tokens_used: Optional[int] = None


class CFOHistoryResponse(BaseModel):
    conversation_id: str
    messages: list[CFOMessage]
    created_at: str
    updated_at: str