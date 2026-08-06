"""Backend tests for Cyber OSINT Suite. Tests public APIs, telegram webhook,
bot flows (via simulated updates), OSINT tool functions, payments, and admin APIs."""
import asyncio
import os
import sys
import time
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

# --- config / base url ---
frontend_env = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
if not BASE_URL:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")

ADMIN_KEY = "admin-osint-2026"
WEBHOOK_SECRET = "cybX9f2Kq7wZn4Lp8Rt3Vd6Hs1Mb0Ej"
WEBHOOK_URL = f"{BASE_URL}/api/telegram/webhook/{WEBHOOK_SECRET}"

# Allow importing backend modules for direct OSINT tests & DB inspection
sys.path.insert(0, "/app/backend")


@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def mongo_db():
    from core import db  # motor async db
    return db


def _post_update(update: dict, secret=WEBHOOK_SECRET):
    return requests.post(f"{BASE_URL}/api/telegram/webhook/{secret}", json=update, timeout=30)


# =========================================================
# PUBLIC APIs
# =========================================================
class TestPublicAPIs:
    def test_root(self, api):
        r = api.get(f"{BASE_URL}/api/")
        assert r.status_code == 200
        assert r.json().get("status") == "online"

    def test_stats_public(self, api):
        r = api.get(f"{BASE_URL}/api/stats/public")
        assert r.status_code == 200
        d = r.json()
        for k in ("users", "scans", "solved", "tools"):
            assert k in d, f"missing {k}"
            assert isinstance(d[k], int)
        assert d["tools"] >= 10

    def test_plans(self, api):
        r = api.get(f"{BASE_URL}/api/plans")
        assert r.status_code == 200
        plans = r.json()["plans"]
        ids = {p["id"] for p in plans}
        assert {"pro_monthly", "pro_yearly", "elite_monthly", "elite_yearly"} <= ids
        for p in plans:
            assert "amount" in p and "plan" in p and "days" in p


# =========================================================
# TELEGRAM WEBHOOK basics
# =========================================================
class TestWebhookBasics:
    def test_wrong_secret_403(self):
        r = requests.post(f"{BASE_URL}/api/telegram/webhook/wrong_secret", json={"update_id": 1}, timeout=15)
        assert r.status_code == 403

    def test_start_creates_user(self, mongo_db):
        tid = 990001
        # cleanup
        asyncio.get_event_loop().run_until_complete(mongo_db.users.delete_many({"telegram_id": tid}))
        update = {
            "update_id": int(time.time()),
            "message": {
                "message_id": 1,
                "from": {"id": tid, "first_name": "TestA", "username": "test_a"},
                "chat": {"id": tid, "type": "private"},
                "text": "/start",
            },
        }
        r = _post_update(update)
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        # verify user persisted
        u = asyncio.get_event_loop().run_until_complete(mongo_db.users.find_one({"telegram_id": tid}))
        assert u is not None
        assert u.get("lang") == "ar"
        assert u.get("plan") == "free"
        # cleanup
        asyncio.get_event_loop().run_until_complete(mongo_db.users.delete_many({"telegram_id": tid}))

    def test_webhook_never_500_on_bad_update(self):
        # malformed update: no message/callback
        r = _post_update({"update_id": 999999})
        assert r.status_code == 200
        assert r.json() == {"ok": True}


# =========================================================
# BOT LOGIC via simulated updates: tool state + IP scan
# =========================================================
class TestBotToolFlow:
    tid = 990002

    def _cleanup(self, db):
        asyncio.get_event_loop().run_until_complete(db.users.delete_many({"telegram_id": self.tid}))
        asyncio.get_event_loop().run_until_complete(db.scans.delete_many({"telegram_id": self.tid}))

    def test_callback_sets_state_then_ip_scan(self, mongo_db):
        self._cleanup(mongo_db)
        # /start to create user
        _post_update({
            "update_id": int(time.time()) + 1,
            "message": {"message_id": 1, "from": {"id": self.tid, "first_name": "B"},
                        "chat": {"id": self.tid, "type": "private"}, "text": "/start"},
        })
        # callback tool:ip
        _post_update({
            "update_id": int(time.time()) + 2,
            "callback_query": {
                "id": "cbq1",
                "from": {"id": self.tid, "first_name": "B"},
                "message": {"message_id": 10, "chat": {"id": self.tid, "type": "private"}},
                "data": "tool:ip",
            },
        })
        u = asyncio.get_event_loop().run_until_complete(mongo_db.users.find_one({"telegram_id": self.tid}))
        assert u.get("state") == "await:ip", f"expected await:ip, got {u.get('state')}"

        # text 8.8.8.8 → runs ip tool, inserts scan, clears state
        _post_update({
            "update_id": int(time.time()) + 3,
            "message": {"message_id": 2, "from": {"id": self.tid, "first_name": "B"},
                        "chat": {"id": self.tid, "type": "private"}, "text": "8.8.8.8"},
        })
        u = asyncio.get_event_loop().run_until_complete(mongo_db.users.find_one({"telegram_id": self.tid}))
        assert u.get("state") is None, f"state should be cleared, got {u.get('state')}"
        assert u.get("scans_today", 0) >= 1
        scans = asyncio.get_event_loop().run_until_complete(
            mongo_db.scans.find({"telegram_id": self.tid}).to_list(10))
        assert len(scans) >= 1
        assert scans[0]["tool"] == "ip"
        self._cleanup(mongo_db)


