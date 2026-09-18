"""Telegram bot logic: bilingual menus, OSINT tools, academy, CTF, courses, subscriptions."""
import html
import re
import secrets

from core import (
    db, tg, PLANS, LIMITS, effective_plan, get_or_create_user,
    set_state, set_lang, check_and_increment, now_utc, PUBLIC_BASE_URL,
    ADMIN_ID, ADMIN_PASSWORD, ADMIN_TRIGGER, get_config, set_config,
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


async def telegram_public_info(username: str, lang="ar") -> str:
    u = username.strip().lstrip("@").split("/")[-1]
    if not re.match(r"^[A-Za-z0-9_]{4,32}$", u):
        return T(lang, "❌ اسم مستخدم غير صالح. أرسل يوزر عام مثل <code>@durov</code>.",
                 "❌ Invalid username. Send a public @username like <code>@durov</code>.")
    res = await tg.get_chat("@" + u)
    if not res.get("ok"):
        return T(lang,
                 "❌ لم أجد قناة/مجموعة/بوت عام بهذا الاسم.\n\n<i>ملاحظة: بيانات الحسابات الشخصية الخاصة (الرقم، الموقع) لا يمكن كشفها — هذا حماية للخصوصية وقانوني.</i>",
                 "❌ No public channel/group/bot found.\n\n<i>Note: private personal account data (phone, location) cannot be revealed — that's privacy protection and the law.</i>")
    c = res["result"]
    ctype = c.get("type", "")
    name = c.get("title") or (" ".join(filter(None, [c.get("first_name"), c.get("last_name")]))) or "—"
    count = None
    if ctype in ("channel", "group", "supergroup"):
        cc = await tg.get_chat_member_count("@" + u)
        if cc.get("ok"):
            count = cc["result"]
    type_map = {"channel": T(lang, "قناة", "Channel"), "supergroup": T(lang, "مجموعة عملاقة", "Supergroup"),
                "group": T(lang, "مجموعة", "Group"), "private": T(lang, "حساب/بوت", "Account/Bot"),
                "bot": T(lang, "بوت", "Bot")}
    title = T(lang, "🔎 <b>معلومات كيان تليجرام العام</b>", "🔎 <b>Public Telegram Entity Info</b>")
    lines = [title, "",
             f"{T(lang,'الاسم','Name')}: <b>{esc(name)}</b>",
             f"{T(lang,'المعرّف','Username')}: <code>@{esc(u)}</code>",
             f"{T(lang,'النوع','Type')}: {type_map.get(ctype, esc(ctype))}",
             f"{T(lang,'الرقم التعريفي','ID')}: <code>{esc(c.get('id'))}</code>"]
    if count is not None:
        lines.append(f"{T(lang,'عدد الأعضاء','Members')}: <code>{count:,}</code>")
    bio = c.get("description") or c.get("bio")
    if bio:
        lines.append(f"\n{T(lang,'الوصف','Description')}:\n{esc(bio[:400])}")
    if c.get("has_private_forwards") is not None or ctype == "private":
        lines.append("\n<i>" + T(lang, "الحسابات الشخصية تُظهر فقط ما يجعله المستخدم عاماً.",
                                  "Personal accounts show only what the user makes public.") + "</i>")
    return "\n".join(lines)


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
    "urlmal":   (osint.url_malware_scan, "🛡️ أرسل الرابط لفحص إن كان خبيثاً/احتيالياً", "🛡️ Send a URL to scan for malicious/phishing", True),
    "emailval": (osint.email_validate,  "✅ أرسل البريد للتحقق من صحته", "✅ Send an email to verify", True),
    "teleinfo": (telegram_public_info,  "🔎 أرسل يوزر قناة/بوت عام (مثال: @telegram)", "🔎 Send a public channel/bot @username (e.g. @telegram)", True),
    "dorks":    (osint.google_dorks,    "🧰 أرسل نطاقاً لتوليد استعلامات Google Dorks", "🧰 Send a domain to generate Google Dorks", True),
    "hashgen":  (osint.hash_generate,   "🔐 أرسل نصاً لتوليد بصماته", "🔐 Send text to generate hashes", False),
    "hashid":   (osint.hash_identify,   "🧩 أرسل البصمة لتحديد نوعها", "🧩 Send a hash to identify its type", False),
    "b64":      (osint.base64_tool,     "🔁 أرسل نصاً للترميز/فك الترميز Base64", "🔁 Send text to Base64 encode/decode", False),
    "genpass":  (osint.password_generator, "🔑 أرسل الطول المطلوب (8-64) أو أرسل أي شيء لطول 16", "🔑 Send desired length (8-64) or anything for length 16", False),
}


# ---------- keyboards ----------
def kb_main(lang, user=None):
    rows = [
        [{"text": T(lang, "🛰️ أدوات OSINT", "🛰️ OSINT Tools"), "callback_data": "menu:osint"}],
        [{"text": T(lang, "🎓 أكاديمية الاختراق الأخلاقي", "🎓 Ethical Hacking Academy"), "callback_data": "menu:academy"}],
        [{"text": T(lang, "💻 تعلّم البرمجة", "💻 Learn to Code"), "callback_data": "menu:courses"}],
        [{"text": T(lang, "📖 شرح الميزات", "📖 Feature Guide"), "callback_data": "menu:guide"}],
        [{"text": T(lang, "🌐 English", "🌐 العربية"), "callback_data": "lang:toggle"}],
    ]
    if (user and user.get("telegram_id") == ADMIN_ID) or (user and user.get("is_admin")):
        rows.insert(-1, [{"text": T(lang, "🛠️ لوحة تحكم الأدمن", "🛠️ Admin Panel"), "callback_data": "adm:panel"}])
    return rows


