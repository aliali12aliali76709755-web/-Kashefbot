"""Legal OSINT & security utility tools. All use free/public sources or offline libs."""
import asyncio
import base64 as b64
import hashlib
import html
import re
import secrets
import string
from urllib.parse import quote_plus, urlparse

import httpx
import phonenumbers
from phonenumbers import carrier, geocoder, timezone as ph_tz

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def e(v):
    return html.escape(str(v)) if v is not None else "—"


def _t(lang, ar, en):
    return ar if lang == "ar" else en


async def ip_lookup(ip: str, lang="ar") -> str:
    ip = ip.strip()
    url = f"http://ip-api.com/json/{ip}?fields=status,message,country,regionName,city,zip,lat,lon,timezone,isp,org,as,query,mobile,proxy,hosting"
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(url)
        d = r.json()
    if d.get("status") != "success":
        return _t(lang, "❌ عنوان IP غير صالح أو غير معروف.", "❌ Invalid or unknown IP address.")
    title = _t(lang, "🌐 <b>معلومات عنوان IP</b>", "🌐 <b>IP Intelligence</b>")
    L = {
        "ip": _t(lang, "العنوان", "IP"),
        "country": _t(lang, "الدولة", "Country"),
        "region": _t(lang, "المنطقة", "Region"),
        "city": _t(lang, "المدينة", "City"),
        "isp": _t(lang, "مزود الخدمة", "ISP"),
        "org": _t(lang, "المنظمة", "Org"),
        "asn": "AS",
        "tz": _t(lang, "التوقيت", "Timezone"),
        "coords": _t(lang, "الإحداثيات", "Coords"),
        "flags": _t(lang, "تصنيفات", "Flags"),
    }
    flags = []
    if d.get("mobile"): flags.append(_t(lang, "شبكة جوال", "Mobile"))
    if d.get("proxy"): flags.append(_t(lang, "بروكسي/VPN", "Proxy/VPN"))
    if d.get("hosting"): flags.append(_t(lang, "استضافة/سحابة", "Hosting"))
    lines = [
        title, "",
        f"{L['ip']}: <code>{e(d.get('query'))}</code>",
        f"{L['country']}: {e(d.get('country'))}",
        f"{L['region']}: {e(d.get('regionName'))}",
        f"{L['city']}: {e(d.get('city'))} {e(d.get('zip'))}",
        f"{L['isp']}: {e(d.get('isp'))}",
        f"{L['org']}: {e(d.get('org'))}",
        f"{L['asn']}: <code>{e(d.get('as'))}</code>",
        f"{L['tz']}: {e(d.get('timezone'))}",
        f"{L['coords']}: <code>{e(d.get('lat'))}, {e(d.get('lon'))}</code>",
    ]
    if flags:
        lines.append(f"{L['flags']}: {', '.join(flags)}")
    return "\n".join(lines)


async def phone_lookup(number: str, lang="ar") -> str:
    number = number.strip()
    try:
        pn = phonenumbers.parse(number, None)
    except Exception:
        return _t(lang,
                  "❌ صيغة غير صحيحة. أرسل الرقم مع رمز الدولة مثال: <code>+9647701234567</code>",
                  "❌ Invalid format. Include country code, e.g. <code>+14155552671</code>")
    valid = phonenumbers.is_valid_number(pn)
    ntype = phonenumbers.number_type(pn)
    type_map = {0: "Fixed line", 1: "Mobile", 2: "Fixed/Mobile", 3: "Toll free",
                4: "Premium rate", 5: "Shared cost", 6: "VoIP", 7: "Personal",
                8: "Pager", 9: "UAN", 10: "Voicemail", 27: "Emergency", 99: "Unknown"}
    region = geocoder.description_for_number(pn, "en")
    car = carrier.name_for_number(pn, "en")
    tzs = ", ".join(ph_tz.time_zones_for_number(pn))
    title = _t(lang, "📞 <b>تحليل رقم الهاتف</b>", "📞 <b>Phone Number Analysis</b>")
    L = {
        "num": _t(lang, "الرقم الدولي", "International"),
        "valid": _t(lang, "صالح", "Valid"),
        "cc": _t(lang, "رمز الدولة", "Country code"),
        "region": _t(lang, "المنطقة", "Region"),
        "carrier": _t(lang, "شركة الاتصال", "Carrier"),
        "type": _t(lang, "النوع", "Type"),
        "tz": _t(lang, "التوقيت", "Timezone"),
    }
    yes = _t(lang, "نعم ✅", "Yes ✅")
    no = _t(lang, "لا ❌", "No ❌")
    lines = [
        title, "",
        f"{L['num']}: <code>{e(phonenumbers.format_number(pn, phonenumbers.PhoneNumberFormat.INTERNATIONAL))}</code>",
        f"{L['valid']}: {yes if valid else no}",
        f"{L['cc']}: <code>+{pn.country_code}</code>",
        f"{L['region']}: {e(region)}",
        f"{L['carrier']}: {e(car) if car else '—'}",
        f"{L['type']}: {e(type_map.get(ntype, 'Unknown'))}",
        f"{L['tz']}: {e(tzs)}",
    ]
    return "\n".join(lines)


