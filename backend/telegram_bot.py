"""Telegram bot logic: bilingual menus, OSINT tools, academy, CTF, courses, subscriptions."""
import html
import re
import secrets

from core import (
    db, tg, PLANS, LIMITS, effective_plan, get_or_create_user,
    set_state, set_lang, check_and_increment, now_utc, PUBLIC_BASE_URL,
    ADMIN_ID, SUPPORT_ID, ADMIN_PASSWORD, ADMIN_TRIGGER, get_config, set_config,
)
import osint
import content
import payments
import academy_files

BOT_USERNAME = None  # filled on startup


def esc(v):
    return html.escape(str(v))


# ---------- i18n ----------
def T(lang, ar, en):
    return ar if lang == "ar" else en


async def telegram_public_info(target: str, lang="ar") -> str:
    raw = target.strip()
    clean_id = raw.lstrip("-")
    
    # 1) If user sends a numeric ID (User ID or Channel/Group ID like -100...)
    if clean_id.isdigit():
        chat_id_num = int(raw)
        u_db = await db.users.find_one({"telegram_id": chat_id_num})
        res = await tg.get_chat(chat_id_num)
        
        if res.get("ok"):
            c = res["result"]
            ctype = c.get("type", "user")
            name = c.get("title") or (" ".join(filter(None, [c.get("first_name"), c.get("last_name")]))) or (u_db.get("first_name") if u_db else "—")
            username = c.get("username") or (u_db.get("username") if u_db else None)
            bio = c.get("bio") or c.get("description")
            cid = c.get("id", chat_id_num)
        elif u_db:
            ctype = "user"
            name = u_db.get("first_name") or "—"
            username = u_db.get("username")
            bio = None
            cid = chat_id_num
        else:
            return T(lang,
                f"❌ لم يتم العثور على معلومات للآيدي <code>{esc(raw)}</code>.\n\n💡 <i>ملاحظة: لكي يتعرف البوت على المستخدم من الآيدي، يجب أن يكون المستخدم قد تواصل مع البوت مسبقاً، أو أن يكون الآيدي لقناة أو مجموعة أو بوت عام.</i>",
                f"❌ No information found for ID <code>{esc(raw)}</code>.\n\n💡 <i>Note: The user must have started the bot, or the ID must belong to a public channel/group/bot.</i>")
        
        type_map = {"channel": T(lang, "قناة", "Channel"), "supergroup": T(lang, "مجموعة عملاقة", "Supergroup"),
                    "group": T(lang, "مجموعة", "Group"), "private": T(lang, "حساب مستخدم شخصي", "Personal User"),
                    "bot": T(lang, "بوت", "Bot"), "user": T(lang, "حساب مستخدم", "User")}
        
        count = None
        if ctype in ("channel", "group", "supergroup"):
            cc = await tg.get_chat_member_count(chat_id_num)
            if cc.get("ok"):
                count = cc["result"]

        title = T(lang, "🔎 <b>كاشف تليجرام — التعرف عبر الآيدي (ID Lookup)</b>", "🔎 <b>Telegram Intelligence — ID Lookup</b>")
        lines = [
            title, "",
            f"🆔 {T(lang, 'الآيدي الرقمي (ID)', 'Telegram ID')}: <code>{esc(cid)}</code>",
            f"👤 {T(lang, 'الاسم / العنوان', 'Name / Title')}: <b>{esc(name)}</b>",
            f"🏷️ {T(lang, 'نوع الحساب', 'Account Type')}: <b>{type_map.get(ctype, esc(ctype))}</b>"
        ]
        if username:
            lines.append(f"🔗 {T(lang, 'اليوزر المعرّف', 'Username')}: @{esc(username)}")
            lines.append(f"🌐 {T(lang, 'رابط الحساب', 'Profile Link')}: https://t.me/{esc(username)}")
        else:
            lines.append(f"🔗 {T(lang, 'اليوزر المعرّف', 'Username')}: <i>{T(lang, 'لا يوجد يوزر عام (حساب برقم فقط)', 'No public username')}</i>")
            lines.append(f"💬 {T(lang, 'رابط المراسلة المباشر', 'Direct Chat Link')}: tg://user?id={esc(cid)}")
        if count is not None:
            lines.append(f"👥 {T(lang, 'عدد الأعضاء', 'Members')}: <code>{count:,}</code>")
        if bio:
            lines.append(f"\n📝 {T(lang, 'الوصف / النبذة', 'Bio / Description')}:\n<i>{esc(bio[:400])}</i>")
        return "\n".join(lines)

    # 2) If user sends a username or t.me link
    u = raw.lstrip("@").split("/")[-1].split("?")[0]
    if not re.match(r"^[A-Za-z0-9_]{3,32}$", u):
        return T(lang,
            "❌ صيغة غير صالحة. أرسل يوزر عام مثل <code>@durov</code> أو آيدي رقمي مثل <code>6641619062</code>.",
            "❌ Invalid format. Send a public @username like <code>@durov</code> or a numeric ID like <code>6641619062</code>.")
    
    res = await tg.get_chat("@" + u)
    u_db = await db.users.find_one({"username": {"$regex": f"^{re.escape(u)}$", "$options": "i"}})
    
    if not res.get("ok") and not u_db:
        return T(lang,
            f"❌ لم أجد حساباً أو قناة أو بوتاً عاماً باليوزر <code>@{esc(u)}</code>.\nتأكد من كتابة اليوزر بشكل صحيح.",
            f"❌ No public account/channel/bot found for <code>@{esc(u)}</code>.\nMake sure the username is correct.")
    
    c = res.get("result", {}) if res.get("ok") else {}
    ctype = c.get("type") or "user"
    cid = c.get("id") or (u_db.get("telegram_id") if u_db else "—")
    name = c.get("title") or (" ".join(filter(None, [c.get("first_name"), c.get("last_name")]))) or (u_db.get("first_name") if u_db else "—")
    
    count = None
    if ctype in ("channel", "group", "supergroup"):
        cc = await tg.get_chat_member_count("@" + u)
        if cc.get("ok"):
            count = cc["result"]

    type_map = {"channel": T(lang, "قناة", "Channel"), "supergroup": T(lang, "مجموعة عملاقة", "Supergroup"),
                "group": T(lang, "مجموعة", "Group"), "private": T(lang, "حساب مستخدم شخصي", "Personal User"),
                "bot": T(lang, "بوت", "Bot"), "user": T(lang, "حساب مستخدم", "User")}
    
    title = T(lang, "🔎 <b>كاشف تليجرام — استخراج الآيدي الأصلي من اليوزر</b>", "🔎 <b>Telegram Intelligence — Extract ID from Username</b>")
    lines = [
        title, "",
        f"🆔 <b>{T(lang, 'الآيدي الأصلي (ID)', 'Original Telegram ID')}:</b> <code>{esc(cid)}</code>",
        f"👤 {T(lang, 'الاسم / العنوان', 'Name / Title')}: <b>{esc(name)}</b>",
        f"🔗 {T(lang, 'المعرّف', 'Username')}: <code>@{esc(u)}</code>",
        f"🏷️ {T(lang, 'النوع', 'Type')}: <b>{type_map.get(ctype, esc(ctype))}</b>",
        f"🌐 {T(lang, 'الرابط المباشر', 'Link')}: https://t.me/{esc(u)}"
    ]
    if count is not None:
        lines.append(f"👥 {T(lang, 'عدد الأعضاء', 'Members')}: <code>{count:,}</code>")
    bio = c.get("description") or c.get("bio")
    if bio:
        lines.append(f"\n📝 {T(lang, 'الوصف / النبذة', 'Bio / Description')}:\n<i>{esc(bio[:400])}</i>")
    return "\n".join(lines)


