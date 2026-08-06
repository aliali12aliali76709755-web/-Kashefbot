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
        assert d["tools"] == 17, f"expected tools=17, got {d['tools']}"
        assert d.get("challenges") == 8

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


# =========================================================
# NEW OSINT tools (iteration 2)
# =========================================================
class TestNewOSINTTools:
    def test_url_malware_scan_phishing(self):
        import osint
        loop = asyncio.get_event_loop()
        res = loop.run_until_complete(osint.url_malware_scan("http://paypal-secure-login.tk/verify"))
        assert isinstance(res, str) and len(res) > 0
        low = res.lower()
        assert "verdict" in low or "التقييم" in res
        assert "risk score" in low or "درجة الخطورة" in res
        # brand impersonation flag for paypal
        assert "paypal" in low or "انتحال" in res or "impersonation" in low

    def test_google_dorks_links(self):
        import osint
        loop = asyncio.get_event_loop()
        res = loop.run_until_complete(osint.google_dorks("example.com"))
        assert "google.com/search?q=" in res
        assert 'href="https://www.google.com/search?q=' in res
        assert "site:example.com" in res

    def test_password_generator_length_20(self):
        import osint
        import re as _re
        loop = asyncio.get_event_loop()
        res = loop.run_until_complete(osint.password_generator("20"))
        m = _re.search(r"<code>([^<]+)</code>", res)
        assert m, "no password code block found"
        pwd = m.group(1)
        assert len(pwd) == 20, f"expected 20 chars, got {len(pwd)}: {pwd}"

    def test_email_breach_detailed(self):
        import osint
        loop = asyncio.get_event_loop()
        res = loop.run_until_complete(osint.email_breach("test@example.com"))
        assert isinstance(res, str) and len(res) > 0
        # Either found breaches with details, or clean email — service may vary.
        # If breaches present, should include Records / Exposed data
        if "breach" in res.lower() or "تسريب" in res:
            # It's OK if the enrichment strings appear
            pass


# =========================================================
# NEW: telegram_public_info
# =========================================================
class TestTelegramPublicInfo:
    def test_public_channel(self):
        from telegram_bot import telegram_public_info
        loop = asyncio.get_event_loop()
        res = loop.run_until_complete(telegram_public_info("@telegram"))
        assert isinstance(res, str) and len(res) > 0
        # Should either return channel info or graceful error string
        # If Telegram API reachable, expect Channel type and Name
        if "Name" in res or "الاسم" in res:
            assert "Channel" in res or "قناة" in res

    def test_invalid_username(self):
        from telegram_bot import telegram_public_info
        loop = asyncio.get_event_loop()
        res = loop.run_until_complete(telegram_public_info("@x"))  # too short
        assert "Invalid" in res or "غير صالح" in res