async def dns_lookup(domain: str, lang="ar") -> str:
    domain = domain.strip().lower().replace("http://", "").replace("https://", "").split("/")[0]
    types = ["A", "AAAA", "MX", "NS", "TXT"]
    out = [_t(lang, f"🧭 <b>سجلات DNS للنطاق</b> <code>{e(domain)}</code>", f"🧭 <b>DNS records for</b> <code>{e(domain)}</code>"), ""]
    async with httpx.AsyncClient(timeout=15) as c:
        for t in types:
            try:
                r = await c.get(f"https://dns.google/resolve?name={domain}&type={t}")
                d = r.json()
                ans = d.get("Answer", [])
                vals = [a.get("data") for a in ans if a.get("type") is not None][:6]
                if vals:
                    out.append(f"<b>{t}</b>: " + ", ".join(f"<code>{e(v)}</code>" for v in vals))
            except Exception:
                continue
    if len(out) <= 2:
        return _t(lang, "❌ لم يتم العثور على سجلات أو النطاق غير صحيح.", "❌ No records found or invalid domain.")
    return "\n".join(out)


async def domain_whois(domain: str, lang="ar") -> str:
    domain = domain.strip().lower().replace("http://", "").replace("https://", "").split("/")[0]
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
            r = await c.get(f"https://rdap.org/domain/{domain}", headers={"User-Agent": UA})
            if r.status_code != 200:
                return _t(lang, "❌ لا توجد بيانات WHOIS لهذا النطاق.", "❌ No WHOIS data for this domain.")
            d = r.json()
    except Exception:
        return _t(lang, "❌ تعذّر جلب بيانات WHOIS.", "❌ Could not fetch WHOIS data.")
    events = {ev.get("eventAction"): ev.get("eventDate") for ev in d.get("events", [])}
    registrar = "—"
    for ent in d.get("entities", []):
        if "registrar" in ent.get("roles", []):
            for v in ent.get("vcardArray", [[], []])[1]:
                if v[0] == "fn":
                    registrar = v[3]
    ns = [n.get("ldhName") for n in d.get("nameservers", [])][:4]
    status = ", ".join(d.get("status", [])[:4])
    title = _t(lang, "🔎 <b>معلومات النطاق (WHOIS)</b>", "🔎 <b>Domain WHOIS</b>")
    L = {
        "dom": _t(lang, "النطاق", "Domain"),
        "reg": _t(lang, "المُسجِّل", "Registrar"),
        "created": _t(lang, "تاريخ الإنشاء", "Created"),
        "expires": _t(lang, "تاريخ الانتهاء", "Expires"),
        "updated": _t(lang, "آخر تحديث", "Updated"),
        "ns": _t(lang, "خوادم الأسماء", "Nameservers"),
        "status": _t(lang, "الحالة", "Status"),
    }
    lines = [
        title, "",
        f"{L['dom']}: <code>{e(d.get('ldhName', domain))}</code>",
        f"{L['reg']}: {e(registrar)}",
        f"{L['created']}: <code>{e(events.get('registration', '—'))}</code>",
        f"{L['expires']}: <code>{e(events.get('expiration', '—'))}</code>",
        f"{L['updated']}: <code>{e(events.get('last changed', '—'))}</code>",
        f"{L['ns']}: {', '.join('<code>'+e(n)+'</code>' for n in ns) if ns else '—'}",
        f"{L['status']}: {e(status) if status else '—'}",
    ]
    return "\n".join(lines)


