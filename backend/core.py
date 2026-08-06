"""Shared config, MongoDB, and Telegram API client."""
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta

import httpx
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "admin")
ADMIN_PASSWORD = os.environ.get("BOT_ADMIN_PASSWORD", "")
ADMIN_TRIGGER = os.environ.get("BOT_ADMIN_TRIGGER", "")

# Subscription business config
PLANS = {
    "pro_monthly":   {"amount": 9.99,  "plan": "pro",   "days": 30,  "label_en": "Pro · Monthly",   "label_ar": "برو · شهري"},
    "pro_yearly":    {"amount": 95.90, "plan": "pro",   "days": 365, "label_en": "Pro · Yearly",    "label_ar": "برو · سنوي"},
    "elite_monthly": {"amount": 24.99, "plan": "elite", "days": 30,  "label_en": "Elite · Monthly", "label_ar": "إيليت · شهري"},
    "elite_yearly":  {"amount": 239.90,"plan": "elite", "days": 365, "label_en": "Elite · Yearly",  "label_ar": "إيليت · سنوي"},
}
LIMITS = {"free": 8, "pro": 150, "elite": 100000}


def now_utc():
    return datetime.now(timezone.utc)


class TelegramClient:
    """Lightweight async Telegram Bot API client (webhook mode)."""

    def __init__(self, token: str):
        self.token = token
        self.base = f"https://api.telegram.org/bot{token}"

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    async def _call(self, method: str, payload: dict):
        if not self.enabled:
            return {"ok": False, "error": "no_token"}
        async with httpx.AsyncClient(timeout=25) as http:
            r = await http.post(f"{self.base}/{method}", json=payload)
            try:
                return r.json()
            except Exception:
                return {"ok": False, "status": r.status_code}

    async def send_message(self, chat_id, text, keyboard=None, disable_preview=True):
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": disable_preview,
        }
        if keyboard is not None:
            payload["reply_markup"] = {"inline_keyboard": keyboard}
        return await self._call("sendMessage", payload)

    async def edit_message(self, chat_id, message_id, text, keyboard=None, disable_preview=True):
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": disable_preview,
        }
        if keyboard is not None:
            payload["reply_markup"] = {"inline_keyboard": keyboard}
        res = await self._call("editMessageText", payload)
        if not res.get("ok"):
            # message may be identical or too old -> send new
            return await self.send_message(chat_id, text, keyboard, disable_preview)
        return res

    async def answer_callback(self, callback_id, text=None):
        payload = {"callback_query_id": callback_id}
        if text:
            payload["text"] = text
        return await self._call("answerCallbackQuery", payload)

    async def send_chat_action(self, chat_id, action="typing"):
        return await self._call("sendChatAction", {"chat_id": chat_id, "action": action})

    async def set_webhook(self, url, secret_token=None):
        payload = {"url": url, "allowed_updates": ["message", "callback_query"]}
        return await self._call("setWebhook", payload)

    async def get_me(self):
        return await self._call("getMe", {})

    async def get_chat(self, chat):
        return await self._call("getChat", {"chat_id": chat})

    async def get_chat_member_count(self, chat):
        return await self._call("getChatMemberCount", {"chat_id": chat})

    async def get_chat_member(self, chat, user_id):
        return await self._call("getChatMember", {"chat_id": chat, "user_id": user_id})

    async def get_file_url(self, file_id):
        res = await self._call("getFile", {"file_id": file_id})
        if res.get("ok"):
            return f"https://api.telegram.org/file/bot{self.token}/{res['result']['file_path']}"
        return None


tg = TelegramClient(TELEGRAM_TOKEN)


async def get_config():
    doc = await db.settings.find_one({"_id": "config"})
    return doc or {}


async def set_config(key, value):
    await db.settings.update_one({"_id": "config"}, {"$set": {key: value}}, upsert=True)


async def get_or_create_user(tg_user: dict, referred_by=None):
    tid = tg_user["id"]
    doc = await db.users.find_one({"telegram_id": tid})
    if doc:
        return doc
    doc = {
        "telegram_id": tid,
        "username": tg_user.get("username"),
        "first_name": tg_user.get("first_name"),
        "lang": "ar",
        "plan": "free",
        "plan_expires": None,
        "scans_today": 0,
        "scans_date": now_utc().strftime("%Y-%m-%d"),
        "points": 0,
        "solved": [],
        "state": None,
        "referred_by": referred_by,
        "ref_count": 0,
        "created_at": now_utc().isoformat(),
    }
    await db.users.insert_one(doc)
    if referred_by and referred_by != tid:
        await db.users.update_one({"telegram_id": referred_by}, {"$inc": {"ref_count": 1, "points": 25}})
    return doc


async def set_state(tid, state):
    await db.users.update_one({"telegram_id": tid}, {"$set": {"state": state}})


async def set_lang(tid, lang):
    await db.users.update_one({"telegram_id": tid}, {"$set": {"lang": lang}})


def effective_plan(user) -> str:
    plan = user.get("plan", "free")
    exp = user.get("plan_expires")
    if plan != "free" and exp:
        try:
            if datetime.fromisoformat(exp) < now_utc():
                return "free"
        except Exception:
            return plan
    return plan


async def check_and_increment(user) -> bool:
    """Returns True if the scan is allowed and increments the daily counter."""
    tid = user["telegram_id"]
    today = now_utc().strftime("%Y-%m-%d")
    fresh = await db.users.find_one({"telegram_id": tid})
    if fresh.get("scans_date") != today:
        await db.users.update_one({"telegram_id": tid}, {"$set": {"scans_date": today, "scans_today": 0}})
        fresh["scans_today"] = 0
    limit = LIMITS[effective_plan(fresh)]
    if fresh.get("scans_today", 0) >= limit:
        return False
    await db.users.update_one({"telegram_id": tid}, {"$inc": {"scans_today": 1}})
    return True


async def activate_plan(telegram_id, package_id):
    cfg = PLANS.get(package_id)
    if not cfg:
        return
    expires = (now_utc() + timedelta(days=cfg["days"])).isoformat()
    await db.users.update_one(
        {"telegram_id": int(telegram_id)},
        {"$set": {"plan": cfg["plan"], "plan_expires": expires}},
    )
    if tg.enabled:
        try:
            user = await db.users.find_one({"telegram_id": int(telegram_id)})
            lang = (user or {}).get("lang", "ar")
            if lang == "ar":
                msg = f"✅ <b>تم تفعيل اشتراكك بنجاح!</b>\n\nالباقة: <b>{cfg['label_ar']}</b>\nصالحة لمدة {cfg['days']} يوم.\n\nاستمتع بكل الميزات 🚀"
            else:
                msg = f"✅ <b>Subscription activated!</b>\n\nPlan: <b>{cfg['label_en']}</b>\nValid for {cfg['days']} days.\n\nEnjoy all features 🚀"
            await tg.send_message(int(telegram_id), msg)
        except Exception:
            pass
