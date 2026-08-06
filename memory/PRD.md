# Cyber OSINT Suite — PRD

## Original Problem Statement
User (Arabic/Iraqi dialect) requested a professional Telegram bot for cybersecurity, OSINT
information gathering, ethical hacking and programming education, monetized as a subscription
business ("business باشتراكات مدفوعة"), bilingual Arabic + English, highest design quality.
Scope boundary agreed with user: LEGAL / ethical only — NO phone hacking, NO surveillance of
individuals. All OSINT uses free public sources.

## Architecture
- Backend: FastAPI (webhook-mode Telegram bot, no polling), MongoDB (motor).
- Frontend: React (bilingual RTL/LTR landing + admin dashboard + payment pages), Tailwind, framer-motion.
- Payments: Stripe via emergentintegrations Flow B (shared test key `sk_test_emergent`).
  NOTE: claimable sandbox was unavailable (account country resolved to TR, unsupported).
- Bot: @xvcezxbot (webhook: /api/telegram/webhook/{secret}).

## Core Modules
- core.py — TelegramClient, Mongo, user helpers, plans/limits, plan activation.
- osint.py — 12 legal OSINT tools (IP, phone, WHOIS/RDAP, DNS via DoH, email breach [XposedOrNot],
  pwned password [HIBP k-anonymity], username search, URL analysis, email verify, hash gen/id, base64).
- content.py — Academy (5 tracks), CTF (6 challenges), Courses (4) — bilingual.
- telegram_bot.py — bilingual menus, state machine, CTF scoring, referrals, subscriptions.
- payments.py — checkout / status / webhook / bot_checkout.
- server.py — routes, admin APIs, public stats, startup webhook registration.

## Implemented (2026-08-06)
- ✅ 17 legal OSINT/security tools with live public data + daily free-tier limits.
- ✅ Ethical Hacking Academy (5 tracks), CTF (8 challenges) + leaderboard, programming courses (4, long simple lessons).
- ✅ Bilingual (AR/EN) bot + website with full RTL support.
- ✅ Referral system (+25 pts/friend), gamification.
- ✅ Stripe subscriptions (Pro/Elite, monthly/yearly) from bot + website; auto activation.
- ✅ Admin dashboard (overview, users, revenue, broadcast).

### Iteration 2 (2026-08-06) — new legal, high-demand features
- ✅ Malicious/phishing URL scanner (heuristics + URLhaus) — defensive.
- ✅ Enriched email-breach report (exposed data classes, record counts via XposedOrNot breach-analytics).
- ✅ Public Telegram entity info (channels/groups/bots via getChat) — public data only, refuses private PII.
- ✅ Google Dorks generator, strong password generator.
- ✅ Consent-based location share (double opt-in: link consent + browser GPS permission; requester notified in-bot with map link) — transparent, NOT covert tracking.
- ✅ Explicitly REFUSED illegal requests: covert IP/location grabbers, Telegram user doxxing (phone/location/posts), malware/virus generation, remote device locking. Reason kept legal to avoid Telegram/Stripe bans and legal exposure.
- Tested: iteration_2 backend 32/33 (the 1 "fail" was a test-spec typo expecting tools=18; real consistent count is 17), frontend 100%.

## Backlog / Next
- P1: Google Dorks generator, IBAN/BIN lookup, more CTF challenges, lesson progress tracking.
- P1: Admin JWT auth instead of static key; broadcast rate-limiting.
- P2: Payment receipts/history in bot, referral leaderboard rewards, more courses & lessons.
- P2: Own Stripe key or Razorpay for a Stripe-supported country to go live.

## Credentials
See /app/memory/test_credentials.md