# ---------- tool registry ----------
# key -> (function, ar_prompt, en_prompt, counts_against_limit)
TOOLS = {
    "ip":       (osint.ip_lookup,           "🌐 أرسل عنوان IP (مثال: 8.8.8.8)", "🌐 Send an IP address (e.g. 8.8.8.8)", True),
    "phone":    (osint.phone_lookup,        "📞 أرسل رقم الهاتف مع رمز الدولة (+9647...)", "📞 Send a phone number with country code (+1...)", True),
    "domain":   (osint.domain_whois,        "🔎 أرسل اسم النطاق (مثال: google.com)", "🔎 Send a domain name (e.g. google.com)", True),
    "dns":      (osint.dns_lookup,          "🧭 أرسل اسم النطاق لجلب سجلات DNS", "🧭 Send a domain to fetch DNS records", True),
    "email":    (osint.email_breach,        "📧 أرسل البريد الإلكتروني لفحص التسريبات", "📧 Send an email to check for breaches", True),
    "pwd":      (osint.password_pwned,       "🔑 أرسل كلمة المرور للتحقق إن كانت مسرّبة (لا نخزّنها)", "🔑 Send a password to check if it's pwned (we never store it)", True),
    "user":     (osint.username_search,     "🕵️ أرسل اسم المستخدم للبحث عبر المنصات", "🕵️ Send a username to search across platforms", True),
    "url":      (osint.url_analyze,          "🔗 أرسل الرابط لتحليله", "🔗 Send a URL to analyze", True),
    "urlmal":   (osint.url_malware_scan,    "🛡️ أرسل الرابط لفحص إن كان خبيثاً/احتيالياً", "🛡️ Send a URL to scan for malicious/phishing", True),
    "emailval": (osint.email_validate,       "✅ أرسل البريد للتحقق من صحته", "✅ Send an email to verify", True),
    "teleinfo": (telegram_public_info,      "🔎 أرسل يوزر حساب/قناة/بوت (مثال: @durov) أو أرسل الآيدي الرقمي (مثال: 6641619062)", "🔎 Send a Telegram @username (e.g. @durov) or numeric ID (e.g. 6641619062)", True),
    "subdomain":(osint.subdomain_scanner,   "🌐 أرسل النطاق (مثال: example.com) لاكتشاف النطاقات الفرعية عبر سجلات SSL", "🌐 Send a domain (e.g. example.com) to discover subdomains via SSL logs", True),
    "github":   (osint.github_user_osint,   "🐙 أرسل اسم مستخدم GitHub (مثال: torvalds) لاستخراج ملفه الاستخباراتي الكامل", "🐙 Send a GitHub username (e.g. torvalds) for full OSINT intelligence", True),
    "mac":      (osint.mac_lookup,          "📟 أرسل عنوان MAC (مثال: 00:1A:2B:3C:4D:5E) للتعرف على الشركة المصنعة", "📟 Send a MAC address (e.g. 00:1A:2B:3C:4D:5E) to identify vendor", False),
    "headers":  (osint.security_headers_scan,"🛡️ أرسل رابط أو نطاق الموقع لفحص رؤوس الحماية والتقنيات (مثال: google.com)", "🛡️ Send a website URL/domain to inspect security headers and tech stack", True),
    "ports":    (osint.fast_port_scan,      "🔌 أرسل IP أو نطاق لفحص المنافذ القياسية المفتوحة (مثال: scanme.nmap.org)", "🔌 Send an IP or domain to scan open common ports", True),
    "dorks":    (osint.google_dorks,        "🧰 أرسل نطاقاً لتوليد استعلامات Google Dorks", "🧰 Send a domain to generate Google Dorks", True),
    "hashgen":  (osint.hash_generate,       "🔐 أرسل نصاً لتوليد بصماته", "🔐 Send text to generate hashes", False),
    "hashid":   (osint.hash_identify,       "🧩 أرسل البصمة لتحديد نوعها", "🧩 Send a hash to identify its type", False),
    "b64":      (osint.base64_tool,         "🔁 أرسل نصاً للترميز/فك الترميز Base64", "🔁 Send text to Base64 encode/decode", False),
    "genpass":  (osint.password_generator,  "🔑 أرسل الطول المطلوب (8-64) أو أرسل أي شيء لطول 16", "🔑 Send desired length (8-64) or anything for length 16", False),
}


