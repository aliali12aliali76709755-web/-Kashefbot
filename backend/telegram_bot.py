"""Telegram bot logic: bilingual menus, OSINT tools, academy, CTF, courses, subscriptions."""
import html

from core import (
    db, tg, PLANS, LIMITS, effective_plan, get_or_create_user,
    set_state, set_lang, check_and_increment, now_utc,
)
import osint
import content
import payments

BOT_USERNAME = None  # filled on startup


def esc(v):
    return html.escape(str(v))


# ---------- i18n ----------
def T(lang, ar, en):
    return ar if lang == "ar" else en


# ---------- tool registry ----------
# key -> (function, ar_prompt, en_prompt, counts_against_limit)
TOOLS = {
    "ip":       (osint.ip_lookup,      "🌐 أرسل عنوان IP (مثال: 8.8.8.8)", "🌐 Send an IP address (e.g. 8.8.8.8)", True),
    "phone":    (osint.phone_lookup,   "📞 أرسل رقم الهاتف مع رمز الدولة (+9647...)", "📞 Send a phone number with country code (+1...)", True),
    "domain":   (osint.domain_whois,   "🔎 أرسل اسم النطاق (مثال: google.com)", "🔎 Send a domain name (e.g. google.com)", True),
    "dns":      (osint.dns_lookup,     "🧭 أرسل اسم النطاق لجلب سجلات DNS", "🧭 Send a domain to fetch DNS records", True),
    "email":    (osint.email_breach,   "📧 أرسل البريد الإلكتروني لفحص التسريبات", "📧 Send an email to check for breaches", True),
    "pwd":      (osint.password_pwned,  "🔑 أرسل كلمة المرور للتحقق إن كانت مسرّبة (لا نخزّنها)", "🔑 Send a password to check if it's pwned (we never store it)", True),
    "user":     (osint.username_search, "🕵️ أرسل اسم المستخدم للبحث عبر المنصات", "🕵️ Send a username to search across platforms", True),
    "url":      (osint.url_analyze,     "🔗 أرسل الرابط لتحليله", "🔗 Send a URL to analyze", True),
    "emailval": (osint.email_validate,  "✅ أرسل البريد للتحقق من صحته", "✅ Send an email to verify", True),
    "hashgen":  (osint.hash_generate,   "🔐 أرسل نصاً لتوليد بصماته", "🔐 Send text to generate hashes", False),
    "hashid":   (osint.hash_identify,   "🧩 أرسل البصمة لتحديد نوعها", "🧩 Send a hash to identify its type", False),
    "b64":      (osint.base64_tool,     "🔁 أرسل نصاً للترميز/فك الترميز Base64", "🔁 Send text to Base64 encode/decode", False),
}


# ---------- keyboards ----------
def kb_main(lang):
    return [
        [{"text": T(lang, "🛰️ أدوات OSINT", "🛰️ OSINT Tools"), "callback_data": "menu:osint"}],
        [{"text": T(lang, "🎓 أكاديمية الاختراق الأخلاقي", "🎓 Ethical Hacking Academy"), "callback_data": "menu:academy"}],
        [{"text": T(lang, "🚩 تحديات CTF", "🚩 CTF Challenges"), "callback_data": "menu:ctf"},
         {"text": T(lang, "🏆 المتصدّرون", "🏆 Leaderboard"), "callback_data": "ctf:board"}],
        [{"text": T(lang, "💻 تعلّم البرمجة", "💻 Learn to Code"), "callback_data": "menu:courses"}],
        [{"text": T(lang, "👤 حسابي", "👤 My Account"), "callback_data": "menu:account"},
         {"text": T(lang, "💎 ترقية", "💎 Upgrade"), "callback_data": "menu:upgrade"}],
        [{"text": T(lang, "🌐 English", "🌐 العربية"), "callback_data": "lang:toggle"}],
    ]