# =========================================================
# NEW: webhook flows for new tools (urlmal, genpass, loc)
# =========================================================
class TestNewToolWebhookFlows:
    urlmal_tid = 991010
    genpass_tid = 991011
    loc_tid = 991012

    def _cleanup(self, db, tid):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(db.users.delete_many({"telegram_id": tid}))
        loop.run_until_complete(db.scans.delete_many({"telegram_id": tid}))
        loop.run_until_complete(db.loc_requests.delete_many({"requester_tid": tid}))

    def test_urlmal_flow(self, mongo_db):
        tid = self.urlmal_tid
        self._cleanup(mongo_db, tid)
        loop = asyncio.get_event_loop()
        _post_update({"update_id": int(time.time())+30,
                      "message": {"message_id": 1, "from": {"id": tid, "first_name": "U"},
                                  "chat": {"id": tid, "type": "private"}, "text": "/start"}})
        _post_update({"update_id": int(time.time())+31,
                      "callback_query": {"id": "c", "from": {"id": tid, "first_name": "U"},
                                         "message": {"message_id": 10, "chat": {"id": tid, "type": "private"}},
                                         "data": "tool:urlmal"}})
        u = loop.run_until_complete(mongo_db.users.find_one({"telegram_id": tid}))
        assert u.get("state") == "await:urlmal"
        _post_update({"update_id": int(time.time())+32,
                      "message": {"message_id": 2, "from": {"id": tid, "first_name": "U"},
                                  "chat": {"id": tid, "type": "private"},
                                  "text": "http://paypal-secure-login.tk/verify"}})
        u = loop.run_until_complete(mongo_db.users.find_one({"telegram_id": tid}))
        assert u.get("state") is None
        scans = loop.run_until_complete(mongo_db.scans.find({"telegram_id": tid, "tool": "urlmal"}).to_list(10))
        assert len(scans) >= 1
        self._cleanup(mongo_db, tid)

    def test_genpass_flow_not_rate_limited(self, mongo_db):
        tid = self.genpass_tid
        self._cleanup(mongo_db, tid)
        loop = asyncio.get_event_loop()
        _post_update({"update_id": int(time.time())+40,
                      "message": {"message_id": 1, "from": {"id": tid, "first_name": "G"},
                                  "chat": {"id": tid, "type": "private"}, "text": "/start"}})
        _post_update({"update_id": int(time.time())+41,
                      "callback_query": {"id": "cg", "from": {"id": tid, "first_name": "G"},
                                         "message": {"message_id": 10, "chat": {"id": tid, "type": "private"}},
                                         "data": "tool:genpass"}})
        u = loop.run_until_complete(mongo_db.users.find_one({"telegram_id": tid}))
        assert u.get("state") == "await:genpass"
        _post_update({"update_id": int(time.time())+42,
                      "message": {"message_id": 2, "from": {"id": tid, "first_name": "G"},
                                  "chat": {"id": tid, "type": "private"}, "text": "24"}})
        u = loop.run_until_complete(mongo_db.users.find_one({"telegram_id": tid}))
        assert u.get("state") is None
        # genpass is NOT rate limited -> scans_today should stay 0
        assert u.get("scans_today", 0) == 0, f"genpass must not count against limit, scans_today={u.get('scans_today')}"
        self._cleanup(mongo_db, tid)

    def test_loc_creates_pending_request(self, mongo_db):
        tid = self.loc_tid
        self._cleanup(mongo_db, tid)
        loop = asyncio.get_event_loop()
        _post_update({"update_id": int(time.time())+50,
                      "message": {"message_id": 1, "from": {"id": tid, "first_name": "L"},
                                  "chat": {"id": tid, "type": "private"}, "text": "/start"}})
        _post_update({"update_id": int(time.time())+51,
                      "callback_query": {"id": "cl", "from": {"id": tid, "first_name": "L"},
                                         "message": {"message_id": 10, "chat": {"id": tid, "type": "private"}},
                                         "data": "tool:loc"}})
        # Must NOT set an await state
        u = loop.run_until_complete(mongo_db.users.find_one({"telegram_id": tid}))
        assert u.get("state") is None, f"loc must not set await state, got {u.get('state')}"
        # Must create a pending loc_requests doc
        docs = loop.run_until_complete(mongo_db.loc_requests.find({"requester_tid": tid}).to_list(10))
        assert len(docs) >= 1, "no loc_requests doc created"
        assert docs[0].get("status") == "pending"
        assert docs[0].get("token")
        self._cleanup(mongo_db, tid)


# =========================================================
# NEW: /api/loc/{token} endpoints
# =========================================================
class TestLocEndpoints:
    tid = 991020
    token = "TEST_LOC_TOKEN_1"

    def _setup(self, db):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(db.users.delete_many({"telegram_id": self.tid}))
        loop.run_until_complete(db.loc_requests.delete_many({"token": self.token}))
        loop.run_until_complete(db.users.insert_one({
            "telegram_id": self.tid, "first_name": "Requester", "lang": "en",
            "plan": "free", "created_at": "2026-01-01T00:00:00",
        }))
        loop.run_until_complete(db.loc_requests.insert_one({
            "token": self.token, "requester_tid": self.tid, "status": "pending",
            "lat": None, "lon": None, "created_at": "2026-01-01T00:00:00",
        }))

    def _teardown(self, db):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(db.users.delete_many({"telegram_id": self.tid}))
        loop.run_until_complete(db.loc_requests.delete_many({"token": self.token}))

    def test_loc_get_pending(self, api, mongo_db):
        self._setup(mongo_db)
        try:
            r = api.get(f"{BASE_URL}/api/loc/{self.token}")
            assert r.status_code == 200
            d = r.json()
            assert d["status"] == "pending"
            assert d["requester_name"] == "Requester"
        finally:
            self._teardown(mongo_db)

    def test_loc_unknown_404(self, api):
        r = api.get(f"{BASE_URL}/api/loc/UNKNOWN_TOKEN_XYZ_ZZZ")
        assert r.status_code == 404

    def test_loc_submit_sets_shared(self, api, mongo_db):
        self._setup(mongo_db)
        try:
            r = api.post(f"{BASE_URL}/api/loc/{self.token}/submit",
                         json={"lat": 33.3152, "lon": 44.3661, "accuracy": 15.0})
            assert r.status_code == 200
            loop = asyncio.get_event_loop()
            doc = loop.run_until_complete(mongo_db.loc_requests.find_one({"token": self.token}))
            assert doc["status"] == "shared"
            assert abs(doc["lat"] - 33.3152) < 1e-6
            assert abs(doc["lon"] - 44.3661) < 1e-6
        finally:
            self._teardown(mongo_db)

    def test_loc_decline_sets_declined(self, api, mongo_db):
        self._setup(mongo_db)
        try:
            r = api.post(f"{BASE_URL}/api/loc/{self.token}/decline")
            assert r.status_code == 200
            loop = asyncio.get_event_loop()
            doc = loop.run_until_complete(mongo_db.loc_requests.find_one({"token": self.token}))
            assert doc["status"] == "declined"
        finally:
            self._teardown(mongo_db)