# ---------- keyboards ----------
def kb_main(lang, user=None):
    rows = [
        [{"text": T(lang, "🛰️ أدوات OSINT", "🛰️ OSINT Tools"), "callback_data": "menu:osint"}],
        [{"text": T(lang, "🎓 أكاديمية الاختراق الأخلاقي", "🎓 Ethical Hacking Academy"), "callback_data": "menu:academy"}],
        [{"text": T(lang, "💻 تعلّم البرمجة", "💻 Learn to Code"), "callback_data": "menu:courses"}],
        [{"text": T(lang, "📖 شرح الميزات", "📖 Feature Guide"), "callback_data": "menu:guide"}],
        [{"text": T(lang, "💬 الدعم الفني", "💬 Technical Support"), "callback_data": "menu:support"}],
        [{"text": T(lang, "🌐 English", "🌐 العربية"), "callback_data": "lang:toggle"}],
    ]
    if (user and user.get("telegram_id") == ADMIN_ID) or (user and user.get("is_admin")):
        rows.insert(-2, [{"text": T(lang, "🛠️ لوحة تحكم الأدمن", "🛠️ Admin Panel"), "callback_data": "adm:panel"}])
    return rows


def kb_osint(lang):
    rows = [
        [{"text": T(lang, "🌐 معلومات IP", "🌐 IP Lookup"), "callback_data": "tool:ip"},
         {"text": T(lang, "📞 تحليل رقم", "📞 Phone Lookup"), "callback_data": "tool:phone"}],
        [{"text": T(lang, "🔎 كاشف تليجرام (يوزر/آيدي)", "🔎 Telegram ID & User"), "callback_data": "tool:teleinfo"},
         {"text": T(lang, "🐙 استخبارات GitHub", "🐙 GitHub OSINT"), "callback_data": "tool:github"}],
        [{"text": T(lang, "🔎 WHOIS نطاق", "🔎 Domain WHOIS"), "callback_data": "tool:domain"},
         {"text": T(lang, "🧭 سجلات DNS", "🧭 DNS Records"), "callback_data": "tool:dns"}],
        [{"text": T(lang, "🌐 كاشف النطاقات الفرعية", "🌐 Subdomain Finder"), "callback_data": "tool:subdomain"},
         {"text": T(lang, "🔌 فاحص المنافذ المفتوحة", "🔌 Fast Port Scanner"), "callback_data": "tool:ports"}],
        [{"text": T(lang, "🛡️ فحص حماية الموقع (Headers)", "🛡️ Security Headers"), "callback_data": "tool:headers"},
         {"text": T(lang, "🛡️ فاحص روابط خبيثة", "🛡️ Malicious URL"), "callback_data": "tool:urlmal"}],
        [{"text": T(lang, "📧 فحص تسريب بريد", "📧 Email Breach"), "callback_data": "tool:email"},
         {"text": T(lang, "🔑 كلمة مرور مسرّبة", "🔑 Pwned Password"), "callback_data": "tool:pwd"}],
        [{"text": T(lang, "🕵️ بحث اسم مستخدم", "🕵️ Username Search"), "callback_data": "tool:user"},
         {"text": T(lang, "🔗 تحليل رابط", "🔗 URL Analysis"), "callback_data": "tool:url"}],
        [{"text": T(lang, "📟 كاشف جهاز MAC", "📟 MAC Vendor"), "callback_data": "tool:mac"},
         {"text": T(lang, "✅ تحقق بريد", "✅ Email Verify"), "callback_data": "tool:emailval"}],
        [{"text": T(lang, "🧰 Google Dorks", "🧰 Google Dorks"), "callback_data": "tool:dorks"},
         {"text": T(lang, "📍 مشاركة موقع (بموافقة)", "📍 Location Share (consent)"), "callback_data": "tool:loc"}],
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
            "اختر من القائمة أدناه للبدء:\n"
            "• 🛰️ أدوات OSINT من مصادر عامة\n"
            "• 🎓 أكاديمية اختراق أخلاقي\n"
            "• 💻 تعلّم البرمجة\n"
            "• 📖 شرح الميزات\n"
            "• 💬 الدعم الفني"
        )
    return (
        "🛡️ <b>CYBER OSINT SUITE</b>\n"
        "<i>Your professional legal cybersecurity & OSINT platform</i>\n\n"
        "Pick from the menu to start:\n"
        "• 🛰️ OSINT tools from public sources\n"
        "• 🎓 Ethical hacking academy\n"
        "• 💻 Learn to code\n"
        "• 📖 Feature Guide\n"
        "• 💬 Technical Support"
    )


