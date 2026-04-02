from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.dependencies import get_db, get_current_user
from app.models.user import User
from app.schemas.profile import ProfileResponse, ProfileUpdate

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])


@router.get("", response_model=ProfileResponse)
async def get_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(text("""
        SELECT trading_name, base_currency, vat_registered,
               utr_number, stripe_account_id, telegram_chat_id
        FROM public.financial_profiles
        WHERE user_id = :user_id
    """), {"user_id": str(current_user.id)})
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Profile not found")
    return ProfileResponse(
        trading_name=row.trading_name,
        base_currency=row.base_currency,
        vat_registered=row.vat_registered,
        utr_number="••••••••" if row.utr_number else None,  # mask in response
        stripe_account_id=row.stripe_account_id,
        telegram_chat_id=row.telegram_chat_id,
    )


@router.patch("", response_model=ProfileResponse)
async def update_profile(
    payload: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Build dynamic SET clause — only update provided fields
    updates = {}
    if payload.trading_name is not None:
        updates["trading_name"] = payload.trading_name
    if payload.base_currency is not None:
        updates["base_currency"] = payload.base_currency.upper()
    if payload.vat_registered is not None:
        updates["vat_registered"] = payload.vat_registered
    if payload.utr_number is not None:
        # In production: encrypt this with Fernet before storing
        updates["utr_number"] = payload.utr_number
    if payload.telegram_chat_id is not None:
        updates["telegram_chat_id"] = payload.telegram_chat_id

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["user_id"] = str(current_user.id)

    result = await db.execute(text(f"""
        UPDATE public.financial_profiles
        SET {set_clause}
        WHERE user_id = :user_id
        RETURNING trading_name, base_currency, vat_registered,
                  utr_number, stripe_account_id
    """), updates)
    await db.commit()
    row = result.fetchone()
    return ProfileResponse(
        trading_name=row.trading_name,
        base_currency=row.base_currency,
        vat_registered=row.vat_registered,
        utr_number="••••••••" if row.utr_number else None,
        stripe_account_id=row.stripe_account_id,
    )