def kb_osint(lang):
    rows = [
        [{"text": T(lang, "🌐 معلومات IP", "🌐 IP Lookup"), "callback_data": "tool:ip"},
         {"text": T(lang, "📞 تحليل رقم", "📞 Phone Lookup"), "callback_data": "tool:phone"}],
        [{"text": T(lang, "🔎 WHOIS نطاق", "🔎 Domain WHOIS"), "callback_data": "tool:domain"},
         {"text": T(lang, "🧭 سجلات DNS", "🧭 DNS Records"), "callback_data": "tool:dns"}],
        [{"text": T(lang, "📧 فحص تسريب بريد", "📧 Email Breach"), "callback_data": "tool:email"},
         {"text": T(lang, "🔑 كلمة مرور مسرّبة", "🔑 Pwned Password"), "callback_data": "tool:pwd"}],
        [{"text": T(lang, "🕵️ بحث اسم مستخدم", "🕵️ Username Search"), "callback_data": "tool:user"},
         {"text": T(lang, "🔗 تحليل رابط", "🔗 URL Analysis"), "callback_data": "tool:url"}],
        [{"text": T(lang, "✅ تحقق بريد", "✅ Email Verify"), "callback_data": "tool:emailval"},
         {"text": T(lang, "🔐 مولّد Hash", "🔐 Hash Gen"), "callback_data": "tool:hashgen"}],
        [{"text": T(lang, "🧩 تحديد Hash", "🧩 Hash ID"), "callback_data": "tool:hashid"},
         {"text": T(lang, "🔁 Base64", "🔁 Base64"), "callback_data": "tool:b64"}],
        [{"text": T(lang, "⬅️ رجوع", "⬅️ Back"), "callback_data": "menu:main"}],
    ]
    return rows


def kb_back(lang, to="menu:main"):
    return [[{"text": T(lang, "⬅️ رجوع", "⬅️ Back"), "callback_data": to}]]


def kb_academy(lang):
    rows = [[{"text": m["title"][lang], "callback_data": f"acad:{m['id']}"}] for m in content.ACADEMY]
    rows.append([{"text": T(lang, "⬅️ رجوع", "⬅️ Back"), "callback_data": "menu:main"}])
    return rows


def kb_courses(lang):
    rows = [[{"text": c["title"][lang], "callback_data": f"course:{c['id']}"}] for c in content.COURSES]
    rows.append([{"text": T(lang, "⬅️ رجوع", "⬅️ Back"), "callback_data": "menu:main"}])
    return rows


def kb_ctf(lang):
    rows = []
    for ch in content.CTF:
        rows.append([{"text": f"{ch['title'][lang]} · {ch['points']}pts", "callback_data": f"ctf:{ch['id']}"}])
    rows.append([{"text": T(lang, "🏆 المتصدّرون", "🏆 Leaderboard"), "callback_data": "ctf:board"}])
    rows.append([{"text": T(lang, "⬅️ رجوع", "⬅️ Back"), "callback_data": "menu:main"}])
    return rows


def kb_upgrade(lang):
    return [
        [{"text": f"💎 {PLANS['pro_monthly']['label_'+lang]} · $9.99", "callback_data": "buy:pro_monthly"}],
        [{"text": f"💎 {PLANS['pro_yearly']['label_'+lang]} · $95.90", "callback_data": "buy:pro_yearly"}],
        [{"text": f"👑 {PLANS['elite_monthly']['label_'+lang]} · $24.99", "callback_data": "buy:elite_monthly"}],
        [{"text": f"👑 {PLANS['elite_yearly']['label_'+lang]} · $239.90", "callback_data": "buy:elite_yearly"}],
        [{"text": T(lang, "⬅️ رجوع", "⬅️ Back"), "callback_data": "menu:main"}],
    ]