async def email_breach(email: str, lang="ar") -> str:
    email = email.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return _t(lang, "❌ صيغة البريد غير صحيحة.", "❌ Invalid email format.")
    try:
        async with httpx.AsyncClient(timeout=25) as c:
            r = await c.get(f"https://api.xposedornot.com/v1/breach-analytics?email={email}",
                            headers={"User-Agent": UA})
            d = r.json()
    except Exception:
        return _t(lang, "❌ تعذّر الاتصال بخدمة الفحص.", "❌ Could not reach the breach service.")
    exposed = (((d or {}).get("ExposedBreaches") or {}).get("breaches_details")) or []
    if not exposed:
        return _t(lang,
                  f"✅ <b>بريد آمن</b>\n\n<code>{e(email)}</code>\nلم يظهر في أي تسريب معروف. 🎉",
                  f"✅ <b>Good news</b>\n\n<code>{e(email)}</code>\nNot found in any known breach. 🎉")
    title = _t(lang, "⚠️ <b>تم العثور على تسريبات!</b>", "⚠️ <b>Breaches found!</b>")
    body = _t(lang,
              f"البريد <code>{e(email)}</code> ظهر في <b>{len(exposed)}</b> تسريب. التفاصيل:",
              f"<code>{e(email)}</code> appeared in <b>{len(exposed)}</b> breach(es). Details:")
    rec_l = _t(lang, "عدد السجلات", "Records")
    data_l = _t(lang, "بيانات مكشوفة", "Exposed data")
    ind_l = _t(lang, "القطاع", "Industry")
    blocks = []
    for b in exposed[:12]:
        name = b.get("breach") or b.get("name") or "—"
        year = b.get("xposed_date") or b.get("year") or "—"
        data = (b.get("xposed_data") or "").replace(";", " · ")
        recs = b.get("xposed_records") or 0
        ind = b.get("industry") or ""
        blk = f"\n<b>• {e(name)}</b> ({e(year)})"
        try:
            if int(recs) > 0:
                blk += f"\n   {rec_l}: <code>{int(recs):,}</code>"
        except Exception:
            pass
        if data:
            blk += f"\n   {data_l}: {e(data)}"
        if ind and ind not in ("", "xx"):
            blk += f"\n   {ind_l}: {e(ind)}"
        blocks.append(blk)
    tip = _t(lang, "\n\n🔐 غيّر كلمات المرور المرتبطة وفعّل التحقق بخطوتين فوراً.",
             "\n\n🔐 Change related passwords and enable 2FA immediately.")
    return f"{title}\n\n{body}\n" + "\n".join(blocks) + tip


