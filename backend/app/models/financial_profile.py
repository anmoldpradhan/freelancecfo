import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, ForeignKey, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base


class FinancialProfile(Base):
    __tablename__ = "financial_profiles"
    __table_args__ = {}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True
    )
    trading_name: Mapped[str | None] = mapped_column(String(255))
    base_currency: Mapped[str] = mapped_column(String(3), default="GBP")
    vat_registered: Mapped[bool] = mapped_column(Boolean, default=False)
    utr_number: Mapped[str | None] = mapped_column(String(255))  # encrypted in Week 7
    stripe_account_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="financial_profile")