# ---------- screen texts ----------
def main_text(lang, user):
    plan = effective_plan(user).upper()
    if lang == "ar":
        return (
            "🛡️ <b>CYBER OSINT SUITE</b>\n"
            "<i>منصّتك الاحترافية للأمن السيبراني وجمع المعلومات القانوني</i>\n\n"
            "اختر من القائمة:\n"
            "• 🛰️ أدوات OSINT من مصادر عامة\n"
            "• 🎓 أكاديمية اختراق أخلاقي\n"
            "• 🚩 تحديات CTF ونقاط\n"
            "• 💻 تعلّم البرمجة\n\n"
            f"باقتك الحالية: <b>{plan}</b>"
        )
    return (
        "🛡️ <b>CYBER OSINT SUITE</b>\n"
        "<i>Your professional legal cybersecurity & OSINT platform</i>\n\n"
        "Pick from the menu:\n"
        "• 🛰️ OSINT tools from public sources\n"
        "• 🎓 Ethical hacking academy\n"
        "• 🚩 CTF challenges & points\n"
        "• 💻 Learn to code\n\n"
        f"Your plan: <b>{plan}</b>"
    )


def osint_text(lang):
    return T(lang,
             "🛰️ <b>أدوات OSINT</b>\nاختر أداة، ثم أرسل المُدخل المطلوب.\n<i>كل الأدوات تعتمد مصادر عامة وقانونية فقط.</i>",
             "🛰️ <b>OSINT Tools</b>\nPick a tool, then send the required input.\n<i>All tools use public, legal sources only.</i>")


async def account_text(lang, tid):
    u = await db.users.find_one({"telegram_id": tid})
    plan = effective_plan(u)
    limit = LIMITS[plan]
    used = u.get("scans_today", 0)
    left = "∞" if limit >= 100000 else str(max(0, limit - used))
    ref_link = f"https://t.me/{BOT_USERNAME}?start={tid}" if BOT_USERNAME else "—"
    exp = u.get("plan_expires") or "—"
    if lang == "ar":
        return (
            "👤 <b>حسابي</b>\n\n"
            f"الباقة: <b>{plan.upper()}</b>\n"
            f"تنتهي: <code>{esc(exp)}</code>\n"
            f"عمليات اليوم: <b>{used}</b> | المتبقّي: <b>{left}</b>\n"
            f"النقاط: <b>{u.get('points',0)}</b> 🏅\n"
            f"تحديات محلولة: <b>{len(u.get('solved',[]))}</b>\n"
            f"إحالات: <b>{u.get('ref_count',0)}</b>\n\n"
            f"🔗 رابط الإحالة (اكسب 25 نقطة لكل صديق):\n<code>{esc(ref_link)}</code>"
        )
    return (
        "👤 <b>My Account</b>\n\n"
        f"Plan: <b>{plan.upper()}</b>\n"
        f"Expires: <code>{esc(exp)}</code>\n"
        f"Scans today: <b>{used}</b> | Remaining: <b>{left}</b>\n"
        f"Points: <b>{u.get('points',0)}</b> 🏅\n"
        f"Solved challenges: <b>{len(u.get('solved',[]))}</b>\n"
        f"Referrals: <b>{u.get('ref_count',0)}</b>\n\n"
        f"🔗 Referral link (earn 25 pts per friend):\n<code>{esc(ref_link)}</code>"
    )


def upgrade_text(lang):
    if lang == "ar":
        return (
            "💎 <b>ترقية الباقة</b>\n\n"
            "<b>FREE</b> — 8 عمليات/يوم\n"
            "<b>PRO</b> ($9.99/شهر) — 150 عملية/يوم + كل الدروس\n"
            "<b>ELITE</b> ($24.99/شهر) — عمليات غير محدودة + أولوية\n\n"
            "اختر باقتك للدفع الآمن عبر Stripe:"
        )
    return (
        "💎 <b>Upgrade your plan</b>\n\n"
        "<b>FREE</b> — 8 scans/day\n"
        "<b>PRO</b> ($9.99/mo) — 150 scans/day + all lessons\n"
        "<b>ELITE</b> ($24.99/mo) — unlimited scans + priority\n\n"
        "Choose a plan for secure Stripe checkout:"
    )


# ---------- update handling ----------
async def handle_update(update: dict):
    if "callback_query" in update:
        await _handle_callback(update["callback_query"])
    elif "message" in update:
        await _handle_message(update["message"])