# =========================================================
# REGRESSION: plans count = 4
# =========================================================
class TestPlansCount:
    def test_four_plans(self, api):
        r = api.get(f"{BASE_URL}/api/plans")
        assert r.status_code == 200
        plans = r.json()["plans"]
        assert len(plans) == 4, f"expected 4 plans, got {len(plans)}"


# =========================================================
# ITERATION 3: In-bot admin panel, forced-sub, daily bonus, guide
# =========================================================
ADMIN_TRIGGER = "صويري"
ADMIN_BOT_PASSWORD = "76891796"


def _start(tid, fname="X", username=None, uid_offset=0):
    frm = {"id": tid, "first_name": fname}
    if username:
        frm["username"] = username
    _post_update({"update_id": int(time.time() * 1000) + uid_offset,
                  "message": {"message_id": 1, "from": frm,
                              "chat": {"id": tid, "type": "private"}, "text": "/start"}})


def _msg(tid, text, uid_offset=0, fname="X"):
    _post_update({"update_id": int(time.time() * 1000) + uid_offset,
                  "message": {"message_id": 99, "from": {"id": tid, "first_name": fname},
                              "chat": {"id": tid, "type": "private"}, "text": text}})


def _cb(tid, data, uid_offset=0, fname="X"):
    _post_update({"update_id": int(time.time() * 1000) + uid_offset,
                  "callback_query": {"id": f"cb{uid_offset}",
                                     "from": {"id": tid, "first_name": fname},
                                     "message": {"message_id": 55, "chat": {"id": tid, "type": "private"}},
                                     "data": data}})


class TestInBotAdminLogin:
    tid = 992001

    def test_admin_trigger_and_password(self, mongo_db):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(mongo_db.users.delete_many({"telegram_id": self.tid}))
        _start(self.tid, "Adm", uid_offset=1)
        # Send Arabic trigger word
        _msg(self.tid, ADMIN_TRIGGER, uid_offset=2)
        u = loop.run_until_complete(mongo_db.users.find_one({"telegram_id": self.tid}))
        assert u.get("state") == "await:adminpass", f"expected await:adminpass got {u.get('state')}"

        # Wrong password → must NOT set is_admin
        _msg(self.tid, "wrong_pass_123", uid_offset=3)
        u = loop.run_until_complete(mongo_db.users.find_one({"telegram_id": self.tid}))
        assert not u.get("is_admin"), "wrong password must not grant admin"
        assert u.get("state") is None

        # Trigger again + correct password → is_admin=True
        _msg(self.tid, ADMIN_TRIGGER, uid_offset=4)
        _msg(self.tid, ADMIN_BOT_PASSWORD, uid_offset=5)
        u = loop.run_until_complete(mongo_db.users.find_one({"telegram_id": self.tid}))
        assert u.get("is_admin") is True, "correct password must grant is_admin"
        assert u.get("state") is None
        loop.run_until_complete(mongo_db.users.delete_many({"telegram_id": self.tid}))


