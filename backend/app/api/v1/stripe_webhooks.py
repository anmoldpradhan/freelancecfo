"""
Stripe Connect onboarding + webhook handler.

Security note on webhooks:
  Never trust the webhook payload alone — always verify the Stripe-Signature
  header using your webhook secret. This prevents anyone from spoofing
  payment events by POSTing fake JSON to your endpoint.
"""
import json
import logging
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional

from app.core.config import settings
from app.core.dependencies import get_db, get_current_user
from app.core.redis import redis_client
from app.models.user import User
from app.schemas.stripe import OnboardingResponse, WebhookResponse

stripe.api_key = settings.stripe_secret_key

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/stripe", tags=["stripe"])


@router.get("/onboard", response_model=OnboardingResponse)
async def get_onboarding_link(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Creates a Stripe Connect Express account for the user (if not exists)
    and returns the onboarding URL to redirect them to.
    """
    if not settings.stripe_secret_key:
        raise HTTPException(
            status_code=503,
            detail="Stripe not configured"
        )

    # Fetch existing stripe_account_id from financial profile
    result = await db.execute(text("""
        SELECT stripe_account_id FROM public.financial_profiles
        WHERE user_id = :user_id
    """), {"user_id": str(current_user.id)})
    profile = result.fetchone()

    stripe_account_id = profile.stripe_account_id if profile else None

    # Create Express account if not already linked
    if not stripe_account_id:
        try:
            account = stripe.Account.create(
                type="express",
                country="GB",
                email=current_user.email,
                capabilities={
                    "card_payments": {"requested": True},
                    "transfers": {"requested": True},
                },
            )
        except stripe.InvalidRequestError as e:
            logger.error("Stripe Connect account creation failed: %s", e)
            raise HTTPException(
                status_code=503,
                detail="Stripe Connect is not enabled on this account. "
                       "Enable it at https://dashboard.stripe.com/connect",
            )
        stripe_account_id = account.id

        # Save to financial profile
        await db.execute(text("""
            UPDATE public.financial_profiles
            SET stripe_account_id = :stripe_id
            WHERE user_id = :user_id
        """), {
            "stripe_id": stripe_account_id,
            "user_id": str(current_user.id),
        })
        await db.commit()
        logger.info("Stripe account created | user=%s account=%s",
                    current_user.id, stripe_account_id)

    # Generate onboarding link (expires after ~1 hour)
    link = stripe.AccountLink.create(
        account=stripe_account_id,
        refresh_url=f"{settings.frontend_url}/stripe/refresh",
        return_url=f"{settings.frontend_url}/stripe/complete",
        type="account_onboarding",
    )

    return OnboardingResponse(
        url=link.url,
        message="Redirect user to this URL to complete Stripe onboarding",
    )


@router.post("/webhook", response_model=WebhookResponse)
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="stripe-signature"),
    db: AsyncSession = Depends(get_db),
):
    """
    Receives Stripe webhook events.
    MUST verify signature before processing — rejects anything unsigned.
    """
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook secret not configured")

    payload = await request.body()

    # Verify signature — raises if invalid
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.stripe_webhook_secret
        )
    except stripe.error.SignatureVerificationError:
        logger.warning("Invalid Stripe webhook signature rejected")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.error("Webhook construction error: %s", e)
        raise HTTPException(status_code=400, detail="Webhook error")

    logger.info("Stripe event received | type=%s id=%s", event["type"], event["id"])

    # Route to appropriate handler
    if event["type"] == "payment_intent.succeeded":
        await _handle_payment_succeeded(event["data"]["object"], db)

    elif event["type"] == "payment_intent.payment_failed":
        await _handle_payment_failed(event["data"]["object"])

    elif event["type"] == "account.updated":
        await _handle_account_updated(event["data"]["object"], db)

    return WebhookResponse(received=True, event_type=event["type"])


async def _handle_payment_succeeded(payment_intent: dict, db: AsyncSession):
    """
    On successful payment:
    1. Find the user by their Stripe account ID
    2. Record transaction in their tenant schema
    3. Publish real-time notification via Redis pub/sub
    """
    stripe_account_id = payment_intent.get("on_behalf_of") or \
                        payment_intent.get("transfer_data", {}).get("destination")
    amount_received = payment_intent.get("amount_received", 0) / 100  # pence → pounds
    currency = payment_intent.get("currency", "gbp").upper()
    payment_id = payment_intent.get("id")
    description = payment_intent.get("description") or "Stripe payment received"

    if not stripe_account_id:
        logger.warning("payment_intent.succeeded missing account ID | pi=%s", payment_id)
        return

    # Find user by stripe_account_id
    result = await db.execute(text("""
        SELECT u.id, u.tenant_schema
        FROM public.users u
        JOIN public.financial_profiles fp ON fp.user_id = u.id
        WHERE fp.stripe_account_id = :account_id
    """), {"account_id": stripe_account_id})
    user_row = result.fetchone()

    if not user_row:
        logger.warning("No user found for Stripe account %s", stripe_account_id)
        return

    user_id = str(user_row.id)
    tenant_schema = user_row.tenant_schema

    # Find "Client Income" category for this tenant
    cat_result = await db.execute(text(f"""
        SELECT id FROM "{tenant_schema}".categories
        WHERE name = 'Client Income' AND is_system = TRUE
        LIMIT 1
    """))
    cat_row = cat_result.fetchone()
    category_id = str(cat_row.id) if cat_row else None

    # Insert transaction
    await db.execute(text(f"""
        INSERT INTO "{tenant_schema}".transactions
            (date, description, amount, currency,
             category_id, confidence, source, stripe_payment_id, is_confirmed)
        VALUES
            (CURRENT_DATE, :description, :amount, :currency,
             :category_id, 1.000, 'stripe', :stripe_id, TRUE)
        ON CONFLICT DO NOTHING
    """), {
        "description": description,
        "amount": amount_received,
        "currency": currency,
        "category_id": category_id,
        "stripe_id": payment_id,
    })
    await db.commit()

    logger.info("Stripe payment recorded | user=%s amount=%s%s",
                user_id, currency, amount_received)

    # Publish real-time notification to Redis
    notification = {
        "user_id": user_id,
        "type": "payment_received",
        "amount": amount_received,
        "currency": currency,
        "description": description,
        "payment_id": payment_id,
    }
    await redis_client.publish("payments", json.dumps(notification))


async def _handle_payment_failed(payment_intent: dict):
    """Log failed payments — no transaction recorded."""
    logger.warning(
        "Payment failed | pi=%s amount=%s",
        payment_intent.get("id"),
        payment_intent.get("amount"),
    )


async def _handle_account_updated(account: dict, db: AsyncSession):
    """Track when a connected account completes onboarding."""
    charges_enabled = account.get("charges_enabled", False)
    account_id = account.get("id")

    if charges_enabled:
        logger.info("Stripe account fully onboarded | account=%s", account_id)