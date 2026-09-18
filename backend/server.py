from fastapi import FastAPI, APIRouter, Request, HTTPException, Query
from starlette.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import logging
import asyncio

from core import db, tg, PLANS, ADMIN_KEY, TELEGRAM_WEBHOOK_SECRET, PUBLIC_BASE_URL, effective_plan, now_utc
import telegram_bot
from payments import payments_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Cyber OSINT Suite API")
api = APIRouter(prefix="/api")


@api.get("/")
async def root():
    return {"message": "Cyber OSINT Suite API", "status": "online"}


# ---------------- Telegram webhook ----------------
@api.post("/telegram/webhook/{secret}")
async def telegram_webhook(secret: str, request: Request):
    if secret != TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(403, "invalid secret")
    update = await request.json()
    try:
        await telegram_bot.handle_update(update)
    except Exception as ex:
        logger.exception("update handling failed: %s", ex)
    return {"ok": True}


# ---------------- Public data ----------------
@api.get("/plans")
async def plans():
    return {"plans": [{"id": k, **v} for k, v in PLANS.items()]}


@api.get("/stats/public")
async def public_stats():
    users = await db.users.count_documents({})
    scans = await db.scans.count_documents({})
    solved = await db.ctf_submissions.count_documents({"correct": True})
    tools = len(telegram_bot.TOOLS) + 1
    return {"users": users, "scans": scans, "solved": solved, "tools": tools,
            "academy_tracks": 5, "challenges": 8, "courses": 4}


# ---------------- Consent-based location share ----------------
class LocSubmit(BaseModel):
    lat: float
    lon: float
    accuracy: float | None = None


@api.get("/loc/{token}")
async def loc_info(token: str):
    req = await db.loc_requests.find_one({"token": token}, {"_id": 0})
    if not req:
        raise HTTPException(404, "not found")
    requester = await db.users.find_one({"telegram_id": req["requester_tid"]}, {"_id": 0})
    name = (requester or {}).get("first_name") or "A user"
    return {"status": req["status"], "requester_name": name}


@api.post("/loc/{token}/submit")
async def loc_submit(token: str, body: LocSubmit):
    req = await db.loc_requests.find_one({"token": token})
    if not req:
        raise HTTPException(404, "not found")
    await db.loc_requests.update_one(
        {"token": token},
        {"$set": {"status": "shared", "lat": body.lat, "lon": body.lon,
                  "accuracy": body.accuracy, "shared_at": now_utc().isoformat()}},
    )
    try:
        await telegram_bot.notify_location(req["requester_tid"], token, body.lat, body.lon, body.accuracy)
    except Exception as ex:
        logger.warning("notify_location failed: %s", ex)
    return {"ok": True}


@api.post("/loc/{token}/decline")
async def loc_decline(token: str):
    await db.loc_requests.update_one({"token": token}, {"$set": {"status": "declined"}})
    return {"ok": True}


# ---------------- Admin ----------------
class AdminAuth(BaseModel):
    key: str


class Broadcast(BaseModel):
    key: str
    message: str


def _check_admin(key: str):
    if key != ADMIN_KEY:
        raise HTTPException(403, "unauthorized")


@api.post("/admin/login")
async def admin_login(body: AdminAuth):
    _check_admin(body.key)
    return {"ok": True}


@api.get("/admin/overview")
async def admin_overview(key: str = Query(...)):
    _check_admin(key)
    users = await db.users.count_documents({})
    paid = await db.payment_transactions.count_documents({"payment_status": "paid"})
    txs = await db.payment_transactions.find({"payment_status": "paid"}, {"_id": 0, "amount": 1}).to_list(1000)
    revenue = round(sum(t.get("amount", 0) for t in txs), 2)
    all_users = await db.users.find({}, {"_id": 0}).to_list(5000)
    plan_breakdown = {"free": 0, "pro": 0, "elite": 0}
    for u in all_users:
        plan_breakdown[effective_plan(u)] = plan_breakdown.get(effective_plan(u), 0) + 1
    scans = await db.scans.count_documents({})
    solved = await db.ctf_submissions.count_documents({"correct": True})
    return {"users": users, "paid_subscriptions": paid, "revenue": revenue,
            "plan_breakdown": plan_breakdown, "scans": scans, "solved": solved}


@api.get("/admin/users")
async def admin_users(key: str = Query(...)):
    _check_admin(key)
    users = await db.users.find({}, {"_id": 0}).sort("created_at", -1).limit(200).to_list(200)
    for u in users:
        u["plan"] = effective_plan(u)
    return {"users": users}


@api.get("/admin/transactions")
async def admin_transactions(key: str = Query(...)):
    _check_admin(key)
    txs = await db.payment_transactions.find({}, {"_id": 0}).sort("created_at", -1).limit(100).to_list(100)
    return {"transactions": txs}


@api.post("/admin/broadcast")
async def admin_broadcast(body: Broadcast):
    _check_admin(body.key)
    users = await db.users.find({}, {"_id": 0, "telegram_id": 1}).to_list(10000)
    sent = 0
    for u in users:
        try:
            res = await tg.send_message(u["telegram_id"], f"📢 {body.message}")
            if res.get("ok"):
                sent += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)
    await db.broadcasts.insert_one({"message": body.message, "sent": sent})
    return {"sent": sent, "total": len(users)}


app.include_router(api)
app.include_router(payments_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _keep_alive_loop():
    import httpx
    while True:
        await asyncio.sleep(480)  # Ping every 8 minutes to keep Render free tier awake 24/7
        if PUBLIC_BASE_URL:
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    await client.get(f"{PUBLIC_BASE_URL}/api/")
            except Exception as ex:
                logger.debug("keep-alive self ping error: %s", ex)


@app.on_event("startup")
async def on_startup():
    if not tg.enabled:
        logger.warning("Telegram token not set; bot disabled.")
        return
    try:
        me = await tg.get_me()
        if me.get("ok"):
            telegram_bot.BOT_USERNAME = me["result"]["username"]
            logger.info("Bot: @%s", telegram_bot.BOT_USERNAME)
        if PUBLIC_BASE_URL:
            hook = f"{PUBLIC_BASE_URL}/api/telegram/webhook/{TELEGRAM_WEBHOOK_SECRET}"
            res = await tg.set_webhook(hook)
            logger.info("setWebhook -> %s (%s)", hook, res)
        # Start keep-alive loop to prevent cold sleep
        asyncio.create_task(_keep_alive_loop())
    except Exception as ex:
        logger.warning("startup telegram init failed: %s", ex)


@app.on_event("shutdown")
async def on_shutdown():
    from core import client
    client.close()