# =========================================================
# REFERRAL FLOW
# =========================================================
class TestReferral:
    ref_tid = 555001
    new_tid = 555002

    def test_referral_credit(self, mongo_db):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(mongo_db.users.delete_many({"telegram_id": {"$in": [self.ref_tid, self.new_tid]}}))
        # create referrer
        _post_update({
            "update_id": int(time.time()) + 10,
            "message": {"message_id": 1, "from": {"id": self.ref_tid, "first_name": "Ref"},
                        "chat": {"id": self.ref_tid, "type": "private"}, "text": "/start"},
        })
        # new user with referral
        _post_update({
            "update_id": int(time.time()) + 11,
            "message": {"message_id": 1, "from": {"id": self.new_tid, "first_name": "New"},
                        "chat": {"id": self.new_tid, "type": "private"},
                        "text": f"/start {self.ref_tid}"},
        })
        new_u = loop.run_until_complete(mongo_db.users.find_one({"telegram_id": self.new_tid}))
        ref_u = loop.run_until_complete(mongo_db.users.find_one({"telegram_id": self.ref_tid}))
        assert new_u is not None
        assert new_u.get("referred_by") == self.ref_tid, f"referred_by={new_u.get('referred_by')}"
        assert ref_u.get("ref_count", 0) >= 1
        assert ref_u.get("points", 0) >= 25
        loop.run_until_complete(mongo_db.users.delete_many({"telegram_id": {"$in": [self.ref_tid, self.new_tid]}}))


# =========================================================
# CTF FLOW
# =========================================================
class TestCTF:
    tid = 990003

    def test_ctf_correct_flag(self, mongo_db):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(mongo_db.users.delete_many({"telegram_id": self.tid}))
        loop.run_until_complete(mongo_db.ctf_submissions.delete_many({"telegram_id": self.tid}))
        # start
        _post_update({
            "update_id": int(time.time()) + 20,
            "message": {"message_id": 1, "from": {"id": self.tid, "first_name": "C"},
                        "chat": {"id": self.tid, "type": "private"}, "text": "/start"},
        })
        # callback solve:c2
        _post_update({
            "update_id": int(time.time()) + 21,
            "callback_query": {
                "id": "cbq2", "from": {"id": self.tid, "first_name": "C"},
                "message": {"message_id": 5, "chat": {"id": self.tid, "type": "private"}},
                "data": "solve:c2",
            },
        })
        u = loop.run_until_complete(mongo_db.users.find_one({"telegram_id": self.tid}))
        assert u.get("state") == "ctfflag:c2"

        # wrong flag first
        _post_update({
            "update_id": int(time.time()) + 22,
            "message": {"message_id": 2, "from": {"id": self.tid, "first_name": "C"},
                        "chat": {"id": self.tid, "type": "private"}, "text": "FLAG{wrong}"},
        })
        u = loop.run_until_complete(mongo_db.users.find_one({"telegram_id": self.tid}))
        assert u.get("points", 0) == 0, "wrong flag must not grant points"
        assert "c2" not in u.get("solved", [])

        # re-open (state cleared after wrong attempt), press solve again
        _post_update({
            "update_id": int(time.time()) + 23,
            "callback_query": {
                "id": "cbq3", "from": {"id": self.tid, "first_name": "C"},
                "message": {"message_id": 6, "chat": {"id": self.tid, "type": "private"}},
                "data": "solve:c2",
            },
        })
        # correct flag
        _post_update({
            "update_id": int(time.time()) + 24,
            "message": {"message_id": 3, "from": {"id": self.tid, "first_name": "C"},
                        "chat": {"id": self.tid, "type": "private"}, "text": "FLAG{b64_decoded}"},
        })
        u = loop.run_until_complete(mongo_db.users.find_one({"telegram_id": self.tid}))
        assert "c2" in u.get("solved", []), f"solved={u.get('solved')}"
        assert u.get("points", 0) >= 60
        subs = loop.run_until_complete(
            mongo_db.ctf_submissions.find({"telegram_id": self.tid, "correct": True}).to_list(10))
        assert len(subs) >= 1
        loop.run_until_complete(mongo_db.users.delete_many({"telegram_id": self.tid}))
        loop.run_until_complete(mongo_db.ctf_submissions.delete_many({"telegram_id": self.tid}))


