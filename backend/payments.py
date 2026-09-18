"""Stripe payments (Flow B - shared test key via emergentintegrations)."""
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from emergentintegrations.payments.stripe.checkout import (
    StripeCheckout, CheckoutSessionRequest,
)

from core import db, PLANS, activate_plan, PUBLIC_BASE_URL

payments_router = APIRouter()
STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY", "sk_test_emergent")


class CheckoutRequest(BaseModel):
    package_id: str
    telegram_id: str
    origin_url: str


def _client(request: Request) -> StripeCheckout:
    host_url = str(request.base_url)
    webhook_url = f"{host_url}api/webhook/stripe"
    return StripeCheckout(api_key=STRIPE_API_KEY, webhook_url=webhook_url)


@payments_router.post("/api/payments/checkout")
async def create_checkout(body: CheckoutRequest, request: Request):
    cfg = PLANS.get(body.package_id)
    if not cfg:
        raise HTTPException(400, "Unknown package")
    if not (body.telegram_id or "").strip().isdigit():
        raise HTTPException(400, "telegram_id must be a numeric Telegram ID")
    origin = body.origin_url.rstrip("/")
    success_url = f"{origin}/payment/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin}/payment/cancel"
    checkout = _client(request)
    req = CheckoutSessionRequest(
        amount=float(cfg["amount"]),
        currency="usd",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"telegram_id": str(body.telegram_id), "package_id": body.package_id},
    )
    session = await checkout.create_checkout_session(req)
    await db.payment_transactions.insert_one({
        "session_id": session.session_id,
        "telegram_id": str(body.telegram_id),
        "package_id": body.package_id,
        "amount": float(cfg["amount"]),
        "currency": "usd",
        "status": "initiated",
        "payment_status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"checkout_url": session.url, "session_id": session.session_id}


async def _finalize(session_id: str):
    rec = await db.payment_transactions.find_one({"session_id": session_id})
    if rec and rec.get("payment_status") != "paid":
        await db.payment_transactions.update_one(
            {"session_id": session_id, "payment_status": {"$ne": "paid"}},
            {"$set": {"status": "completed", "payment_status": "paid",
                      "updated_at": datetime.now(timezone.utc).isoformat()}},
        )
        await activate_plan(rec["telegram_id"], rec["package_id"])


@payments_router.get("/api/payments/status/{session_id}")
async def get_status(session_id: str, request: Request):
    rec = await db.payment_transactions.find_one({"session_id": session_id})
    if not rec:
        raise HTTPException(404, "Transaction not found")
    if rec.get("payment_status") != "paid":
        try:
            checkout = _client(request)
            status = await checkout.get_checkout_status(session_id)
            if status.payment_status == "paid" or status.status == "complete":
                await _finalize(session_id)
                rec = await db.payment_transactions.find_one({"session_id": session_id})
        except Exception:
            pass
    return {
        "session_id": rec["session_id"],
        "status": rec["status"],
        "payment_status": rec["payment_status"],
        "package_id": rec.get("package_id"),
    }


@payments_router.post("/api/webhook/stripe")
async def stripe_webhook(request: Request):
    body = await request.body()
    sig = request.headers.get("Stripe-Signature", "")
    checkout = _client(request)
    try:
        resp = await checkout.handle_webhook(body, sig)
    except Exception as ex:
        raise HTTPException(400, f"Webhook error: {ex}")
    if resp.payment_status == "paid" and resp.session_id:
        await _finalize(resp.session_id)
    return {"status": "ok"}


async def bot_checkout(package_id: str, telegram_id) -> str:
    """Create a Stripe checkout session directly from the Telegram bot."""
    cfg = PLANS.get(package_id)
    if not cfg:
        raise ValueError("bad package")
    origin = PUBLIC_BASE_URL or "https://kashef-bot.onrender.com"
    checkout = StripeCheckout(api_key=STRIPE_API_KEY, webhook_url=f"{origin}/api/webhook/stripe")
    req = CheckoutSessionRequest(
        amount=float(cfg["amount"]),
        currency="usd",
        success_url=f"{origin}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{origin}/payment/cancel",
        metadata={"telegram_id": str(telegram_id), "package_id": package_id},
    )
    session = await checkout.create_checkout_session(req)
    await db.payment_transactions.insert_one({
        "session_id": session.session_id,
        "telegram_id": str(telegram_id),
        "package_id": package_id,
        "amount": float(cfg["amount"]),
        "currency": "usd",
        "status": "initiated",
        "payment_status": "pending",
        "source": "bot",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    return session.url