async def password_pwned(password: str, lang="ar") -> str:
    sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix, suffix = sha1[:5], sha1[5:]
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"https://api.pwnedpasswords.com/range/{prefix}",
                            headers={"Add-Padding": "true", "User-Agent": UA})
            text = r.text
    except Exception:
        return _t(lang, "❌ تعذّر فحص كلمة المرور.", "❌ Could not check the password.")
    count = 0
    for line in text.splitlines():
        parts = line.split(":")
        if parts[0] == suffix:
            count = int(parts[1])
            break
    # local strength estimate
    score = 0
    if len(password) >= 8: score += 1
    if len(password) >= 12: score += 1
    if re.search(r"[a-z]", password) and re.search(r"[A-Z]", password): score += 1
    if re.search(r"\d", password): score += 1
    if re.search(r"[^a-zA-Z0-9]", password): score += 1
    strength = [_t(lang, "ضعيفة جداً", "Very weak"), _t(lang, "ضعيفة", "Weak"),
                _t(lang, "متوسطة", "Fair"), _t(lang, "جيدة", "Good"),
                _t(lang, "قوية", "Strong"), _t(lang, "قوية جداً", "Very strong")][score]
    if count > 0:
        head = _t(lang, "⚠️ <b>كلمة مرور مسرّبة!</b>", "⚠️ <b>Compromised password!</b>")
        body = _t(lang, f"ظهرت <b>{count:,}</b> مرة في تسريبات معروفة. لا تستخدمها أبداً.",
                  f"Seen <b>{count:,}</b> times in known breaches. Never use it.")
    else:
        head = _t(lang, "✅ <b>لم تظهر في التسريبات</b>", "✅ <b>Not found in breaches</b>")
        body = _t(lang, "لكن هذا لا يعني أنها قوية بالضرورة.", "But that alone doesn't make it strong.")
    return f"{head}\n\n{body}\n" + _t(lang, "القوة", "Strength") + f": <b>{strength}</b> ({score}/5)"


async def _check_site(client, name, url):
    try:
        r = await client.get(url, headers={"User-Agent": UA})
        if r.status_code == 200:
            return (name, "found", url)
        if r.status_code in (404, 410):
            return (name, "free", url)
        return (name, "unknown", url)
    except Exception:
        return (name, "unknown", url)


async def username_search(username: str, lang="ar") -> str:
    username = username.strip().lstrip("@")
    if not re.match(r"^[A-Za-z0-9._-]{2,40}$", username):
        return _t(lang, "❌ اسم مستخدم غير صالح.", "❌ Invalid username.")
    sites = {
        "GitHub": f"https://github.com/{username}",
        "Instagram": f"https://www.instagram.com/{username}/",
        "X (Twitter)": f"https://x.com/{username}",
        "TikTok": f"https://www.tiktok.com/@{username}",
        "Reddit": f"https://www.reddit.com/user/{username}",
        "Telegram": f"https://t.me/{username}",
        "YouTube": f"https://www.youtube.com/@{username}",
        "GitLab": f"https://gitlab.com/{username}",
        "Twitch": f"https://www.twitch.tv/{username}",
        "Pinterest": f"https://www.pinterest.com/{username}/",
        "Medium": f"https://medium.com/@{username}",
        "Steam": f"https://steamcommunity.com/id/{username}",
    }
    async with httpx.AsyncClient(timeout=8, follow_redirects=True) as c:
        results = await asyncio.gather(*[_check_site(c, n, u) for n, u in sites.items()])
    title = _t(lang, f"🕵️ <b>بحث عن اسم المستخدم</b> <code>{e(username)}</code>",
               f"🕵️ <b>Username search</b> <code>{e(username)}</code>")
    found_lines, other_lines = [], []
    for name, status, url in results:
        if status == "found":
            found_lines.append(f"✅ <a href=\"{e(url)}\">{e(name)}</a>")
        elif status == "free":
            other_lines.append(f"⚪️ {e(name)}")
    body = _t(lang, "<b>حسابات محتملة:</b>", "<b>Likely profiles:</b>") + "\n"
    body += "\n".join(found_lines) if found_lines else _t(lang, "لا شيء واضح.", "None obvious.")
    note = _t(lang, "\n\n<i>ملاحظة: بعض المواقع تحجب الفحص الآلي، النتائج تقريبية.</i>",
              "\n\n<i>Note: some sites block automated checks; results are approximate.</i>")
    return f"{title}\n\n{body}{note}"


