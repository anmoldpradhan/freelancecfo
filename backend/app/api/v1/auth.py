import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import JWTError
from app.core.limiter import limiter
from app.core.dependencies import get_db
from app.core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token
)
from app.core.redis import redis_client
from app.core.config import settings
from app.db.tenant import generate_tenant_schema, provision_tenant_schema
from app.models.user import User
from app.models.financial_profile import FinancialProfile
from app.schemas.auth import (
    RegisterRequest, LoginRequest, TokenResponse, RefreshRequest,
    DeleteAccountRequest,
)
from app.core.dependencies import get_current_user
from sqlalchemy import text

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
@limiter.limit("5/minute")
async def register(request: Request, payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # 1. Check email not already taken
    existing = await db.execute(
        select(User).where(User.email == payload.email)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    # 2. Create user
    tenant_schema = generate_tenant_schema()
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        tenant_schema=tenant_schema,
    )
    db.add(user)
    await db.flush()  # assigns user.id without committing yet

    # 3. Create financial profile (auto-created for every user)
    profile = FinancialProfile(user_id=user.id)
    db.add(profile)
    await db.flush()

    # 4. Provision private tenant schema + all tables
    await provision_tenant_schema(tenant_schema, db)
    # Note: provision_tenant_schema calls db.commit() internally

    # 5. Issue tokens
    access_token = create_access_token(str(user.id))
    refresh_token = create_refresh_token(str(user.id))

    # 6. Store refresh token in Redis with TTL
    await redis_client.setex(
        f"refresh:{refresh_token}",
        settings.refresh_token_expire_days * 86400,  # TTL in seconds
        str(user.id),
    )

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(request: Request, payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    # 1. Find user
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    # 2. Verify — same error for "not found" and "wrong password" (security)
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account deactivated")

    # 3. Issue tokens
    access_token = create_access_token(str(user.id))
    refresh_token = create_refresh_token(str(user.id))

    await redis_client.setex(
        f"refresh:{refresh_token}",
        settings.refresh_token_expire_days * 86400,
        str(user.id),
    )

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest):
    # 1. Verify JWT signature and expiry
    try:
        token_data = decode_token(payload.refresh_token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    if token_data.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Not a refresh token")

    # 2. Check it exists in Redis (not logged out)
    stored_user_id = await redis_client.get(f"refresh:{payload.refresh_token}")
    if not stored_user_id:
        raise HTTPException(status_code=401, detail="Token revoked or expired")

    # 3. Rotate — delete old, issue new pair
    await redis_client.delete(f"refresh:{payload.refresh_token}")

    user_id = token_data["sub"]
    new_access = create_access_token(user_id)
    new_refresh = create_refresh_token(user_id)

    await redis_client.setex(
        f"refresh:{new_refresh}",
        settings.refresh_token_expire_days * 86400,
        user_id,
    )

    return TokenResponse(access_token=new_access, refresh_token=new_refresh)


@router.post("/logout", status_code=204)
async def logout(payload: RefreshRequest):
    """
    Deletes the refresh token from Redis.
    The access token expires naturally — 30 min max exposure.
    """
    await redis_client.delete(f"refresh:{payload.refresh_token}")
    return None


@router.delete("/account", status_code=204)
async def delete_account(
    payload: DeleteAccountRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Permanently deletes the user's account and all their data (GDPR right to erasure).
    Requires password confirmation to prevent accidental or malicious deletion.
    """
    # 1. Verify password
    if not verify_password(payload.password, current_user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect password")

    schema = current_user.tenant_schema
    user_id = str(current_user.id)

    # 2. Drop the entire tenant schema and all its tables (CASCADE)
    await db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))

    # 3. Delete financial profile (foreign key to users)
    await db.execute(
        text("DELETE FROM public.financial_profiles WHERE user_id = :uid"),
        {"uid": user_id},
    )

    # 4. Delete the user row
    await db.execute(
        text("DELETE FROM public.users WHERE id = :uid"),
        {"uid": user_id},
    )

    await db.commit()

    # 5. Revoke refresh token if provided
    if payload.refresh_token:
        await redis_client.delete(f"refresh:{payload.refresh_token}")

    return None