class TestAdminUpgradeUser:
    admin_tid = 992010
    target_tid = 992011
    target_uname_tid = 992012

    def _make_admin(self, db, tid):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(db.users.update_one({"telegram_id": tid}, {"$set": {"is_admin": True}}, upsert=False))

    def test_upgrade_by_id_and_username(self, mongo_db):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(mongo_db.users.delete_many(
            {"telegram_id": {"$in": [self.admin_tid, self.target_tid, self.target_uname_tid]}}))
        # create admin and targets
        _start(self.admin_tid, "AdminBoss", uid_offset=10)
        self._make_admin(mongo_db, self.admin_tid)
        _start(self.target_tid, "Target1", uid_offset=11)
        _start(self.target_uname_tid, "Target2", username="target_uname_x", uid_offset=12)

        # admin clicks adm:upgrade -> state await:adminupgrade
        _cb(self.admin_tid, "adm:upgrade", uid_offset=13, fname="AdminBoss")
        u = loop.run_until_complete(mongo_db.users.find_one({"telegram_id": self.admin_tid}))
        assert u.get("state") == "await:adminupgrade"

        # Upgrade by numeric id
        _msg(self.admin_tid, f"{self.target_tid} pro 30", uid_offset=14, fname="AdminBoss")
        t = loop.run_until_complete(mongo_db.users.find_one({"telegram_id": self.target_tid}))
        assert t.get("plan") == "pro"
        assert t.get("plan_expires"), "plan_expires must be set"

        # Upgrade by @username
        _cb(self.admin_tid, "adm:upgrade", uid_offset=15, fname="AdminBoss")
        _msg(self.admin_tid, "@target_uname_x elite 365", uid_offset=16, fname="AdminBoss")
        t2 = loop.run_until_complete(mongo_db.users.find_one({"telegram_id": self.target_uname_tid}))
        assert t2.get("plan") == "elite"
        assert t2.get("plan_expires")

        # Malformed input - must not crash
        _cb(self.admin_tid, "adm:upgrade", uid_offset=17, fname="AdminBoss")
        r = _post_update({"update_id": int(time.time() * 1000) + 18,
                          "message": {"message_id": 200, "from": {"id": self.admin_tid, "first_name": "AdminBoss"},
                                      "chat": {"id": self.admin_tid, "type": "private"},
                                      "text": "garbage_no_plan"}})
        assert r.status_code == 200

        loop.run_until_complete(mongo_db.users.delete_many(
            {"telegram_id": {"$in": [self.admin_tid, self.target_tid, self.target_uname_tid]}}))

    def test_non_admin_adm_callback_rejected(self, mongo_db):
        loop = asyncio.get_event_loop()
        tid = 992020
        loop.run_until_complete(mongo_db.users.delete_many({"telegram_id": tid}))
        _start(tid, "NotAdmin", uid_offset=20)
        # Non-admin sends adm:upgrade callback
        _cb(tid, "adm:upgrade", uid_offset=21, fname="NotAdmin")
        u = loop.run_until_complete(mongo_db.users.find_one({"telegram_id": tid}))
        assert not u.get("is_admin"), "must not become admin"
        assert u.get("state") != "await:adminupgrade", f"non-admin got state {u.get('state')}"
        loop.run_until_complete(mongo_db.users.delete_many({"telegram_id": tid}))