async def _handle_message(msg):
    if "text" not in msg:
        return
    tg_user = msg["from"]
    chat_id = msg["chat"]["id"]
    text = msg["text"].strip()

    referred_by = None
    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        if len(parts) > 1 and parts[1].strip().isdigit():
            referred_by = int(parts[1].strip())
    user = await get_or_create_user(tg_user, referred_by)
    lang = user.get("lang", "ar")

    if text.startswith("/start") or text.startswith("/menu"):
        await set_state(chat_id, None)
        await tg.send_message(chat_id, main_text(lang, user), kb_main(lang))
        return
    if text.startswith("/help"):
        await tg.send_message(chat_id, T(lang,
            "الأوامر:\n/start القائمة\n/menu القائمة\n/me حسابي\n/lang تغيير اللغة",
            "Commands:\n/start menu\n/menu menu\n/me account\n/lang change language"), kb_main(lang))
        return
    if text.startswith("/me"):
        await tg.send_message(chat_id, await account_text(lang, chat_id), kb_back(lang))
        return
    if text.startswith("/lang"):
        new = "en" if lang == "ar" else "ar"
        await set_lang(chat_id, new)
        u = await db.users.find_one({"telegram_id": chat_id})
        await tg.send_message(chat_id, main_text(new, u), kb_main(new))
        return

    # stateful input
    state = user.get("state") or ""
    if state.startswith("await:"):
        key = state.split(":", 1)[1]
        await set_state(chat_id, None)
        await _run_tool(chat_id, lang, key, text)
        return
    if state == "await:ctfflag":
        return

    if state.startswith("ctfflag:"):
        cid = state.split(":", 1)[1]
        await set_state(chat_id, None)
        await _check_flag(chat_id, lang, cid, text)
        return

    # default
    await tg.send_message(chat_id, T(lang, "استخدم /menu لفتح القائمة 👇", "Use /menu to open the menu 👇"), kb_main(lang))


async def _run_tool(chat_id, lang, key, text):
    if key not in TOOLS:
        return
    fn, _a, _e, limited = TOOLS[key]
    if limited:
        user = await db.users.find_one({"telegram_id": chat_id})
        allowed = await check_and_increment(user)
        if not allowed:
            await tg.send_message(chat_id, T(lang,
                "🚫 وصلت للحد اليومي المجاني. رقِّ باقتك للمزيد 💎",
                "🚫 Daily free limit reached. Upgrade for more 💎"), kb_upgrade(lang))
            return
    await tg.send_chat_action(chat_id, "typing")
    try:
        result = await fn(text, lang)
    except Exception:
        result = T(lang, "❌ حدث خطأ أثناء المعالجة، حاول مجدداً.", "❌ Something went wrong, please try again.")
    kb = [
        [{"text": T(lang, "🔁 أداة أخرى", "🔁 Another tool"), "callback_data": "menu:osint"}],
        [{"text": T(lang, "🏠 القائمة", "🏠 Menu"), "callback_data": "menu:main"}],
    ]
    await tg.send_message(chat_id, result, kb)
    await db.scans.insert_one({"telegram_id": chat_id, "tool": key, "at": now_utc().isoformat()})


