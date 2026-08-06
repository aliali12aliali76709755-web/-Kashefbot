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
- ✅ 12 OSINT tools working with live public data, daily free-tier limits (8/day free, 150 pro, unlimited elite).
- ✅ Ethical Hacking Academy, CTF challenges with points + leaderboard, programming courses.
- ✅ Bilingual (AR/EN) bot + website with full RTL support.
- ✅ Referral system (+25 pts/friend), gamification.
- ✅ Stripe subscriptions (Pro/Elite, monthly/yearly) from both bot and website; auto plan activation.
- ✅ Admin dashboard (overview, users, revenue, broadcast).
- ✅ Premium dark cyber landing page. Tested: 19/19 backend, 100% frontend.

## Backlog / Next
- P1: Google Dorks generator, IBAN/BIN lookup, more CTF challenges, lesson progress tracking.
- P1: Admin JWT auth instead of static key; broadcast rate-limiting.
- P2: Payment receipts/history in bot, referral leaderboard rewards, more courses & lessons.
- P2: Own Stripe key or Razorpay for a Stripe-supported country to go live.

## Credentials
See /app/memory/test_credentials.md