def support_text(lang):
    if lang == "ar":
        return (
            "💬 <b>قسم الدعم الفني والمساعدة</b>\n\n"
            "إذا واجهتك أي مشكلة أو كان لديك استفسار أو اقتراح، يمكنك التواصل مع مسؤول الدعم الفني مباشرة:\n\n"
            f"👤 <b>معرّف الدعم (ID):</b> <code>{SUPPORT_ID}</code>\n\n"
            "اضغط على الزر أدناه لفتح المحادثة ومراسلة الدعم فوراً 👇"
        )
    return (
        "💬 <b>Technical Support & Help</b>\n\n"
        "If you encounter any issue, inquiry or suggestion, contact technical support directly:\n\n"
        f"👤 <b>Support ID:</b> <code>{SUPPORT_ID}</code>\n\n"
        "Tap the button below to message support directly 👇"
    )


def kb_support(lang):
    return [
        [{"text": T(lang, "💬 مراسلة الدعم الفني", "💬 Contact Support"), "url": f"tg://user?id={SUPPORT_ID}"}],
        [{"text": T(lang, "⬅️ رجوع", "⬅️ Back"), "callback_data": "menu:main"}],
    ]


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
    if not isinstance(channels, list):
        single = cfg.get("forced_channel")
        channels = [single] if single else []
    cleaned = []
    for c in channels:
        if not c:
            continue
        c = str(c).strip()
        if "t.me/" in c:
            c = c.split("t.me/")[-1].split("/")[0].split("?")[0]
        if not c.startswith("@") and not c.startswith("-"):
            c = "@" + c
        if c not in cleaned:
            cleaned.append(c)
    return cleaned