async def url_analyze(url: str, lang="ar") -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": UA})
    except Exception:
        return _t(lang, "❌ تعذّر الوصول إلى الرابط.", "❌ Could not reach the URL.")
    h = r.headers
    title_m = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.I | re.S)
    page_title = title_m.group(1).strip()[:120] if title_m else "—"
    sec = []
    for hd in ["strict-transport-security", "content-security-policy", "x-frame-options"]:
        sec.append("✅" if hd in h else "❌")
    title = _t(lang, "🔗 <b>تحليل الرابط / الموقع</b>", "🔗 <b>URL / Website Analysis</b>")
    L = {
        "final": _t(lang, "الرابط النهائي", "Final URL"),
        "status": _t(lang, "الحالة", "Status"),
        "server": _t(lang, "الخادم", "Server"),
        "tech": _t(lang, "التقنية", "Powered-by"),
        "title": _t(lang, "العنوان", "Title"),
        "sec": _t(lang, "رؤوس الأمان (HSTS/CSP/XFO)", "Security headers (HSTS/CSP/XFO)"),
        "https": _t(lang, "مشفّر HTTPS", "HTTPS"),
    }
    yes = _t(lang, "نعم ✅", "Yes ✅"); no = _t(lang, "لا ⚠️", "No ⚠️")
    lines = [
        title, "",
        f"{L['final']}: <code>{e(str(r.url))}</code>",
        f"{L['status']}: <b>{r.status_code}</b>",
        f"{L['https']}: {yes if str(r.url).startswith('https') else no}",
        f"{L['server']}: {e(h.get('server', '—'))}",
        f"{L['tech']}: {e(h.get('x-powered-by', '—'))}",
        f"{L['title']}: {e(page_title)}",
        f"{L['sec']}: {' '.join(sec)}",
    ]
    return "\n".join(lines)


async def email_validate(email: str, lang="ar") -> str:
    email = email.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return _t(lang, "❌ صيغة البريد غير صحيحة.", "❌ Invalid email format.")
    domain = email.split("@")[1]
    mx = []
    try:
        async with httpx.AsyncClient(timeout=12) as c:
            r = await c.get(f"https://dns.google/resolve?name={domain}&type=MX")
            for a in r.json().get("Answer", []):
                mx.append(a.get("data"))
    except Exception:
        pass
    has_mx = bool(mx)
    disposable = domain in {"mailinator.com", "10minutemail.com", "guerrillamail.com", "tempmail.com", "trashmail.com", "yopmail.com"}
    title = _t(lang, "📧 <b>التحقق من البريد الإلكتروني</b>", "📧 <b>Email Verification</b>")
    yes = _t(lang, "نعم ✅", "Yes ✅"); no = _t(lang, "لا ❌", "No ❌")
    lines = [
        title, "",
        f"{_t(lang,'البريد','Email')}: <code>{e(email)}</code>",
        f"{_t(lang,'النطاق','Domain')}: <code>{e(domain)}</code>",
        f"{_t(lang,'صيغة صحيحة','Valid syntax')}: {yes}",
        f"{_t(lang,'خوادم بريد (MX)','Mail servers (MX)')}: {yes if has_mx else no}",
        f"{_t(lang,'بريد مؤقت','Disposable')}: {(_t(lang,'نعم ⚠️','Yes ⚠️')) if disposable else no}",
    ]
    if mx:
        lines.append(f"MX: {', '.join('<code>'+e(m)+'</code>' for m in mx[:3])}")
    return "\n".join(lines)


async def hash_generate(text: str, lang="ar") -> str:
    b = text.encode("utf-8")
    title = _t(lang, "🔐 <b>مولّد البصمات (Hash)</b>", "🔐 <b>Hash Generator</b>")
    return "\n".join([
        title, "",
        f"MD5:\n<code>{hashlib.md5(b).hexdigest()}</code>",
        f"SHA1:\n<code>{hashlib.sha1(b).hexdigest()}</code>",
        f"SHA256:\n<code>{hashlib.sha256(b).hexdigest()}</code>",
        f"SHA512:\n<code>{hashlib.sha512(b).hexdigest()}</code>",
    ])