async def _handle_callback(cq):
    data = cq.get("data", "")
    chat_id = cq["message"]["chat"]["id"]
    message_id = cq["message"]["message_id"]
    await get_or_create_user(cq["from"])
    user = await db.users.find_one({"telegram_id": chat_id})
    lang = user.get("lang", "ar")
    await tg.answer_callback(cq["id"])

    async def edit(text, kb):
        await tg.edit_message(chat_id, message_id, text, kb)

    if data == "menu:main":
        await set_state(chat_id, None)
        await edit(main_text(lang, user), kb_main(lang))
    elif data == "lang:toggle":
        new = "en" if lang == "ar" else "ar"
        await set_lang(chat_id, new)
        u = await db.users.find_one({"telegram_id": chat_id})
        await edit(main_text(new, u), kb_main(new))
    elif data == "menu:osint":
        await edit(osint_text(lang), kb_osint(lang))
    elif data == "menu:academy":
        await edit(T(lang, "🎓 <b>أكاديمية الاختراق الأخلاقي</b>\nاختر مساراً:", "🎓 <b>Ethical Hacking Academy</b>\nChoose a track:"), kb_academy(lang))
    elif data == "menu:courses":
        await edit(T(lang, "💻 <b>تعلّم البرمجة</b>\nاختر دورة:", "💻 <b>Learn to Code</b>\nChoose a course:"), kb_courses(lang))
    elif data == "menu:ctf":
        await edit(T(lang, "🚩 <b>تحديات CTF</b>\nحل التحدي وأرسل العلم لتكسب النقاط:", "🚩 <b>CTF Challenges</b>\nSolve and submit the flag to earn points:"), kb_ctf(lang))
    elif data == "menu:account":
        await edit(await account_text(lang, chat_id), kb_back(lang))
    elif data == "menu:upgrade":
        await edit(upgrade_text(lang), kb_upgrade(lang))
    elif data.startswith("tool:"):
        key = data.split(":", 1)[1]
        await set_state(chat_id, f"await:{key}")
        prompt = TOOLS[key][1] if lang == "ar" else TOOLS[key][2]
        await edit(prompt, kb_back(lang, "menu:osint"))
    elif data.startswith("acad:"):
        mid = data.split(":", 1)[1]
        await _show_academy_module(edit, lang, mid)
    elif data.startswith("course:"):
        cid = data.split(":", 1)[1]
        await _show_course(edit, lang, cid)
    elif data.startswith("ctf:"):
        rest = data.split(":", 1)[1]
        if rest == "board":
            await edit(await _leaderboard_text(lang), kb_back(lang, "menu:ctf"))
        else:
            await _show_ctf(edit, lang, rest, chat_id)
    elif data.startswith("solve:"):
        cid = data.split(":", 1)[1]
        await set_state(chat_id, f"ctfflag:{cid}")
        await tg.send_message(chat_id, T(lang, "🚩 أرسل العلم (Flag):", "🚩 Send the flag:"))
    elif data.startswith("buy:"):
        pkg = data.split(":", 1)[1]
        await _start_checkout(chat_id, lang, pkg)


async def _show_academy_module(edit, lang, mid):
    mod = next((m for m in content.ACADEMY if m["id"] == mid), None)
    if not mod:
        return
    parts = [f"<b>{esc(mod['title'][lang])}</b>", ""]
    for i, ls in enumerate(mod["lessons"], 1):
        parts.append(f"<b>{i}. {esc(ls['t'][lang])}</b>")
        parts.append(ls["b"][lang])
        parts.append("")
    await edit("\n".join(parts), kb_back(lang, "menu:academy"))


async def _show_course(edit, lang, cid):
    c = next((x for x in content.COURSES if x["id"] == cid), None)
    if not c:
        return
    parts = [f"<b>{esc(c['title'][lang])}</b>", ""]
    for i, ls in enumerate(c["lessons"], 1):
        parts.append(f"<b>{i}. {esc(ls['t'][lang])}</b>")
        parts.append(ls["b"][lang])
        parts.append("")
    await edit("\n".join(parts), kb_back(lang, "menu:courses"))


async def _show_ctf(edit, lang, cid, chat_id):
    ch = next((x for x in content.CTF if x["id"] == cid), None)
    if not ch:
        return
    user = await db.users.find_one({"telegram_id": chat_id})
    solved = cid in user.get("solved", [])
    status = T(lang, "✅ محلول", "✅ Solved") if solved else T(lang, "⏳ غير محلول", "⏳ Unsolved")
    text = (
        f"🚩 <b>{esc(ch['title'][lang])}</b>\n"
        f"{T(lang,'التصنيف','Category')}: {esc(ch['cat'][lang])} · {ch['points']}pts · {status}\n\n"
        f"{ch['q'][lang]}"
    )
    kb = []
    if not solved:
        kb.append([{"text": T(lang, "📝 إرسال العلم", "📝 Submit flag"), "callback_data": f"solve:{cid}"}])
    kb.append([{"text": T(lang, "⬅️ رجوع", "⬅️ Back"), "callback_data": "menu:ctf"}])
    await edit(text, kb)