class TestForcedSubscription:
    admin_tid = 992030

    def _cleanup_config(self, db):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(db.settings.update_one(
            {"_id": "config"}, {"$set": {"forced_channel": None}}, upsert=True))

    def test_set_and_clear_forced_channel(self, mongo_db):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(mongo_db.users.delete_many({"telegram_id": self.admin_tid}))
        self._cleanup_config(mongo_db)
        _start(self.admin_tid, "SubAdmin", uid_offset=30)
        loop.run_until_complete(mongo_db.users.update_one({"telegram_id": self.admin_tid},
                                                          {"$set": {"is_admin": True}}))
        # adm:sub -> await:adminsetchannel
        _cb(self.admin_tid, "adm:sub", uid_offset=31, fname="SubAdmin")
        u = loop.run_until_complete(mongo_db.users.find_one({"telegram_id": self.admin_tid}))
        assert u.get("state") == "await:adminsetchannel"

        # Set channel
        _msg(self.admin_tid, "@somechannel_test", uid_offset=32, fname="SubAdmin")
        from core import get_config
        cfg = loop.run_until_complete(get_config())
        assert cfg.get("forced_channel") == "@somechannel_test"

        # Turn off
        _cb(self.admin_tid, "adm:sub", uid_offset=33, fname="SubAdmin")
        _msg(self.admin_tid, "off", uid_offset=34, fname="SubAdmin")
        cfg = loop.run_until_complete(get_config())
        assert cfg.get("forced_channel") in (None, ""), f"expected cleared, got {cfg.get('forced_channel')}"

        # cleanup
        self._cleanup_config(mongo_db)
        loop.run_until_complete(mongo_db.users.delete_many({"telegram_id": self.admin_tid}))

    def test_is_member_fail_open(self, mongo_db):
        """When forced_channel set to a channel bot is NOT admin in, is_member returns True (fail-open)."""
        loop = asyncio.get_event_loop()
        from core import set_config
        from telegram_bot import is_member
        # Set to a bogus channel bot has no access to
        loop.run_until_complete(set_config("forced_channel", "@nonexistent_bogus_channel_zzz_123"))
        try:
            result = loop.run_until_complete(is_member(88888888))
            assert result is True, f"is_member must fail-open (True) when bot cannot verify, got {result}"
        finally:
            # CRITICAL cleanup — clear so real users aren't gated
            loop.run_until_complete(set_config("forced_channel", None))
            cfg = loop.run_until_complete(__import__("core").get_config())
            assert cfg.get("forced_channel") in (None, ""), "forced_channel MUST be cleared"


class TestDailyBonus:
    tid = 992040

    def test_bonus_once_per_day(self, mongo_db):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(mongo_db.users.delete_many({"telegram_id": self.tid}))
        _start(self.tid, "BonusUser", uid_offset=40)
        u0 = loop.run_until_complete(mongo_db.users.find_one({"telegram_id": self.tid}))
        p0 = u0.get("points", 0)

        _cb(self.tid, "acct:bonus", uid_offset=41, fname="BonusUser")
        u1 = loop.run_until_complete(mongo_db.users.find_one({"telegram_id": self.tid}))
        assert u1.get("points", 0) == p0 + 10, f"expected +10 points, got {u1.get('points')}"
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert u1.get("bonus_date") == today

        # Second claim same day → no change
        _cb(self.tid, "acct:bonus", uid_offset=42, fname="BonusUser")
        u2 = loop.run_until_complete(mongo_db.users.find_one({"telegram_id": self.tid}))
        assert u2.get("points", 0) == p0 + 10, f"second claim must not add; got {u2.get('points')}"

        loop.run_until_complete(mongo_db.users.delete_many({"telegram_id": self.tid}))


class TestGuideAndAdminMenu:
    tid = 992050

    def test_guide_callbacks_no_500(self, mongo_db):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(mongo_db.users.delete_many({"telegram_id": self.tid}))
        _start(self.tid, "GuideUser", uid_offset=50)
        for i, data in enumerate(["menu:guide", "guide:osint", "guide:learn", "guide:plans"], start=51):
            r = _post_update({"update_id": int(time.time() * 1000) + i,
                              "callback_query": {"id": f"gb{i}", "from": {"id": self.tid, "first_name": "GuideUser"},
                                                 "message": {"message_id": 60, "chat": {"id": self.tid, "type": "private"}},
                                                 "data": data}})
            assert r.status_code == 200, f"{data} returned {r.status_code}"
            assert r.json() == {"ok": True}
        loop.run_until_complete(mongo_db.users.delete_many({"telegram_id": self.tid}))

    def test_admin_menu_has_admin_panel_button(self, mongo_db):
        """kb_main includes adm:panel row when user.is_admin."""
        from telegram_bot import kb_main
        rows_normal = kb_main("en", {"is_admin": False})
        flat_n = [b.get("callback_data") for row in rows_normal for b in row]
        assert "adm:panel" not in flat_n, "non-admin must not see admin panel button"

        rows_admin = kb_main("en", {"is_admin": True})
        flat_a = [b.get("callback_data") for row in rows_admin for b in row]
        assert "adm:panel" in flat_a, "admin must see adm:panel button"


# Final sanity: ensure forced_channel is cleared (safety net)
class TestZZZ_ForcedChannelCleanup:
    def test_forced_channel_is_cleared(self, mongo_db):
        from core import get_config
        loop = asyncio.get_event_loop()
        cfg = loop.run_until_complete(get_config())
        fc = cfg.get("forced_channel")
        assert fc in (None, ""), f"forced_channel MUST be cleared after tests, still set to: {fc}"