async def hash_identify(h: str, lang="ar") -> str:
    h = h.strip()
    guesses = []
    if re.fullmatch(r"[a-fA-F0-9]{32}", h): guesses.append("MD5 / NTLM")
    if re.fullmatch(r"[a-fA-F0-9]{40}", h): guesses.append("SHA1")
    if re.fullmatch(r"[a-fA-F0-9]{64}", h): guesses.append("SHA256")
    if re.fullmatch(r"[a-fA-F0-9]{128}", h): guesses.append("SHA512")
    if h.startswith("$2a$") or h.startswith("$2b$") or h.startswith("$2y$"): guesses.append("bcrypt")
    if h.startswith("$1$"): guesses.append("MD5 crypt")
    if h.startswith("$6$"): guesses.append("SHA512 crypt")
    title = _t(lang, "🧩 <b>تحديد نوع البصمة</b>", "🧩 <b>Hash Identifier</b>")
    if not guesses:
        return f"{title}\n\n" + _t(lang, "لم أتعرّف على النوع.", "Could not identify the type.")
    return f"{title}\n\n<code>{e(h[:80])}</code>\n\n" + _t(lang, "الأنواع المحتملة:", "Possible types:") + "\n" + "\n".join(f"• {g}" for g in guesses)


async def base64_tool(text: str, lang="ar") -> str:
    text = text.strip()
    title = _t(lang, "🔁 <b>أداة Base64</b>", "🔁 <b>Base64 Tool</b>")
    enc = b64.b64encode(text.encode("utf-8")).decode()
    dec = "—"
    try:
        dec = b64.b64decode(text.encode("utf-8"), validate=True).decode("utf-8", "replace")
    except Exception:
        dec = _t(lang, "(ليس Base64 صالح)", "(not valid Base64)")
    return f"{title}\n\n{_t(lang,'ترميز','Encode')}:\n<code>{e(enc)}</code>\n\n{_t(lang,'فك الترميز','Decode')}:\n<code>{e(dec)}</code>"


async def url_malware_scan(url: str, lang="ar") -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    p = urlparse(url)
    host = (p.netloc or "").lower()
    score = 0
    flags = []
    if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", host.split(":")[0]):
        score += 2; flags.append(_t(lang, "IP بدل اسم نطاق", "IP instead of domain"))
    if "@" in url:
        score += 2; flags.append(_t(lang, "رمز @ في الرابط", "@ symbol in URL"))
    if host.count("-") >= 3:
        score += 1; flags.append(_t(lang, "شرطات كثيرة", "many hyphens"))
    if len(host.split(".")) > 4:
        score += 1; flags.append(_t(lang, "نطاقات فرعية كثيرة", "many subdomains"))
    if "xn--" in host:
        score += 2; flags.append(_t(lang, "punycode (تمويه أحرف)", "punycode homograph"))
    susp_tld = (".zip", ".mov", ".xyz", ".top", ".club", ".gq", ".tk", ".ml", ".cf", ".work", ".click", ".loan", ".rest")
    if host.endswith(susp_tld):
        score += 1; flags.append(_t(lang, "امتداد مشبوه", "suspicious TLD"))
    brands = ["paypal", "apple", "google", "facebook", "instagram", "microsoft", "whatsapp", "binance", "netflix", "amazon", "telegram", "bank"]
    hit = next((b for b in brands if b in host), None)
    if hit and not (host == f"{hit}.com" or host.endswith(f".{hit}.com")):
        score += 3; flags.append(_t(lang, f"انتحال علامة ({hit})", f"brand impersonation ({hit})"))
    if len(url) > 90:
        score += 1; flags.append(_t(lang, "رابط طويل جداً", "very long URL"))
    if p.scheme != "https":
        score += 1; flags.append(_t(lang, "بدون HTTPS", "no HTTPS"))
    shorteners = {"bit.ly", "tinyurl.com", "goo.gl", "t.co", "ow.ly", "is.gd", "cutt.ly", "rebrand.ly", "shorturl.at"}
    if host in shorteners:
        flags.append(_t(lang, "رابط مختصر (وجهة مخفية)", "shortener (hidden destination)"))
    urlhaus_note = None
    try:
        async with httpx.AsyncClient(timeout=12) as c:
            r = await c.post("https://urlhaus-api.abuse.ch/v1/host/", data={"host": host.split(":")[0]})
            j = r.json()
            if j.get("query_status") == "ok" and j.get("urls"):
                score += 6
                urlhaus_note = _t(lang, "🚨 مُدرج في قاعدة URLhaus لمواقع البرمجيات الخبيثة!",
                                  "🚨 Listed in the URLhaus malware database!")
    except Exception:
        pass
    if score >= 6:
        verdict = _t(lang, "🔴 خطير جداً — لا تفتحه", "🔴 Dangerous — do not open")
    elif score >= 3:
        verdict = _t(lang, "🟠 مشبوه — احذر", "🟠 Suspicious — be careful")
    else:
        verdict = _t(lang, "🟢 يبدو آمناً (لا ضمان مطلق)", "🟢 Looks safe (no absolute guarantee)")
    title = _t(lang, "🛡️ <b>فاحص الروابط الخبيثة</b>", "🛡️ <b>Malicious URL Scanner</b>")
    lines = [title, "",
             f"{_t(lang,'الرابط','URL')}: <code>{e(url[:120])}</code>",
             f"{_t(lang,'النطاق','Host')}: <code>{e(host)}</code>",
             f"{_t(lang,'التقييم','Verdict')}: <b>{verdict}</b>",
             f"{_t(lang,'درجة الخطورة','Risk score')}: <b>{score}/10</b>"]
    if urlhaus_note:
        lines.append(urlhaus_note)
    if flags:
        lines.append("\n" + _t(lang, "المؤشرات:", "Indicators:"))
        lines += [f"• {f}" for f in flags]
    return "\n".join(lines)