def kb_osint(lang):
    rows = [
        [{"text": T(lang, "🌐 معلومات IP", "🌐 IP Lookup"), "callback_data": "tool:ip"},
         {"text": T(lang, "📞 تحليل رقم", "📞 Phone Lookup"), "callback_data": "tool:phone"}],
        [{"text": T(lang, "🔎 WHOIS نطاق", "🔎 Domain WHOIS"), "callback_data": "tool:domain"},
         {"text": T(lang, "🧭 سجلات DNS", "🧭 DNS Records"), "callback_data": "tool:dns"}],
        [{"text": T(lang, "📧 فحص تسريب بريد", "📧 Email Breach"), "callback_data": "tool:email"},
         {"text": T(lang, "🔑 كلمة مرور مسرّبة", "🔑 Pwned Password"), "callback_data": "tool:pwd"}],
        [{"text": T(lang, "🕵️ بحث اسم مستخدم", "🕵️ Username Search"), "callback_data": "tool:user"},
         {"text": T(lang, "🛡️ فاحص روابط خبيثة", "🛡️ Malicious URL"), "callback_data": "tool:urlmal"}],
        [{"text": T(lang, "🔗 تحليل رابط", "🔗 URL Analysis"), "callback_data": "tool:url"},
         {"text": T(lang, "✅ تحقق بريد", "✅ Email Verify"), "callback_data": "tool:emailval"}],
        [{"text": T(lang, "🔎 معلومات كيان تليجرام", "🔎 Telegram Entity"), "callback_data": "tool:teleinfo"},
         {"text": T(lang, "🧰 Google Dorks", "🧰 Google Dorks"), "callback_data": "tool:dorks"}],
        [{"text": T(lang, "📍 مشاركة موقع (بموافقة)", "📍 Location Share (consent)"), "callback_data": "tool:loc"}],
        [{"text": T(lang, "🔐 مولّد Hash", "🔐 Hash Gen"), "callback_data": "tool:hashgen"},
         {"text": T(lang, "🧩 تحديد Hash", "🧩 Hash ID"), "callback_data": "tool:hashid"}],
        [{"text": T(lang, "🔁 Base64", "🔁 Base64"), "callback_data": "tool:b64"},
         {"text": T(lang, "🔑 مولّد كلمة مرور", "🔑 Password Gen"), "callback_data": "tool:genpass"}],
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
def main_text(lang, user=None):
    if lang == "ar":
        return (
            "🛡️ <b>CYBER OSINT SUITE</b>\n"
            "<i>منصّتك الاحترافية للأمن السيبراني وجمع المعلومات القانوني</i>\n\n"
            "اختر من القائمة:\n"
            "• 🛰️ أدوات OSINT من مصادر عامة\n"
            "• 🎓 أكاديمية اختراق أخلاقي\n"
            "• 💻 تعلّم البرمجة\n"
            "• 📖 شرح الميزات"
        )
    return (
        "🛡️ <b>CYBER OSINT SUITE</b>\n"
        "<i>Your professional legal cybersecurity & OSINT platform</i>\n\n"
        "Pick from the menu:\n"
        "• 🛰️ OSINT tools from public sources\n"
        "• 🎓 Ethical hacking academy\n"
        "• 💻 Learn to code\n"
        "• 📖 Feature Guide"
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


def kb_account(lang):
    return [
        [{"text": T(lang, "🎁 مكافأة يومية (+10)", "🎁 Daily bonus (+10)"), "callback_data": "acct:bonus"}],
        [{"text": T(lang, "💎 ترقية باقتي", "💎 Upgrade plan"), "callback_data": "menu:upgrade"}],
        [{"text": T(lang, "⬅️ رجوع", "⬅️ Back"), "callback_data": "menu:main"}],
    ]


# ---------- multi-channel sequential forced subscription gate ----------
async def get_forced_channels() -> list:
    cfg = await get_config()
    channels = cfg.get("forced_channels")
    if isinstance(channels, list):
        return [c for c in channels if c]
    single = cfg.get("forced_channel")
    if single:
        return [single]
    return []


async def get_next_unjoined_channel(chat_id):
    """Returns (channel_str, current_step, total_channels) or None if all are joined."""
    u = await db.users.find_one({"telegram_id": chat_id})
    if chat_id == ADMIN_ID or (u and u.get("is_admin")):
        return None
    channels = await get_forced_channels()
    if not channels:
        return None
    for idx, ch in enumerate(channels, 1):
        try:
            res = await tg.get_chat_member(ch, chat_id)
            if res.get("ok"):
                status = res["result"]["status"]
                if status in ("left", "kicked"):
                    return (ch, idx, len(channels))
            else:
                # If bot is not admin or cannot verify, don't trap the user, continue checking others
                continue
        except Exception:
            continue
    return None


async def is_member(chat_id) -> bool:
    next_ch = await get_next_unjoined_channel(chat_id)
    return next_ch is None


async def send_join(chat_id, lang, next_ch=None, edit=None):
    if not next_ch:
        next_ch = await get_next_unjoined_channel(chat_id)
    if not next_ch:
        return
    ch, step, total = next_ch
    clean_ch = ch.lstrip("@")
    if clean_ch.startswith("https://") or clean_ch.startswith("http://"):
        link = clean_ch
        display_name = clean_ch
    else:
        link = f"https://t.me/{clean_ch}"
        display_name = f"@{clean_ch}"

    if step > 1:
        text = T(lang,
                 f"🎉 <b>أحسنت!</b>\n\nيرجى الآن الاشتراك في القناة التالية [{step}/{total}]:\n👉 <b>{esc(display_name)}</b>\n\nاضغط على الزر أدناه للاشتراك ثم اضغط «✅ تحقّقت».",
                 f"🎉 <b>Great job!</b>\n\nPlease now join the next channel [{step}/{total}]:\n👉 <b>{esc(display_name)}</b>\n\nTap to join then tap “✅ I've joined”.")
    else:
        text = T(lang,
                 f"🔒 <b>الاشتراك الإجباري مطلوب</b>\n\nللاستمرار في استخدام البوت، اشترك في القناة [{step}/{total}]:\n👉 <b>{esc(display_name)}</b>\n\nبعد الاشتراك اضغط «✅ تحقّقت» للمتابعة.",
                 f"🔒 <b>Subscription required</b>\n\nTo continue using the bot, join channel [{step}/{total}]:\n👉 <b>{esc(display_name)}</b>\n\nAfter joining, tap “✅ I've joined” to proceed.")

    kb = [
        [{"text": T(lang, f"📢 اشترك في {display_name}", f"📢 Join {display_name}"), "url": link}],
        [{"text": T(lang, "✅ تحقّقت", "✅ I've joined"), "callback_data": "check:sub"}]
    ]
    if edit:
        await edit(text, kb)
    else:
        await tg.send_message(chat_id, text, kb)


# ---------- feature guide ----------
def kb_guide(lang):
    return [
        [{"text": T(lang, "🛰️ شرح أدوات OSINT", "🛰️ OSINT tools guide"), "callback_data": "guide:osint"}],
        [{"text": T(lang, "🎓 شرح التعلّم و CTF", "🎓 Learning & CTF guide"), "callback_data": "guide:learn"}],
        [{"text": T(lang, "💎 الاشتراكات والنقاط", "💎 Plans & points"), "callback_data": "guide:plans"}],
        [{"text": T(lang, "⬅️ رجوع", "⬅️ Back"), "callback_data": "menu:main"}],
    ]


def guide_text(lang, sec):
    if sec == "osint":
        if lang == "ar":
            return (
                "🛰️ <b>دليل أدوات OSINT — ماذا تفعل وكيف تستخدمها</b>\n\n"
                "🌐 <b>معلومات IP</b>: تعرف الدولة والمدينة ومزود الخدمة لأي عنوان IP. الاستخدام: اضغط الأداة وأرسل IP مثل <code>8.8.8.8</code>.\n\n"
                "📞 <b>تحليل رقم</b>: يكشف الدولة والشركة ونوع الخط والتوقيت. أرسل الرقم مع رمز الدولة <code>+9647...</code>. (اسم صاحب الرقم غير متاح قانونياً).\n\n"
                "🔎 <b>WHOIS نطاق</b>: مالك النطاق وتاريخ تسجيله وانتهائه. أرسل <code>example.com</code>.\n\n"
                "🧭 <b>سجلات DNS</b>: عناوين الخوادم وسجلات البريد. أرسل النطاق.\n\n"
                "📧 <b>فحص تسريب بريد</b>: هل ظهر بريدك في تسريبات؟ وما البيانات المكشوفة. أرسل الإيميل. (للدفاع: افحص بريدك أنت).\n\n"
                "🔑 <b>كلمة مرور مسرّبة</b>: كم مرة ظهرت كلمتك في التسريبات. لا نخزّنها إطلاقاً.\n\n"
                "🕵️ <b>بحث اسم مستخدم</b>: يبحث عن اليوزر عبر 12 منصة. أرسل اسم المستخدم.\n\n"
                "🛡️ <b>فاحص روابط خبيثة</b>: يكشف روابط التصيّد والاحتيال قبل ما تفتحها. أرسل الرابط.\n\n"
                "🔗 <b>تحليل رابط</b>: حالة الموقع، الخادم، رؤوس الأمان. أرسل الرابط.\n\n"
                "🔎 <b>معلومات كيان تليجرام</b>: معلومات قناة/بوت/مجموعة عامة. أرسل اليوزر العام <code>@telegram</code>.\n\n"
                "🧰 <b>Google Dorks</b>: يولّد استعلامات بحث متقدمة لأي نطاق. أرسل النطاق.\n\n"
                "📍 <b>مشاركة موقع بموافقة</b>: يعطيك رابطاً ترسله لشخص، وإذا وافق يصلك موقعه. شفّاف وقانوني.\n\n"
                "🔐 <b>Hash / Base64 / مولّد كلمة مرور</b>: أدوات تشفير وترميز وتوليد كلمات مرور قوية."
            )
        return (
            "🛰️ <b>OSINT Tools Guide — what each does & how to use</b>\n\n"
            "🌐 <b>IP Lookup</b>: country, city, ISP of any IP. Tap it and send an IP like <code>8.8.8.8</code>.\n\n"
            "📞 <b>Phone Analysis</b>: country, carrier, line type, timezone. Send with country code <code>+1...</code>. (Owner name is not legally available).\n\n"
            "🔎 <b>Domain WHOIS</b>: owner, registration & expiry dates. Send <code>example.com</code>.\n\n"
            "🧭 <b>DNS Records</b>: server addresses and mail records. Send a domain.\n\n"
            "📧 <b>Email Breach</b>: was your email leaked, and what data was exposed. Send an email (defensive: check your own).\n\n"
            "🔑 <b>Pwned Password</b>: how many times your password appeared in breaches. Never stored.\n\n"
            "🕵️ <b>Username Search</b>: searches a username across 12 platforms.\n\n"
            "🛡️ <b>Malicious URL</b>: detects phishing/scam links before you open them.\n\n"
            "🔗 <b>URL Analysis</b>: site status, server, security headers.\n\n"
            "🔎 <b>Telegram Entity</b>: info about a public channel/bot/group. Send <code>@telegram</code>.\n\n"
            "🧰 <b>Google Dorks</b>: generates advanced search queries for a domain.\n\n"
            "📍 <b>Consent Location</b>: gives you a link to send someone; if they agree, you receive their location.\n\n"
            "🔐 <b>Hash / Base64 / Password Gen</b>: encoding & strong-password utilities."
        )
    if sec == "learn":
        return T(lang,
            "🎓 <b>دليل التعلّم و CTF</b>\n\n"
            "🎓 <b>الأكاديمية</b>: 5 مسارات (استطلاع، ويب، شبكات، تشفير، لينكس). اضغط المسار لقراءة دروسه الطويلة المبسّطة.\n\n"
            "💻 <b>تعلّم البرمجة</b>: دورات بايثون (من الصفر للاحتراف)، جافاسكربت، Bash، وأمن سيبراني.\n\n"
            "🚩 <b>تحديات CTF</b>: حل اللغز ثم اضغط «إرسال العلم» وأرسل الإجابة بصيغة <code>FLAG{...}</code> لتكسب النقاط.\n\n"
            "🏆 <b>المتصدّرون</b>: ترتيب أعلى اللاعبين نقاطاً. النقاط تجيك من حل التحديات والإحالات والمكافأة اليومية.",
            "🎓 <b>Learning & CTF Guide</b>\n\n"
            "🎓 <b>Academy</b>: 5 tracks (recon, web, networking, crypto, Linux). Tap a track to read its long, simple lessons.\n\n"
            "💻 <b>Learn to Code</b>: Python (zero to pro), JavaScript, Bash, and cybersecurity courses.\n\n"
            "🚩 <b>CTF</b>: solve the puzzle, tap 'Submit flag', and send the answer as <code>FLAG{...}</code> to earn points.\n\n"
            "🏆 <b>Leaderboard</b>: top players by points. Earn points from challenges, referrals, and the daily bonus.")
    return T(lang,
        "💎 <b>الاشتراكات والنقاط</b>\n\n"
        "<b>الباقات</b>: FREE (8 عمليات/يوم)، PRO (150/يوم + كل الدروس)، ELITE (غير محدود).\n"
        "للاشتراك: القائمة ← 💎 ترقية ← اختر الباقة ← ادفع بأمان عبر Stripe. تُفعَّل باقتك تلقائياً.\n\n"
        "<b>النقاط</b> 🏅: تكسبها من حل تحديات CTF (50-120 نقطة)، ومن دعوة الأصدقاء (25 نقطة/صديق)، ومن المكافأة اليومية (10 نقاط).\n\n"
        "<b>الإحالة</b>: افتح «حسابي» وانسخ رابط الإحالة الخاص بك وشاركه.",
        "💎 <b>Plans & Points</b>\n\n"
        "<b>Plans</b>: FREE (8 scans/day), PRO (150/day + all lessons), ELITE (unlimited).\n"
        "To subscribe: Menu → 💎 Upgrade → pick a plan → pay via Stripe. Your plan activates automatically.\n\n"
        "<b>Points</b> 🏅: earn from CTF challenges (50-120 pts), inviting friends (25 pts each), and the daily bonus (10 pts).\n\n"
        "<b>Referral</b>: open 'My Account' and share your referral link.")


# ---------- admin panel ----------
def kb_admin(lang):
    return [
        [{"text": T(lang, "📊 الإحصائيات", "📊 Statistics"), "callback_data": "adm:stats"}],
        [{"text": T(lang, "📢 بثّ رسالة للجميع", "📢 Broadcast"), "callback_data": "adm:broadcast"}],
        [{"text": T(lang, "⬆️ ترقية مستخدم", "⬆️ Upgrade a user"), "callback_data": "adm:upgrade"}],
        [{"text": T(lang, "🔒 الاشتراك الإجباري", "🔒 Forced subscription"), "callback_data": "adm:sub"}],
        [{"text": T(lang, "⬅️ رجوع", "⬅️ Back"), "callback_data": "menu:main"}],
    ]


async def admin_panel(edit, lang):
    txt = T(lang,
            "🛠️ <b>لوحة تحكم الأدمن</b>\n\nاختر إجراءً:\n"
            "• 📊 الإحصائيات: أرقام المستخدمين والاشتراكات والإيرادات.\n"
            "• 📢 البثّ: أرسل رسالة لكل المستخدمين دفعة واحدة.\n"
            "• ⬆️ ترقية مستخدم: فعّل باقة لأي مستخدم يدوياً.\n"
            "• 🔒 الاشتراك الإجباري: إدارة قنوات ومجموعات الاشتراك الإجباري بالتتابع.",
            "🛠️ <b>Admin Panel</b>\n\nPick an action:\n"
            "• 📊 Statistics: users, subscriptions, revenue.\n"
            "• 📢 Broadcast: message all users at once.\n"
            "• ⬆️ Upgrade a user: manually grant a plan.\n"
            "• 🔒 Forced subscription: manage sequential required channels/groups.")
    await edit(txt, kb_admin(lang))


async def show_admin_sub_panel(edit, lang):
    channels = await get_forced_channels()
    if channels:
        ch_list = "\n".join([f"{i}. <code>{esc(ch)}</code>" for i, ch in enumerate(channels, 1)])
        text = T(lang,
                 f"🔒 <b>إدارة قنوات ومجموعات الاشتراك الإجباري</b>\n\nالقنوات المضافة حالياً ({len(channels)}):\n{ch_list}\n\n<i>يطلب البوت من المستخدم الاشتراك فيها بالتتابع قناة تلو الأخرى حتى ينتهي منها جميعاً.</i>",
                 f"🔒 <b>Manage Forced Subscription Channels/Groups</b>\n\nCurrent channels ({len(channels)}):\n{ch_list}\n\n<i>The bot asks users to join them sequentially one after another.</i>")
        kb = [
            [{"text": T(lang, "➕ إضافة قناة / مجموعة", "➕ Add channel/group"), "callback_data": "adm:sub_add"}],
            [{"text": T(lang, "❌ حذف قناة معينة", "❌ Delete a channel"), "callback_data": "adm:sub_del"}],
            [{"text": T(lang, "🗑️ مسح كل القنوات", "🗑️ Clear all channels"), "callback_data": "adm:sub_clear"}],
            [{"text": T(lang, "⬅️ لوحة الأدمن", "⬅️ Admin Panel"), "callback_data": "adm:panel"}],
        ]
    else:
        text = T(lang,
                 "🔒 <b>إدارة قنوات الاشتراك الإجباري</b>\n\nلا توجد أي قنوات مضافة حالياً. البوت متاح للجميع بدون اشتراك إجباري.",
                 "🔒 <b>Manage Forced Subscription Channels</b>\n\nNo channels added yet. The bot is currently open to all.")
        kb = [
            [{"text": T(lang, "➕ إضافة قناة / مجموعة", "➕ Add channel/group"), "callback_data": "adm:sub_add"}],
            [{"text": T(lang, "⬅️ لوحة الأدمن", "⬅️ Admin Panel"), "callback_data": "adm:panel"}],
        ]
    await edit(text, kb)


async def show_admin_sub_del_panel(edit, lang):
    channels = await get_forced_channels()
    if not channels:
        await show_admin_sub_panel(edit, lang)
        return
    text = T(lang, "🗑️ اضغط على القناة التي تريد إزالتها من الاشتراك الإجباري:", "🗑️ Click on the channel you want to remove:")
    kb = []
    for idx, ch in enumerate(channels):
        kb.append([{"text": f"❌ {ch}", "callback_data": f"adm:sub_rm:{idx}"}])
    kb.append([{"text": T(lang, "⬅️ رجوع", "⬅️ Back"), "callback_data": "adm:sub"}])
    await edit(text, kb)


async def admin_stats_text(lang):
    users = await db.users.count_documents({})
    paid = await db.payment_transactions.count_documents({"payment_status": "paid"})
    txs = await db.payment_transactions.find({"payment_status": "paid"}, {"_id": 0, "amount": 1}).to_list(2000)
    revenue = round(sum(t.get("amount", 0) for t in txs), 2)
    scans = await db.scans.count_documents({})
    solved = await db.ctf_submissions.count_documents({"correct": True})
    all_u = await db.users.find({}, {"_id": 0}).to_list(5000)
    pro = sum(1 for u in all_u if effective_plan(u) == "pro")
    elite = sum(1 for u in all_u if effective_plan(u) == "elite")
    channels = await get_forced_channels()
    ch = ", ".join(channels) if channels else T(lang, "غير مفعّل", "off")
    return T(lang,
        f"📊 <b>الإحصائيات</b>\n\n👥 المستخدمون: <b>{users}</b>\n💎 اشتراكات مدفوعة: <b>{paid}</b> (PRO {pro} · ELITE {elite})\n💰 الإيرادات: <b>${revenue}</b>\n🔍 عمليات الفحص: <b>{scans}</b>\n🚩 تحديات محلولة: <b>{solved}</b>\n🔒 قنوات الاشتراك الإجباري ({len(channels)}): {esc(ch)}",
        f"📊 <b>Statistics</b>\n\n👥 Users: <b>{users}</b>\n💎 Paid subs: <b>{paid}</b> (PRO {pro} · ELITE {elite})\n💰 Revenue: <b>${revenue}</b>\n🔍 Scans: <b>{scans}</b>\n🚩 Solved: <b>{solved}</b>\n🔒 Forced channels ({len(channels)}): {esc(ch)}")


async def do_admin_broadcast(chat_id, lang, message):
    users = await db.users.find({}, {"_id": 0, "telegram_id": 1}).to_list(20000)
    sent = 0
    for u in users:
        try:
            res = await tg.send_message(u["telegram_id"], f"📢 {message}")
            if res.get("ok"):
                sent += 1
        except Exception:
            pass
    await db.broadcasts.insert_one({"message": message, "sent": sent, "at": now_utc().isoformat()})
    await tg.send_message(chat_id, T(lang, f"✅ تم إرسال البثّ إلى {sent} مستخدم.", f"✅ Broadcast sent to {sent} users."), kb_admin(lang))


async def do_admin_upgrade(chat_id, lang, text):
    parts = text.split()
    if len(parts) < 2 or parts[1].lower() not in ("pro", "elite", "free"):
        await tg.send_message(chat_id, T(lang,
            "❌ صيغة خاطئة. اكتب: <code>المعرّف الباقة [الأيام]</code>\nمثال: <code>123456789 pro 30</code> أو <code>@username elite 365</code>",
            "❌ Wrong format. Use: <code>id plan [days]</code>\ne.g. <code>123456789 pro 30</code> or <code>@username elite 365</code>"), kb_admin(lang))
        return
    target, plan = parts[0], parts[1].lower()
    days = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else (365 if plan == "elite" else 30)
    if target.startswith("@"):
        u = await db.users.find_one({"username": target.lstrip("@")})
        tid = u["telegram_id"] if u else None
    else:
        tid = int(target) if target.lstrip("-").isdigit() else None
    if not tid:
        await tg.send_message(chat_id, T(lang, "❌ لم أجد هذا المستخدم (لازم يكون بدأ البوت).", "❌ User not found (they must have started the bot)."), kb_admin(lang))
        return
    if plan == "free":
        await db.users.update_one({"telegram_id": tid}, {"$set": {"plan": "free", "plan_expires": None}})
    else:
        from datetime import timedelta
        exp = (now_utc() + timedelta(days=days)).isoformat()
        await db.users.update_one({"telegram_id": tid}, {"$set": {"plan": plan, "plan_expires": exp}})
        try:
            await tg.send_message(tid, T(lang, f"🎉 تمت ترقيتك إلى <b>{plan.upper()}</b> لمدة {days} يوم!", f"🎉 You were upgraded to <b>{plan.upper()}</b> for {days} days!"))
        except Exception:
            pass
    await tg.send_message(chat_id, T(lang, f"✅ تم ضبط باقة المستخدم {tid} إلى {plan.upper()}.", f"✅ User {tid} set to {plan.upper()}."), kb_admin(lang))


# ---------- update handling ----------
async def handle_update(update: dict):
    if "callback_query" in update:
        await _handle_callback(update["callback_query"])
    elif "message" in update:
        await _handle_message(update["message"])


async def _handle_message(msg):
    # Only interact in private 1-on-1 chat with the bot
    # Stay 100% silent in channels and groups when added as admin
    chat_type = msg.get("chat", {}).get("type", "private")
    if chat_type != "private":
        return

    if "text" not in msg:
        return
    tg_user = msg.get("from")
    if not tg_user or tg_user.get("is_bot"):
        return
    chat_id = msg["chat"]["id"]
    text = msg["text"].strip()

    # Automatically remove residual reply keyboards from previous bot runs/sessions on /start
    if text.startswith("/start"):
        try:
            sent = await tg._call("sendMessage", {
                "chat_id": chat_id,
                "text": "⚡",
                "reply_markup": {"remove_keyboard": True}
            })
            if sent.get("ok"):
                await tg._call("deleteMessage", {
                    "chat_id": chat_id,
                    "message_id": sent["result"]["message_id"]
                })
        except Exception:
            pass

    referred_by = None
    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        if len(parts) > 1 and parts[1].strip().isdigit():
            referred_by = int(parts[1].strip())
    user = await get_or_create_user(tg_user, referred_by)
    lang = user.get("lang", "ar")
    state = user.get("state") or ""

    # ---- admin login / panel trigger ----
    is_admin_cmd = text.startswith("/admin") or (ADMIN_TRIGGER and text.strip().lower() in (ADMIN_TRIGGER.lower(), f"/{ADMIN_TRIGGER.lower()}", "admin", "/admin"))
    if is_admin_cmd:
        if chat_id == ADMIN_ID or user.get("is_admin"):
            await db.users.update_one({"telegram_id": chat_id}, {"$set": {"is_admin": True}})
            user["is_admin"] = True
            await set_state(chat_id, None)
            await tg.send_message(chat_id, T(lang, "🛠️ أهلاً بك يا أدمن! هذه لوحة التحكم:", "🛠️ Welcome Admin! Here is your panel:"), kb_admin(lang))
            return
        elif ADMIN_PASSWORD and text.strip() == ADMIN_PASSWORD:
            await db.users.update_one({"telegram_id": chat_id}, {"$set": {"is_admin": True}})
            user["is_admin"] = True
            await set_state(chat_id, None)
            await tg.send_message(chat_id, T(lang, "✅ تم تسجيل دخولك بنجاح! هذه لوحة التحكم:", "✅ Logged in successfully! Here is your admin panel:"), kb_admin(lang))
            return
        else:
            await set_state(chat_id, "await:adminpass")
            await tg.send_message(chat_id, T(lang, "🔐 أدخل كلمة سر لوحة التحكم:", "🔐 Enter the admin password:"))
            return
    if state == "await:adminpass":
        await set_state(chat_id, None)
        if (chat_id == ADMIN_ID) or (ADMIN_PASSWORD and text.strip() == ADMIN_PASSWORD):
            await db.users.update_one({"telegram_id": chat_id}, {"$set": {"is_admin": True}})
            user["is_admin"] = True
            await tg.send_message(chat_id, T(lang, "✅ تم تسجيل دخولك بنجاح! هذه لوحة التحكم:", "✅ Logged in successfully! Here is your admin panel:"), kb_admin(lang))
        else:
            await tg.send_message(chat_id, T(lang, "❌ كلمة سر خاطئة. لا يمكنك الدخول.", "❌ Wrong password. Access denied."))
        return
    if state == "await:adminbroadcast" and user.get("is_admin"):
        await set_state(chat_id, None)
        await do_admin_broadcast(chat_id, lang, text)
        return
    if state == "await:adminupgrade" and user.get("is_admin"):
        await set_state(chat_id, None)
        await do_admin_upgrade(chat_id, lang, text)
        return
    if state == "await:adminaddchannel" and (chat_id == ADMIN_ID or user.get("is_admin")):
        await set_state(chat_id, None)
        raw = text.strip()
        if "t.me/" in raw:
            raw = raw.split("t.me/")[-1].split("/")[0].split("?")[0]
        if not raw.startswith("@") and not raw.startswith("-100") and not raw.isdigit():
            ch = "@" + raw
        else:
            ch = raw

        channels = await get_forced_channels()
        if ch not in channels:
            channels.append(ch)
            await set_config("forced_channels", channels)
            await set_config("forced_channel", channels[0])
            msg_ok = T(lang,
                f"✅ تم إضافة القناة/المجموعة بنجاح:\n<b>{esc(ch)}</b>\n\nإجمالي القنوات المطلوبة الآن: <b>{len(channels)}</b>\n⚠️ تأكد من رفع البوت كمشرف (Admin) فيها حتى يتمكن من التحقق من اشتراك الأعضاء.",
                f"✅ Channel/group added successfully:\n<b>{esc(ch)}</b>\n\nTotal forced channels: <b>{len(channels)}</b>\n⚠️ Make sure the bot is an Admin in it.")
        else:
            msg_ok = T(lang, f"ℹ️ القناة موجودة مسبقاً في القائمة:\n<b>{esc(ch)}</b>", f"ℹ️ Channel already exists in the list:\n<b>{esc(ch)}</b>")

        await tg.send_message(chat_id, msg_ok, [
            [{"text": T(lang, "➕ إضافة قناة أخرى", "➕ Add another"), "callback_data": "adm:sub_add"}],
            [{"text": T(lang, "📋 عرض القنوات", "📋 View channels"), "callback_data": "adm:sub"}],
            [{"text": T(lang, "⬅️ لوحة الأدمن", "⬅️ Admin Panel"), "callback_data": "adm:panel"}]
        ])
        return

    if state == "await:adminsetchannel" and (chat_id == ADMIN_ID or user.get("is_admin")):
        await set_state(chat_id, None)
        ch = text.strip()
        if ch.lower() in ("off", "الغاء", "إلغاء", "-"):
            await set_config("forced_channels", [])
            await set_config("forced_channel", None)
            await tg.send_message(chat_id, T(lang, "✅ تم إيقاف الاشتراك الإجباري ومسح جميع القنوات.", "✅ Forced subscription disabled."), kb_admin(lang))
        else:
            ch = "@" + ch.lstrip("@")
            await set_config("forced_channels", [ch])
            await set_config("forced_channel", ch)
            await tg.send_message(chat_id, T(lang,
                f"✅ تم تفعيل الاشتراك الإجباري على {ch}.\n⚠️ تأكد أن البوت أدمن في القناة حتى يتحقق من الاشتراك.",
                f"✅ Forced subscription set to {ch}.\n⚠️ Make sure the bot is an admin in that channel so it can verify membership."), kb_admin(lang))
        return

    # ---- forced subscription gate (non-admin) ----
    if not text.startswith("/start") and not await is_member(chat_id):
        await send_join(chat_id, lang)
        return

    if text.startswith("/start") or text.startswith("/menu"):
        await set_state(chat_id, None)
        if not await is_member(chat_id):
            await send_join(chat_id, lang)
            return
        await tg.send_message(chat_id, main_text(lang, user), kb_main(lang, user))
        return
    if text.startswith("/help"):
        await tg.send_message(chat_id, T(lang,
            "الأوامر:\n/start القائمة\n/menu القائمة\n/me حسابي\n/lang تغيير اللغة",
            "Commands:\n/start menu\n/menu menu\n/me account\n/lang change language"), kb_main(lang, user))
        return
    if text.startswith("/me"):
        await tg.send_message(chat_id, await account_text(lang, chat_id), kb_account(lang))
        return
    if text.startswith("/lang"):
        new = "en" if lang == "ar" else "ar"
        await set_lang(chat_id, new)
        u = await db.users.find_one({"telegram_id": chat_id})
        await tg.send_message(chat_id, main_text(new, u), kb_main(new, u))
        return

    # stateful input
    if state.startswith("await:"):
        key = state.split(":", 1)[1]
        await set_state(chat_id, None)
        await _run_tool(chat_id, lang, key, text)
        return
    if state.startswith("ctfflag:"):
        cid = state.split(":", 1)[1]
        await set_state(chat_id, None)
        await _check_flag(chat_id, lang, cid, text)
        return

    # default
    await tg.send_message(chat_id, T(lang, "استخدم /menu لفتح القائمة 👇", "Use /menu to open the menu 👇"), kb_main(lang, user))


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
    async def edit(text, kb):
        await tg.edit_message(chat_id, message_id, text, kb)

    if data == "check:sub":
        next_ch = await get_next_unjoined_channel(chat_id)
        if not next_ch:
            await tg.answer_callback(cq["id"], T(lang, "✅ تم التحقق بنجاح! أهلاً بك.", "✅ Verified successfully! Welcome."))
            await set_state(chat_id, None)
            await edit(main_text(lang, user), kb_main(lang, user))
        else:
            ch, step, total = next_ch
            await tg.answer_callback(cq["id"], T(lang, f"⚠️ لم تشترك بعد في القناة [{step}/{total}]!\nاشترك أولاً ثم اضغط تحقّقت.", f"⚠️ Not joined channel [{step}/{total}] yet!\nPlease join first then verify."), show_alert=True)
            try:
                await send_join(chat_id, lang, next_ch=next_ch, edit=edit)
            except Exception:
                pass
        return

    await tg.answer_callback(cq["id"])

    if not data.startswith("adm:") and not user.get("is_admin") and not await is_member(chat_id):
        await send_join(chat_id, lang)
        return

    if data == "menu:main":
        await set_state(chat_id, None)
        await edit(main_text(lang, user), kb_main(lang, user))
    elif data == "lang:toggle":
        new = "en" if lang == "ar" else "ar"
        await set_lang(chat_id, new)
        u = await db.users.find_one({"telegram_id": chat_id})
        await edit(main_text(new, u), kb_main(new, u))
    elif data == "menu:osint":
        await edit(osint_text(lang), kb_osint(lang))
    elif data == "menu:academy":
        await edit(T(lang, "🎓 <b>أكاديمية الاختراق الأخلاقي</b>\nاختر مساراً:", "🎓 <b>Ethical Hacking Academy</b>\nChoose a track:"), kb_academy(lang))
    elif data == "menu:courses":
        await edit(T(lang, "💻 <b>تعلّم البرمجة</b>\nاختر دورة:", "💻 <b>Learn to Code</b>\nChoose a course:"), kb_courses(lang))
    elif data == "menu:ctf":
        await edit(T(lang, "🚩 <b>تحديات CTF</b>\nحل التحدي وأرسل العلم لتكسب النقاط:", "🚩 <b>CTF Challenges</b>\nSolve and submit the flag to earn points:"), kb_ctf(lang))
    elif data == "menu:account":
        await edit(await account_text(lang, chat_id), kb_account(lang))
    elif data == "menu:upgrade":
        await edit(upgrade_text(lang), kb_upgrade(lang))
    elif data == "menu:guide":
        await edit(T(lang, "📖 <b>دليل الميزات</b>\nاختر قسماً لتعرف كل ميزة وكيف تستخدمها:", "📖 <b>Feature Guide</b>\nPick a section to learn each feature and how to use it:"), kb_guide(lang))
    elif data.startswith("guide:"):
        sec = data.split(":", 1)[1]
        await edit(guide_text(lang, sec), kb_back(lang, "menu:guide"))
    elif data == "acct:bonus":
        await _daily_bonus(chat_id, lang, edit)
    elif data == "adm:panel":
        if chat_id == ADMIN_ID or user.get("is_admin"):
            await admin_panel(edit, lang)
        else:
            await tg.answer_callback(cq["id"], T(lang, "🚫 غير مصرّح", "🚫 Not authorized"))
    elif data.startswith("adm:"):
        if chat_id != ADMIN_ID and not user.get("is_admin"):
            await tg.answer_callback(cq["id"], T(lang, "🚫 غير مصرّح", "🚫 Not authorized"))
            return
        action = data.split(":", 1)[1]
        if action == "stats":
            await edit(await admin_stats_text(lang), [
                [{"text": T(lang, "🔄 تحديث الإحصائيات", "🔄 Refresh Stats"), "callback_data": "adm:stats"}],
                [{"text": T(lang, "⬅️ لوحة الأدمن", "⬅️ Admin Panel"), "callback_data": "adm:panel"}],
            ])
        elif action == "broadcast":
            await set_state(chat_id, "await:adminbroadcast")
            await edit(T(lang, "📢 أرسل نص الرسالة التي تريد بثّها لكل المستخدمين:", "📢 Send the message text to broadcast to all users:"), [
                [{"text": T(lang, "❌ إلغاء", "❌ Cancel"), "callback_data": "adm:panel"}]
            ])
        elif action == "upgrade":
            await set_state(chat_id, "await:adminupgrade")
            await edit(T(lang,
                "⬆️ أرسل: <code>المعرّف الباقة [الأيام]</code>\nمثال: <code>123456789 pro 30</code>\nأو بيوزر: <code>@username elite 365</code>",
                "⬆️ Send: <code>id plan [days]</code>\ne.g. <code>123456789 pro 30</code>\nor by username: <code>@username elite 365</code>"), [
                [{"text": T(lang, "❌ إلغاء", "❌ Cancel"), "callback_data": "adm:panel"}]
            ])
        elif action == "sub":
            await show_admin_sub_panel(edit, lang)
        elif action == "sub_add":
            await set_state(chat_id, "await:adminaddchannel")
            await edit(T(lang,
                "➕ <b>إضافة قناة أو مجموعة للاشتراك الإجباري</b>\n\nأرسل معرّف القناة (مثال: <code>@channel</code>) أو رابط القناة/المجموعة.\n\n⚠️ <b>مهم جداً:</b> تأكد من رفع البوت كمشرف (Admin) في القناة/المجموعة حتى يتمكن من التحقق من اشتراك الأعضاء.",
                "➕ <b>Add Channel or Group</b>\n\nSend channel @username (e.g. <code>@channel</code>) or link.\n\n⚠️ <b>Important:</b> Ensure the bot is an Admin in the channel/group to verify membership."), [
                [{"text": T(lang, "❌ إلغاء", "❌ Cancel"), "callback_data": "adm:sub"}]
            ])
        elif action == "sub_del":
            await show_admin_sub_del_panel(edit, lang)
        elif action == "sub_clear":
            await set_config("forced_channels", [])
            await set_config("forced_channel", None)
            await show_admin_sub_panel(edit, lang)
        elif action.startswith("sub_rm:"):
            target = action.split(":", 1)[1]
            channels = await get_forced_channels()
            if target.isdigit() and int(target) < len(channels):
                channels.pop(int(target))
            elif target in channels:
                channels.remove(target)
            await set_config("forced_channels", channels)
            await set_config("forced_channel", channels[0] if channels else None)
            await show_admin_sub_panel(edit, lang)
    elif data == "tool:loc":
        await _start_loc(chat_id, lang, edit)
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


async def _daily_bonus(chat_id, lang, edit):
    today = now_utc().strftime("%Y-%m-%d")
    u = await db.users.find_one({"telegram_id": chat_id})
    if u.get("bonus_date") == today:
        msg = T(lang, "⏳ أخذت مكافأتك اليوم. عُد غداً!", "⏳ Already claimed today. Come back tomorrow!")
    else:
        await db.users.update_one({"telegram_id": chat_id}, {"$inc": {"points": 10}, "$set": {"bonus_date": today}})
        msg = T(lang, "🎁 حصلت على 10 نقاط!", "🎁 You earned 10 points!")
    text = await account_text(lang, chat_id)
    await edit(f"{msg}\n\n{text}", kb_account(lang))


async def _start_loc(chat_id, lang, edit):
    token = secrets.token_urlsafe(9)
    await db.loc_requests.insert_one({
        "token": token, "requester_tid": chat_id, "status": "pending",
        "lat": None, "lon": None, "created_at": now_utc().isoformat(),
    })
    link = f"{PUBLIC_BASE_URL}/loc/{token}"
    if lang == "ar":
        text = (
            "📍 <b>مشاركة موقع بموافقة صريحة</b>\n\n"
            "أنشأنا لك رابطاً. أرسله لشخص <b>بعلمه</b>. عندما يفتحه سيظهر له طلب واضح: «هل تشارك موقعك؟». "
            "إذا وافق فقط، سيصلك موقعه هنا مع رابط خريطة.\n\n"
            f"🔗 <b>رابطك:</b>\n<code>{esc(link)}</code>\n\n"
            "<i>هذه أداة شفّافة وقانونية للأصدقاء واللقاءات — ليست تتبّعاً سرّياً.</i>"
        )
    else:
        text = (
            "📍 <b>Consent-based location share</b>\n\n"
            "We created a link. Send it to a person <b>who knows about it</b>. When they open it, they'll see a clear prompt: 'Share your location?'. "
            "Only if they agree, you'll receive their location here with a map link.\n\n"
            f"🔗 <b>Your link:</b>\n<code>{esc(link)}</code>\n\n"
            "<i>This is a transparent, legal tool for friends & meetups — not covert tracking.</i>"
        )
    await edit(text, kb_back(lang, "menu:osint"))


async def notify_location(requester_tid, token, lat, lon, accuracy=None):
    user = await db.users.find_one({"telegram_id": requester_tid})
    lang = (user or {}).get("lang", "ar")
    maps = f"https://www.google.com/maps?q={lat},{lon}"
    if lang == "ar":
        text = (f"📍 <b>وصل موقع مشارَك!</b>\n\nالإحداثيات: <code>{lat}, {lon}</code>\n"
                + (f"الدقة: ~{int(accuracy)}m\n" if accuracy else "")
                + f"\n🗺️ افتح الخريطة: {maps}")
    else:
        text = (f"📍 <b>A shared location arrived!</b>\n\nCoords: <code>{lat}, {lon}</code>\n"
                + (f"Accuracy: ~{int(accuracy)}m\n" if accuracy else "")
                + f"\n🗺️ Open map: {maps}")
    await tg.send_message(requester_tid, text, disable_preview=False)


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