async def get_next_unjoined_channel(chat_id):
    """Returns (channel_str, current_step, total_channels) or None if all are joined."""
    try:
        u = await db.users.find_one({"telegram_id": chat_id})
    except Exception:
        u = None
    if chat_id == ADMIN_ID or (u and u.get("is_admin")):
        return None
    channels = await get_forced_channels()
    if not channels:
        return None
    for idx, ch in enumerate(channels, 1):
        try:
            res = await tg.get_chat_member(ch, chat_id)
            if res.get("ok"):
                result = res.get("result", {})
                status = result.get("status")
                # Active member statuses in Telegram Bot API:
                is_sub = False
                if status in ("creator", "administrator", "member"):
                    is_sub = True
                elif status == "restricted" and result.get("is_member", True):
                    is_sub = True
                
                # If not an active member (status is 'left', 'kicked', etc.) -> user must join
                if not is_sub:
                    return (ch, idx, len(channels))
            else:
                # Telegram returned an error
                err_desc = str(res.get("description", "")).lower()
                user_not_found_keywords = (
                    "user not found",
                    "participant_id_invalid",
                    "user_not_participant",
                    "not a participant",
                    "not a member",
                    "user is not a member",
                    "chat_member_not_found",
                )
                if any(kw in err_desc for kw in user_not_found_keywords):
                    # User is confirmed NOT in the channel / left the channel
                    return (ch, idx, len(channels))
                
                # If error is bot-related (bot is not admin, chat not found, etc.):
                # skip checking this channel so bot doesn't freeze for everyone if channel was deleted
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
    
    # Try to resolve a friendly link & title
    link = None
    display_name = None
    try:
        c_info = await tg.get_chat(ch)
        if c_info.get("ok"):
            res_c = c_info.get("result", {})
            title = res_c.get("title")
            username = res_c.get("username")
            inv = res_c.get("invite_link")
            if username:
                link = f"https://t.me/{username}"
                display_name = title or f"@{username}"
            elif inv:
                link = inv
                display_name = title or ch
    except Exception:
        pass
    
    if not link:
        clean_ch = ch.lstrip("@")
        if clean_ch.startswith("https://") or clean_ch.startswith("http://"):
            link = clean_ch
            display_name = clean_ch
        elif ch.startswith("-"):
            link = "https://t.me/"
            display_name = ch
        else:
            link = f"https://t.me/{clean_ch}"
            display_name = f"@{clean_ch}"
            
    if not display_name:
        display_name = ch

    if step > 1:
        text = T(lang,
                 f"🎉 <b>أحسنت!</b>\n\nيرجى الآن الاشتراك في القناة / المجموعة التالية [{step}/{total}]:\n👉 <b>{esc(display_name)}</b>\n\nاضغط على الزر أدناه للاشتراك ثم اضغط «✅ تحقّقت».",
                 f"🎉 <b>Great job!</b>\n\nPlease now join the next channel/group [{step}/{total}]:\n👉 <b>{esc(display_name)}</b>\n\nTap to join then tap “✅ I've joined”.")
    else:
        text = T(lang,
                 f"🔒 <b>الاشتراك الإجباري مطلوب</b>\n\nللاستمرار في استخدام البوت، يجب عليك الاشتراك أولاً في القناة / المجموعة [{step}/{total}]:\n👉 <b>{esc(display_name)}</b>\n\nبعد الاشتراك اضغط «✅ تحقّقت» للمتابعة.",
                 f"🔒 <b>Subscription required</b>\n\nTo continue using the bot, you must join channel/group [{step}/{total}]:\n👉 <b>{esc(display_name)}</b>\n\nAfter joining, tap “✅ I've joined” to proceed.")

    kb = [
        [{"text": T(lang, f"📢 اشترك في {display_name}", f"📢 Join {display_name}"), "url": link}],
        [{"text": T(lang, "✅ تحقّقت", "✅ I've joined"), "callback_data": "check:sub"}]
    ]
    if edit:
        try:
            await edit(text, kb)
            return
        except Exception:
            pass
    await tg.send_message(chat_id, text, kb)


# ---------- feature guide ----------
def kb_guide(lang):
    return [
        [{"text": T(lang, "🛰️ شرح أدوات OSINT", "🛰️ OSINT tools guide"), "callback_data": "guide:osint"}],
        [{"text": T(lang, "🎓 شرح التعلّم والكتيبات الشاملة", "🎓 Learning & Handbooks guide"), "callback_data": "guide:learn"}],
        [{"text": T(lang, "⬅️ رجوع", "⬅️ Back"), "callback_data": "menu:main"}],
    ]