async def _check_flag(chat_id, lang, cid, submitted):
    ch = next((x for x in content.CTF if x["id"] == cid), None)
    if not ch:
        return
    user = await db.users.find_one({"telegram_id": chat_id})
    if cid in user.get("solved", []):
        await tg.send_message(chat_id, T(lang, "سبق أن حللت هذا التحدي ✅", "Already solved ✅"), kb_ctf(lang))
        return
    if submitted.strip().lower() == ch["flag"].strip().lower():
        await db.users.update_one({"telegram_id": chat_id},
                                  {"$inc": {"points": ch["points"]}, "$addToSet": {"solved": cid}})
        await db.ctf_submissions.insert_one({"telegram_id": chat_id, "cid": cid, "correct": True, "at": now_utc().isoformat()})
        await tg.send_message(chat_id, T(lang,
            f"🎉 صحيح! حصلت على <b>{ch['points']}</b> نقطة.",
            f"🎉 Correct! You earned <b>{ch['points']}</b> points."), kb_ctf(lang))
    else:
        await tg.send_message(chat_id, T(lang, "❌ علم خاطئ، حاول مجدداً.", "❌ Wrong flag, try again."),
                              [[{"text": T(lang, "📝 إعادة المحاولة", "📝 Retry"), "callback_data": f"solve:{cid}"}],
                               [{"text": T(lang, "⬅️ رجوع", "⬅️ Back"), "callback_data": "menu:ctf"}]])


async def _leaderboard_text(lang):
    top = await db.users.find({}, {"_id": 0, "first_name": 1, "username": 1, "points": 1}).sort("points", -1).limit(10).to_list(10)
    lines = [T(lang, "🏆 <b>لوحة المتصدّرين</b>", "🏆 <b>Leaderboard</b>"), ""]
    medals = ["🥇", "🥈", "🥉"]
    for i, u in enumerate(top):
        if u.get("points", 0) <= 0:
            continue
        name = u.get("first_name") or (("@" + u["username"]) if u.get("username") else "Anon")
        rank = medals[i] if i < 3 else f"{i+1}."
        lines.append(f"{rank} {esc(name)} — <b>{u.get('points',0)}</b>")
    if len(lines) <= 2:
        lines.append(T(lang, "لا يوجد نقاط بعد. كن الأول! 🚀", "No points yet. Be the first! 🚀"))
    return "\n".join(lines)


async def _start_checkout(chat_id, lang, pkg):
    if pkg not in PLANS:
        return
    await tg.send_chat_action(chat_id, "typing")
    try:
        url = await payments.bot_checkout(pkg, chat_id)
    except Exception:
        await tg.send_message(chat_id, T(lang, "❌ تعذّر إنشاء رابط الدفع، حاول لاحقاً.", "❌ Could not create checkout link, try later."), kb_back(lang))
        return
    label = PLANS[pkg]["label_" + lang]
    text = T(lang,
             f"💳 <b>الدفع الآمن</b>\nالباقة: <b>{label}</b>\n\nاضغط الزر لإتمام الدفع عبر Stripe. سيتم تفعيل باقتك تلقائياً بعد الدفع.\n\n<i>وضع تجريبي: استخدم البطاقة 4242 4242 4242 4242</i>",
             f"💳 <b>Secure checkout</b>\nPlan: <b>{label}</b>\n\nTap the button to pay via Stripe. Your plan activates automatically after payment.\n\n<i>Test mode: use card 4242 4242 4242 4242</i>")
    kb = [[{"text": T(lang, "💳 ادفع الآن", "💳 Pay now"), "url": url}],
          [{"text": T(lang, "⬅️ رجوع", "⬅️ Back"), "callback_data": "menu:upgrade"}]]
    await tg.send_message(chat_id, text, kb)