async def password_generator(text: str, lang="ar") -> str:
    digits = re.sub(r"\D", "", text or "")
    n = int(digits) if digits else 16
    n = min(max(n, 8), 64)
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+[]{}?"
    pwd = "".join(secrets.choice(alphabet) for _ in range(n))
    title = _t(lang, "🔑 <b>مولّد كلمات مرور قوية</b>", "🔑 <b>Strong Password Generator</b>")
    hint = _t(lang, f"تم توليد كلمة مرور بطول {n} حرفاً:", f"Generated a {n}-character password:")
    tip = _t(lang, "\n\n💡 أرسل رقماً (8-64) لتحديد الطول.", "\n\n💡 Send a number (8-64) to set the length.")
    return f"{title}\n\n{hint}\n<code>{e(pwd)}</code>{tip}"


async def google_dorks(target: str, lang="ar") -> str:
    t = target.strip().replace("http://", "").replace("https://", "").split("/")[0]
    if not t:
        return _t(lang, "❌ أرسل نطاقاً أو كلمة مفتاحية.", "❌ Send a domain or keyword.")
    dorks = [
        (_t(lang, "ملفات PDF", "PDF documents"), f'site:{t} filetype:pdf'),
        (_t(lang, "صفحات تسجيل الدخول", "Login pages"), f'site:{t} inurl:login'),
        (_t(lang, "فهرسة المجلدات المكشوفة", "Open directory listing"), f'site:{t} intitle:"index of"'),
        (_t(lang, "ملفات إعدادات حسّاسة", "Sensitive config files"), f'site:{t} ext:env | ext:ini | ext:conf'),
        (_t(lang, "جداول بيانات", "Spreadsheets"), f'site:{t} filetype:xls | filetype:csv'),
        (_t(lang, "النطاقات الفرعية", "Subdomains"), f'site:*.{t}'),
        (_t(lang, "نسخ احتياطية", "Backups"), f'site:{t} ext:bak | ext:old | ext:sql'),
        (_t(lang, "بريد على النطاق", "Emails on domain"), f'"@{t}"'),
    ]
    title = _t(lang, f"🧰 <b>مولّد Google Dorks لـ</b> <code>{e(t)}</code>", f"🧰 <b>Google Dorks for</b> <code>{e(t)}</code>")
    note = _t(lang, "استعلامات بحث متقدمة للاستطلاع القانوني — اضغط للفتح:",
              "Advanced search queries for legal recon — tap to open:")
    lines = [title, "", note, ""]
    for label, q in dorks:
        link = "https://www.google.com/search?q=" + quote_plus(q)
        lines.append(f"🔍 <a href=\"{link}\">{e(label)}</a>\n   <code>{e(q)}</code>")
    return "\n".join(lines)