def guide_text(lang, sec):
    if sec == "osint":
        if lang == "ar":
            return (
                "🛰️ <b>دليل أدوات OSINT — ماذا تفعل وكيف تستخدمها</b>\n\n"
                "🌐 <b>معلومات IP</b>: تعرف الدولة والمدينة ومزود الخدمة لأي عنوان IP. أرسل IP مثل <code>8.8.8.8</code>.\n\n"
                "📞 <b>تحليل رقم</b>: يكشف الدولة والشركة ونوع الخط والتوقيت. أرسل الرقم مع رمز الدولة <code>+9647...</code>.\n\n"
                "🔎 <b>كاشف تليجرام (يوزر/آيدي)</b>: استخراج الآيدي الأصلي لأي يوزر، أو التعرف على الحساب/القناة/المجموعة عبر الآيدي الرقمي.\n\n"
                "🐙 <b>استخبارات GitHub</b>: فحص أي حساب GitHub وكشف الاسم الحقيقي، البريد، المستودعات، والبيانات العامة.\n\n"
                "🔎 <b>WHOIS نطاق</b>: مالك النطاق وتاريخ تسجيله وانتهائه. أرسل <code>example.com</code>.\n\n"
                "🧭 <b>سجلات DNS</b>: عناوين الخوادم وسجلات البريد (A, MX, TXT). أرسل النطاق.\n\n"
                "🌐 <b>كاشف النطاقات الفرعية</b>: اكتشاف النطاقات الفرعية عبر سجلات الشهادات الرقمية العامة (crt.sh).\n\n"
                "🔌 <b>فاحص المنافذ</b>: فحص المنافذ القياسية المفتوحة وسرعة استجابة الخادم.\n\n"
                "🛡️ <b>فحص حماية الموقع (Headers)</b>: كشف برنامج الخادم، وتقييم أمان الرؤوس (HSTS, CSP, X-Frame).\n\n"
                "📧 <b>فحص تسريب بريد</b>: هل ظهر بريدك في تسريبات؟ وما البيانات المكشوفة.\n\n"
                "🔑 <b>كلمة مرور مسرّبة</b>: كم مرة ظهرت كلمتك في التسريبات. لا نخزّنها إطلاقاً.\n\n"
                "🕵️ <b>بحث اسم مستخدم</b>: يبحث عن اليوزر عبر المنصات الرقمية.\n\n"
                "🛡️ <b>فاحص روابط خبيثة</b>: يكشف روابط التصيّد والاحتيال قبل فتحها.\n\n"
                "📟 <b>كاشف جهاز MAC</b>: كشف الشركة المصنعة ونوع الجهاز عبر عنوان MAC.\n\n"
                "🧰 <b>Google Dorks</b>: يولّد استعلامات بحث متقدمة لأي نطاق.\n\n"
                "📍 <b>مشاركة موقع بموافقة</b>: رابط شفاف لمشاركة الإحداثيات بموافقة الطرف الآخر.\n\n"
                "🔐 <b>Hash / Base64 / مولّد كلمة مرور</b>: أدوات تشفير وترميز وتوليد كلمات مرور قوية."
            )
        return (
            "🛰️ <b>OSINT Tools Guide — what each does & how to use</b>\n\n"
            "🌐 <b>IP Lookup</b>: country, city, ISP of any IP.\n\n"
            "📞 <b>Phone Analysis</b>: country, carrier, line type, timezone.\n\n"
            "🔎 <b>Telegram ID & User</b>: extract original ID from username or lookup account from numeric ID.\n\n"
            "🐙 <b>GitHub OSINT</b>: full intelligence on any GitHub user (repos, email, bio).\n\n"
            "🔎 <b>Domain WHOIS</b>: owner, registrar, expiry dates.\n\n"
            "🧭 <b>DNS Records</b>: server addresses & mail records.\n\n"
            "🌐 <b>Subdomain Finder</b>: discover subdomains via SSL transparency logs.\n\n"
            "🔌 <b>Port Scanner</b>: scan common standard open ports.\n\n"
            "🛡️ <b>Security Headers</b>: inspect web server banner & protection headers.\n\n"
            "📧 <b>Email Breach</b>: check if your email was leaked.\n\n"
            "🔑 <b>Pwned Password</b>: check breach counts.\n\n"
            "🕵️ <b>Username Search</b>: multi-platform username lookup.\n\n"
            "🛡️ <b>Malicious URL</b>: detect phishing links.\n\n"
            "📟 <b>MAC Vendor</b>: identify device hardware vendor.\n\n"
            "🧰 <b>Google Dorks</b>: generate advanced search queries.\n\n"
            "🔐 <b>Hash / Base64 / Password Gen</b>: security utilities."
        )
    return T(lang,
        "🎓 <b>دليل التعلّم والكتيبات الشاملة</b>\n\n"
        "🎓 <b>أكاديمية الاختراق الأخلاقي</b>: 5 مسارات شاملة (الاستطلاع و OSINT، أمن الويب OWASP، الشبكات، التشفير، لينكس).\n"
        "بمجرد الضغط على أي مسار، يُرسل لك البوت فوراً <b>كتاباً تعليمياً كاملاً (.txt)</b> يحمل شعار ويوزر البوت <code>@Kashef4bot</code> ويشرح المسار من الصفر للاحتراف!\n\n"
        "💻 <b>تعلّم البرمجة</b>: 4 دورات عملية (بايثون السيبراني، جافاسكربت، Bash، أساسيات الدفاع السيبراني).\n"
        "كل دورة مزودة بكتيب ودليل برمجي متكامل مع أكواد عملية جاهزة للتحميل.\n\n"
        "🚩 <b>تحديات CTF</b>: تحديات تفاعلية لاختبار قدراتك في التشفير والويب والتجزئة.",
        "🎓 <b>Learning & Handbooks Guide</b>\n\n"
        "🎓 <b>Ethical Hacking Academy</b>: 5 tracks with full downloadable zero-to-hero handbooks with @Kashef4bot branding.\n\n"
        "💻 <b>Learn to Code</b>: 4 programming courses with complete downloadable books and practical codes.\n\n"
        "🚩 <b>CTF Challenges</b>: test your skills in crypto, web, and hashing.")


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
        if raw.isdigit():
            ch = "-100" + raw
        elif not raw.startswith("@") and not raw.startswith("-100"):
            ch = "@" + raw
        else:
            ch = raw

        channels = await get_forced_channels()
        if ch not in channels:
            channels.append(ch)
            await set_config("forced_channels", channels)
            await set_config("forced_channel", channels[0])
            
            # Check bot admin status in this channel
            c_test = await tg.get_chat(ch)
            title_str = ""
            admin_feedback = ""
            if c_test.get("ok"):
                title = c_test["result"].get("title")
                if title:
                    title_str = f" (<b>{esc(title)}</b>)"
                me = await tg.get_me()
                bot_id = me.get("result", {}).get("id")
                if bot_id:
                    m_check = await tg.get_chat_member(ch, bot_id)
                    if m_check.get("ok"):
                        b_status = m_check["result"].get("status")
                        if b_status not in ("administrator", "creator"):
                            admin_feedback = T(lang,
                                "\n\n⚠️ <b>تنبيه هام جداً:</b> البوت ليس مشرفاً (Admin) في هذه القناة حالياً! يرجى رفعه مشرفاً حتى يتمكن من فحص اشتراك المستخدمين بدقة.",
                                "\n\n⚠️ <b>Important Notice:</b> The bot is not an Admin in this channel yet! Please promote it to Admin.")
                        else:
                            admin_feedback = T(lang,
                                "\n\n👑 <b>تم التحقق بنجاح:</b> البوت مشرف (Admin) في القناة وجاهز لفحص اشتراك الأعضاء فوراً.",
                                "\n\n👑 <b>Verified:</b> The bot is an Admin in this channel and ready to verify members.")
                    else:
                        admin_feedback = T(lang,
                            "\n\n⚠️ <b>تنبيه:</b> يرجى التأكد من رفع البوت مشرفاً (Admin) في القناة/المجموعة.",
                            "\n\n⚠️ <b>Notice:</b> Please ensure the bot is an Admin in this channel/group.")
            else:
                admin_feedback = T(lang,
                    "\n\n⚠️ <b>تنبيه:</b> تأكد من كتابة اليوزر بشكل صحيح ورفع البوت مشرفاً (Admin) في القناة.",
                    "\n\n⚠️ <b>Notice:</b> Ensure the username is correct and the bot is an Admin.")

            msg_ok = T(lang,
                f"✅ تم إضافة القناة/المجموعة بنجاح:\n<b>{esc(ch)}</b>{title_str}\n\nإجمالي القنوات المطلوبة الآن: <b>{len(channels)}</b>{admin_feedback}",
                f"✅ Channel/group added successfully:\n<b>{esc(ch)}</b>{title_str}\n\nTotal forced channels: <b>{len(channels)}</b>{admin_feedback}")
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
    if chat_id != ADMIN_ID and not user.get("is_admin"):
        if not await is_member(chat_id):
            await set_state(chat_id, None)
            await send_join(chat_id, lang)
            return

    if text.startswith("/start") or text.startswith("/menu"):
        await set_state(chat_id, None)
        await tg.send_message(chat_id, main_text(lang, user), kb_main(lang, user))
        return
    if text.startswith("/support") or text.strip().lower() in ("دعم", "الدعم", "الدعم الفني", "support", "/support"):
        await set_state(chat_id, None)
        await tg.send_message(chat_id, support_text(lang), kb_support(lang))
        return
    if text.startswith("/help"):
        await tg.send_message(chat_id, T(lang,
            "📌 <b>الأوامر المتاحة:</b>\n/start - بدء تشغيل البوت وفتح القائمة الرئيسية\n/menu - القائمة الرئيسية\n/support - الدعم الفني والمساعدة\n/lang - تغيير اللغة",
            "📌 <b>Available Commands:</b>\n/start - Start bot & open main menu\n/menu - Main menu\n/support - Technical Support\n/lang - Change language"), kb_main(lang, user))
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

    if not data.startswith("adm:") and not user.get("is_admin") and chat_id != ADMIN_ID:
        if not await is_member(chat_id):
            await set_state(chat_id, None)
            await tg.answer_callback(cq["id"], T(lang, "⚠️ يجب عليك الاشتراك في القناة أولاً لتتمكن من استخدام البوت!", "⚠️ You must join the channel first to use the bot!"), show_alert=True)
            await send_join(chat_id, lang, edit=edit)
            return

    await tg.answer_callback(cq["id"])

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
    elif data == "menu:support":
        await edit(support_text(lang), kb_support(lang))
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
        await _show_academy_module(edit, lang, mid, chat_id)
    elif data.startswith("course:"):
        cid = data.split(":", 1)[1]
        await _show_course(edit, lang, cid, chat_id)
    elif data.startswith("doc:acad:"):
        mid = data.split(":", 2)[2]
        doc = academy_files.get_academy_doc(mid)
        if doc:
            await tg.answer_callback(cq["id"], T(lang, "⏳ جاري إرسال الكتيب الشامل...", "⏳ Sending full handbook..."))
            caption = T(lang,
                f"📚 <b>الكتيب التعليمي الكامل: {esc(doc['title'])}</b>\n\n🛡️ <i>إعداد منصة كاشف للأمن السيبراني | @Kashef4bot</i>\n📥 ملف شامل ومفصل من الصفر للاحتراف.",
                f"📚 <b>Comprehensive Handbook: {esc(doc['title'])}</b>\n\n🛡️ <i>Kashef OSINT Suite | @Kashef4bot</i>")
            await tg.send_document(chat_id, doc["filename"], doc["content"].encode("utf-8"), caption=caption)
    elif data.startswith("doc:course:"):
        cid = data.split(":", 2)[2]
        doc = academy_files.get_course_doc(cid)
        if doc:
            await tg.answer_callback(cq["id"], T(lang, "⏳ جاري إرسال الملف الشامل...", "⏳ Sending full course guide..."))
            caption = T(lang,
                f"💻 <b>الملف التعليمي الشامل: {esc(doc['title'])}</b>\n\n🛡️ <i>إعداد منصة كاشف للأمن السيبراني | @Kashef4bot</i>\n📥 ملف شامل ومفصل من الصفر للاحتراف.",
                f"💻 <b>Comprehensive Course Guide: {esc(doc['title'])}</b>\n\n🛡️ <i>Kashef OSINT Suite | @Kashef4bot</i>")
            await tg.send_document(chat_id, doc["filename"], doc["content"].encode("utf-8"), caption=caption)
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