# =========================================================
# OSINT modules (direct)
# =========================================================
class TestOSINTFunctions:
    def test_all_tools_return_non_empty_html(self):
        import osint
        loop = asyncio.get_event_loop()

        async def run_all():
            return {
                "ip": await osint.ip_lookup("8.8.8.8"),
                "phone": await osint.phone_lookup("+14155552671"),
                "dns": await osint.dns_lookup("google.com"),
                "whois": await osint.domain_whois("github.com"),
                "email": await osint.email_breach("test@example.com"),
                "pwd": await osint.password_pwned("password"),
                "hash": await osint.hash_generate("x"),
                "b64": await osint.base64_tool("aGVsbG8="),
            }
        results = loop.run_until_complete(run_all())
        for k, v in results.items():
            assert isinstance(v, str) and len(v) > 0, f"{k} returned empty"


# =========================================================
# PAYMENTS
# =========================================================
class TestPayments:
    def test_checkout_success(self, api, mongo_db):
        payload = {
            "package_id": "pro_monthly",
            "telegram_id": "123456789",
            "origin_url": BASE_URL,
        }
        r = api.post(f"{BASE_URL}/api/payments/checkout", json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "checkout_url" in d and d["checkout_url"].startswith("http")
        assert "session_id" in d and d["session_id"]
        # verify persistence
        rec = asyncio.get_event_loop().run_until_complete(
            mongo_db.payment_transactions.find_one({"session_id": d["session_id"]}))
        assert rec is not None
        assert rec["payment_status"] == "pending"
        assert rec["package_id"] == "pro_monthly"

    def test_checkout_invalid_telegram_id(self, api):
        r = api.post(f"{BASE_URL}/api/payments/checkout", json={
            "package_id": "pro_monthly", "telegram_id": "abc", "origin_url": BASE_URL})
        assert r.status_code == 400

    def test_checkout_unknown_package(self, api):
        r = api.post(f"{BASE_URL}/api/payments/checkout", json={
            "package_id": "nope", "telegram_id": "123", "origin_url": BASE_URL})
        assert r.status_code == 400

    def test_status_endpoint(self, api):
        # first create a session
        r = api.post(f"{BASE_URL}/api/payments/checkout", json={
            "package_id": "pro_monthly", "telegram_id": "123456789", "origin_url": BASE_URL})
        assert r.status_code == 200
        sid = r.json()["session_id"]
        r2 = api.get(f"{BASE_URL}/api/payments/status/{sid}")
        assert r2.status_code == 200
        d = r2.json()
        for k in ("session_id", "status", "payment_status", "package_id"):
            assert k in d


# =========================================================
# ADMIN
# =========================================================
class TestAdmin:
    def test_login_ok(self, api):
        r = api.post(f"{BASE_URL}/api/admin/login", json={"key": ADMIN_KEY})
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_login_wrong_key(self, api):
        r = api.post(f"{BASE_URL}/api/admin/login", json={"key": "bad"})
        assert r.status_code == 403

    def test_overview(self, api):
        r = api.get(f"{BASE_URL}/api/admin/overview", params={"key": ADMIN_KEY})
        assert r.status_code == 200
        d = r.json()
        for k in ("users", "revenue", "paid_subscriptions", "plan_breakdown", "scans"):
            assert k in d
        assert set(d["plan_breakdown"].keys()) >= {"free", "pro", "elite"}

    def test_users_list(self, api):
        r = api.get(f"{BASE_URL}/api/admin/users", params={"key": ADMIN_KEY})
        assert r.status_code == 200
        assert isinstance(r.json().get("users"), list)

    def test_broadcast(self, api):
        r = api.post(f"{BASE_URL}/api/admin/broadcast",
                     json={"key": ADMIN_KEY, "message": "TEST_ping"})
        assert r.status_code == 200
        d = r.json()
        assert "sent" in d and "total" in d