async def _show_academy_module(edit, lang, mid, chat_id=None):
    mod = next((m for m in content.ACADEMY if m["id"] == mid), None)
    doc = academy_files.get_academy_doc(mid)
    if not mod:
        return
    title = mod["title"][lang]
    lessons_list = "\n".join([f"• <b>الفصل {i}:</b> {esc(ls['t'][lang])}" for i, ls in enumerate(mod["lessons"], 1)])
    text = T(lang,
        f"🎓 <b>{esc(title)}</b>\n\n"
        f"📑 <b>أهم محاور وفصول هذا المسار:</b>\n{lessons_list}\n\n"
        f"📄 <b>الكتيب التعليمي الشامل (.txt):</b>\n"
        f"تم إعداد كتيب كامل ومفصل يشرح هذا المسار بالتفصيل الممل من الصفر للاحتراف، يحمل شعار ويوزر البوت الرسمي <code>@Kashef4bot</code>.\n\n"
        f"🚀 <i>تم إرسال الملف كاملاً إلى محادثتك الآن لتنزيله وقراءته دون إنترنت!</i>",
        f"🎓 <b>{esc(title)}</b>\n\n"
        f"📑 <b>Track Chapters:</b>\n{lessons_list}\n\n"
        f"📄 <b>Full Educational Handbook (.txt):</b>\nA complete zero-to-mastery handbook with bot branding @Kashef4bot has been sent to your chat below!"
    )
    kb = [
        [{"text": T(lang, "📥 إعادة إرسال الكتيب الشامل 📄", "📥 Re-send Full Handbook 📄"), "callback_data": f"doc:acad:{mid}"}],
        [{"text": T(lang, "⬅️ رجوع للأكاديمية", "⬅️ Back to Academy"), "callback_data": "menu:academy"}],
    ]
    await edit(text, kb)
    if chat_id and doc:
        caption = T(lang,
            f"📚 <b>الكتيب التعليمي الكامل: {esc(doc['title'])}</b>\n\n🛡️ <i>إعداد منصة كاشف للأمن السيبراني | @Kashef4bot</i>\n📥 ملف شامل ومفصل من الصفر للاحتراف.",
            f"📚 <b>Comprehensive Handbook: {esc(doc['title'])}</b>\n\n🛡️ <i>Kashef OSINT Suite | @Kashef4bot</i>")
        try:
            await tg.send_document(chat_id, doc["filename"], doc["content"].encode("utf-8"), caption=caption)
        except Exception:
            pass


async def _show_course(edit, lang, cid, chat_id=None):
    c = next((x for x in content.COURSES if x["id"] == cid), None)
    doc = academy_files.get_course_doc(cid)
    if not c:
        return
    title = c["title"][lang]
    lessons_list = "\n".join([f"• <b>الدرس {i}:</b> {esc(ls['t'][lang])}" for i, ls in enumerate(c["lessons"], 1)])
    text = T(lang,
        f"💻 <b>{esc(title)}</b>\n\n"
        f"📑 <b>أهم محاور ودروس الدورة:</b>\n{lessons_list}\n\n"
        f"📄 <b>الكتاب والملف البرمجي الكامل (.txt):</b>\n"
        f"تم إعداد كتاب ودليل شامل ومفصل يشرح هذه اللغة والتقنية من الصفر للاحتراف مع أكواد ومشاريع أمنية كاملة، يحمل شعار ويوزر البوت الرسمي <code>@Kashef4bot</code>.\n\n"
        f"🚀 <i>تم إرسال الملف كاملاً إلى محادثتك الآن لتنزيله والتعلم منه دون إنترنت!</i>",
        f"💻 <b>{esc(title)}</b>\n\n"
        f"📑 <b>Course Lessons:</b>\n{lessons_list}\n\n"
        f"📄 <b>Full Course Book (.txt):</b>\nA comprehensive course book with bot branding @Kashef4bot has been sent to your chat below!"
    )
    kb = [
        [{"text": T(lang, "📥 إعادة إرسال الملف الكامل 📄", "📥 Re-send Full Guide 📄"), "callback_data": f"doc:course:{cid}"}],
        [{"text": T(lang, "⬅️ رجوع للدورات", "⬅️ Back to Courses"), "callback_data": "menu:courses"}],
    ]
    await edit(text, kb)
    if chat_id and doc:
        caption = T(lang,
            f"💻 <b>الملف التعليمي الشامل: {esc(doc['title'])}</b>\n\n🛡️ <i>إعداد منصة كاشف للأمن السيبراني | @Kashef4bot</i>\n📥 ملف شامل ومفصل من الصفر للاحتراف.",
            f"💻 <b>Comprehensive Course Guide: {esc(doc['title'])}</b>\n\n🛡️ <i>Kashef OSINT Suite | @Kashef4bot</i>")
        try:
            await tg.send_document(chat_id, doc["filename"], doc["content"].encode("utf-8"), caption=caption)
        except Exception:
            pass


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
