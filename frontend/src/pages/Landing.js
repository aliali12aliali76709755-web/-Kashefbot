import React, { useEffect, useState } from "react";
import axios from "axios";
import { motion } from "framer-motion";
import { toast } from "sonner";
import {
  Shield, Globe, Phone, Search, Network, Mail, KeyRound, UserSearch,
  Link2, Hash, Binary, GraduationCap, Flag, Code2, Terminal, ArrowRight,
  Check, Send, Lock, Zap, Trophy, Activity, ScanLine, Fingerprint, X,
} from "lucide-react";
import { useLang } from "@/i18n";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;
const BOT_LINK = "https://t.me/xvcezxbot";
const HERO_IMG =
  "https://images.unsplash.com/photo-1624969862644-791f3dc98927?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjA1NzR8MHwxfHNlYXJjaHw0fHxoYWNrZXIlMjBjb2RpbmclMjBkYXJrfGVufDB8fHx8MTc4NTk3NzU1M3ww&ixlib=rb-4.1.0&q=85";

const fade = {
  hidden: { opacity: 0, y: 24 },
  show: (i = 0) => ({ opacity: 1, y: 0, transition: { duration: 0.5, delay: i * 0.06 } }),
};

function Section({ children, className = "", id }) {
  return (
    <section id={id} className={`relative z-10 mx-auto w-full max-w-7xl px-5 md:px-8 ${className}`}>
      {children}
    </section>
  );
}

function Header({ onBuy }) {
  const { tr, toggle, lang } = useLang();
  return (
    <header className="sticky top-0 z-50 border-b border-white/10 bg-black/60 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-5 md:px-8">
        <a href="#top" className="flex items-center gap-2" data-testid="logo">
          <div className="flex h-8 w-8 items-center justify-center border border-cyan-400/60 text-cyan-400" style={{ boxShadow: "0 0 18px -4px var(--cyan)" }}>
            <Shield size={18} />
          </div>
          <span className="font-display text-lg font-black tracking-tight">CYBER<span className="text-cyan">OSINT</span></span>
        </a>
        <nav className="hidden items-center gap-7 text-sm text-zinc-400 md:flex">
          <a href="#tools" className="transition-colors hover:text-white" data-testid="nav-tools">{tr("الأدوات", "Tools")}</a>
          <a href="#learn" className="transition-colors hover:text-white" data-testid="nav-learn">{tr("التعلّم", "Learn")}</a>
          <a href="#pricing" className="transition-colors hover:text-white" data-testid="nav-pricing">{tr("الأسعار", "Pricing")}</a>
        </nav>
        <div className="flex items-center gap-2">
          <button onClick={toggle} data-testid="lang-toggle"
            className="border border-white/15 px-3 py-1.5 font-mono text-xs text-zinc-300 transition-colors hover:border-cyan-400/60 hover:text-cyan-400">
            {lang === "ar" ? "EN" : "ع"}
          </button>
          <a href={BOT_LINK} target="_blank" rel="noreferrer" data-testid="header-open-bot"
            className="flex items-center gap-2 bg-cyan px-4 py-1.5 text-sm font-semibold text-black transition-transform hover:scale-[1.03]">
            <Send size={15} /> {tr("افتح البوت", "Open Bot")}
          </a>
        </div>
      </div>
    </header>
  );
}

function Hero() {
  const { tr } = useLang();
  return (
    <div id="top" className="relative overflow-hidden border-b border-white/10">
      <div className="absolute inset-0 z-0">
        <img src={HERO_IMG} alt="cyber" className="h-full w-full object-cover opacity-40" />
        <div className="absolute inset-0 bg-black/60" />
        <div className="absolute inset-0 grid-bg opacity-60" />
      </div>
      <Section className="relative z-10 py-20 md:py-32">
        <motion.div initial="hidden" animate="show" variants={fade} className="max-w-3xl">
          <div className="mb-6 inline-flex items-center gap-2 border border-cyan-400/40 bg-cyan-400/5 px-3 py-1 font-mono text-xs text-cyan-400">
            <span className="h-2 w-2 animate-pulse rounded-full bg-cyan-400" />
            {tr("قانوني 100% · مصادر مفتوحة", "100% Legal · Open Sources")}
          </div>
          <h1 className="font-display text-4xl font-black leading-[1.05] tracking-tight md:text-6xl">
            {tr("منصة الأمن السيبراني و", "The Cybersecurity &")}
            <br />
            <span className="text-cyan">{tr("جمع المعلومات", "OSINT")}</span> {tr("الاحترافية", "Suite")}
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-zinc-300">
            {tr(
              "بوت تليجرام واحد يجمع أدوات OSINT، أكاديمية اختراق أخلاقي، تحديات CTF، وتعلّم البرمجة من الصفر. كل ما يحتاجه الهاكر الأخلاقي والمبرمج وخبير الأمن.",
              "One Telegram bot with OSINT tools, an ethical-hacking academy, CTF challenges, and code learning from zero. Everything an ethical hacker, developer & security pro needs."
            )}
          </p>
          <div className="mt-9 flex flex-wrap items-center gap-3">
            <a href={BOT_LINK} target="_blank" rel="noreferrer" data-testid="hero-open-bot"
              className="group flex items-center gap-2 bg-cyan px-6 py-3 font-semibold text-black transition-transform hover:scale-[1.03]">
              <Send size={18} /> {tr("ابدأ الآن مجاناً", "Start Free Now")}
              <ArrowRight size={16} className="transition-transform group-hover:translate-x-1 rtl:-scale-x-100" />
            </a>
            <a href="#tools" data-testid="hero-explore"
              className="flex items-center gap-2 border border-white/20 px-6 py-3 font-semibold text-white transition-colors hover:border-cyan-400/60 hover:text-cyan-400">
              <Terminal size={18} /> {tr("استعرض الأدوات", "Explore Tools")}
            </a>
          </div>
        </motion.div>

        <motion.div initial="hidden" animate="show" variants={fade} custom={2}
          className="mt-14 max-w-xl border border-white/10 bg-black/70 p-4 font-mono text-xs backdrop-blur-md">
          <div className="mb-3 flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-red-500" />
            <span className="h-2.5 w-2.5 rounded-full bg-yellow-400" />
            <span className="h-2.5 w-2.5 rounded-full bg-green-500" />
            <span className="ms-2 text-zinc-500">osint@suite:~</span>
          </div>
          <div className="space-y-1 text-zinc-300">
            <p><span className="text-cyan">$</span> lookup 8.8.8.8</p>
            <p className="text-zinc-500">→ Google LLC · Ashburn, US · AS15169</p>
            <p><span className="text-cyan">$</span> breach check user@mail.com</p>
            <p className="text-red-400">→ found in 204 breaches ⚠</p>
            <p><span className="text-cyan">$</span> whois github.com<span className="blink text-cyan">▋</span></p>
          </div>
        </motion.div>
      </Section>
    </div>
  );
}

function LiveStats() {
  const { tr } = useLang();
  const [stats, setStats] = useState({ users: 0, scans: 0, solved: 0, tools: 12 });
  useEffect(() => {
    axios.get(`${API}/stats/public`).then((r) => setStats(r.data)).catch(() => {});
  }, []);
  const items = [
    { icon: Activity, v: stats.users, l: tr("مستخدم", "Users") },
    { icon: ScanLine, v: stats.scans, l: tr("عملية فحص", "Scans Run") },
    { icon: Trophy, v: stats.solved, l: tr("تحدي محلول", "Flags Solved") },
    { icon: Zap, v: stats.tools, l: tr("أداة OSINT", "OSINT Tools") },
  ];
  return (
    <div className="relative z-10 border-b border-white/10 bg-[#0a0a0b]">
      <div className="mx-auto grid max-w-7xl grid-cols-2 md:grid-cols-4">
        {items.map((it, i) => (
          <div key={i} className="border-b border-e border-white/10 px-6 py-8 md:border-b-0" data-testid={`stat-${i}`}>
            <it.icon size={20} className="text-cyan" />
            <div className="mt-3 font-mono text-3xl font-bold">{Number(it.v).toLocaleString()}</div>
            <div className="mt-1 text-sm text-zinc-500">{it.l}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

const TOOLS = [
  { icon: Globe, ar: "معلومات IP", en: "IP Intelligence" },
  { icon: Phone, ar: "تحليل رقم هاتف", en: "Phone Analysis" },
  { icon: Search, ar: "WHOIS نطاق", en: "Domain WHOIS" },
  { icon: Network, ar: "سجلات DNS", en: "DNS Records" },
  { icon: Mail, ar: "فحص تسريب البريد", en: "Email Breach" },
  { icon: KeyRound, ar: "كلمة مرور مسرّبة", en: "Pwned Password" },
  { icon: UserSearch, ar: "بحث اسم مستخدم", en: "Username Search" },
  { icon: Link2, ar: "تحليل الروابط", en: "URL Analysis" },
  { icon: Check, ar: "تحقق البريد", en: "Email Verify" },
  { icon: Hash, ar: "مولّد Hash", en: "Hash Generator" },
  { icon: Fingerprint, ar: "تحديد نوع Hash", en: "Hash Identifier" },
  { icon: Binary, ar: "أداة Base64", en: "Base64 Tool" },
];

function Tools() {
  const { tr } = useLang();
  return (
    <Section id="tools" className="py-20 md:py-28">
      <motion.div initial="hidden" whileInView="show" viewport={{ once: true }} variants={fade}>
        <p className="font-mono text-sm text-cyan">// {tr("مصادر مفتوحة · قانونية", "open sources · legal")}</p>
        <h2 className="mt-3 font-display text-3xl font-black tracking-tight md:text-5xl">
          {tr("12 أداة OSINT جاهزة", "12 OSINT Tools, Ready")}
        </h2>
        <p className="mt-4 max-w-2xl text-zinc-400">
          {tr("كل أداة تعمل مباشرة داخل تليجرام، تعتمد بيانات عامة ومجانية بالكامل.",
            "Each tool runs right inside Telegram, powered entirely by free, public data.")}
        </p>
      </motion.div>
      <div className="mt-12 grid grid-cols-2 border-s border-t border-white/10 md:grid-cols-4">
        {TOOLS.map((t, i) => (
          <motion.div key={i} custom={i} initial="hidden" whileInView="show" viewport={{ once: true }} variants={fade}
            className="group border-b border-e border-white/10 p-6 transition-colors hover:bg-cyan-400/[0.04]"
            data-testid={`tool-card-${i}`}>
            <t.icon size={22} className="text-zinc-400 transition-colors group-hover:text-cyan-400" />
            <div className="mt-4 font-display font-bold">{tr(t.ar, t.en)}</div>
            <div className="mt-1 font-mono text-xs text-zinc-600">/{t.en.toLowerCase().replace(/ /g, "_")}</div>
          </motion.div>
        ))}
      </div>
    </Section>
  );
}

function Learn() {
  const { tr } = useLang();
  const cards = [
    { icon: GraduationCap, ar: "أكاديمية الاختراق الأخلاقي", en: "Ethical Hacking Academy",
      dar: "5 مسارات: استطلاع، أمن الويب OWASP، الشبكات، التشفير، لينكس.", den: "5 tracks: recon, OWASP web, networking, crypto, Linux.", tag: "5 tracks" },
    { icon: Flag, ar: "تحديات CTF", en: "CTF Challenges",
      dar: "تحديات تفاعلية بنقاط ولوحة متصدّرين لصقل مهاراتك.", den: "Interactive point-based challenges with a live leaderboard.", tag: "6 challenges" },
    { icon: Code2, ar: "تعلّم البرمجة", en: "Learn to Code",
      dar: "دورات بايثون، جافاسكربت، Bash وأساسيات الأمن من الصفر.", den: "Python, JavaScript, Bash & security basics from zero.", tag: "4 courses" },
  ];
  return (
    <Section id="learn" className="py-20 md:py-28">
      <h2 className="font-display text-3xl font-black tracking-tight md:text-5xl">
        {tr("تعلّم. تدرّب. احترف.", "Learn. Practice. Master.")}
      </h2>
      <div className="mt-12 grid gap-px border border-white/10 bg-white/10 md:grid-cols-3">
        {cards.map((c, i) => (
          <motion.div key={i} custom={i} initial="hidden" whileInView="show" viewport={{ once: true }} variants={fade}
            className="bg-[#0b0b0d] p-8" data-testid={`learn-card-${i}`}>
            <div className="flex items-center justify-between">
              <c.icon size={26} className="text-violet" />
              <span className="border border-white/10 px-2 py-0.5 font-mono text-xs text-zinc-500">{c.tag}</span>
            </div>
            <h3 className="mt-6 font-display text-xl font-bold">{tr(c.ar, c.en)}</h3>
            <p className="mt-3 text-sm leading-relaxed text-zinc-400">{tr(c.dar, c.den)}</p>
          </motion.div>
        ))}
      </div>
    </Section>
  );
}

function CheckoutModal({ open, onClose, plan }) {
  const { tr, lang } = useLang();
  const [tgId, setTgId] = useState("");
  const [cycle, setCycle] = useState("monthly");
  const [loading, setLoading] = useState(false);
  if (!open) return null;
  const pkg = `${plan}_${cycle}`;

  const pay = async () => {
    if (!/^\d{4,}$/.test(tgId.trim())) {
      toast.error(tr("أدخل معرّف تليجرام رقمي صحيح", "Enter a valid numeric Telegram ID"));
      return;
    }
    setLoading(true);
    try {
      const res = await axios.post(`${API}/payments/checkout`, {
        package_id: pkg, telegram_id: tgId.trim(), origin_url: window.location.origin,
      });
      window.location.href = res.data.checkout_url;
    } catch (e) {
      toast.error(tr("تعذّر إنشاء الدفع", "Could not start checkout"));
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 p-4" data-testid="checkout-modal">
      <div className="w-full max-w-md border border-white/15 bg-[#0d0d0f] p-6">
        <div className="flex items-center justify-between">
          <h3 className="font-display text-xl font-bold">{tr("إتمام الاشتراك", "Complete Subscription")}</h3>
          <button onClick={onClose} data-testid="checkout-close" className="text-zinc-500 hover:text-white"><X size={20} /></button>
        </div>
        <p className="mt-2 text-sm text-zinc-400">
          {tr(`الباقة: ${plan.toUpperCase()}`, `Plan: ${plan.toUpperCase()}`)}
        </p>
        <div className="mt-5 grid grid-cols-2 gap-px border border-white/10 bg-white/10">
          {["monthly", "yearly"].map((c) => (
            <button key={c} onClick={() => setCycle(c)} data-testid={`cycle-${c}`}
              className={`bg-[#0d0d0f] py-2.5 text-sm font-semibold transition-colors ${cycle === c ? "text-cyan-400" : "text-zinc-500 hover:text-white"}`}>
              {c === "monthly" ? tr("شهري", "Monthly") : tr("سنوي", "Yearly")}
            </button>
          ))}
        </div>
        <label className="mt-5 block text-sm text-zinc-400">
          {tr("معرّف تليجرام الرقمي (Telegram ID)", "Your numeric Telegram ID")}
        </label>
        <input value={tgId} onChange={(e) => setTgId(e.target.value)} data-testid="checkout-tgid"
          placeholder="123456789" inputMode="numeric"
          className="mt-2 w-full border border-white/15 bg-black px-3 py-2.5 font-mono text-sm outline-none focus:border-cyan-400" />
        <p className="mt-2 font-mono text-xs text-zinc-600">
          {tr("أرسل /me للبوت للحصول على معرّفك.", "Send /me to the bot to get your ID.")}
        </p>
        <button onClick={pay} disabled={loading} data-testid="checkout-pay"
          className="mt-5 flex w-full items-center justify-center gap-2 bg-cyan py-3 font-semibold text-black transition-transform hover:scale-[1.02] disabled:opacity-60">
          <Lock size={16} /> {loading ? tr("جارٍ التحويل…", "Redirecting…") : tr("ادفع بأمان عبر Stripe", "Pay securely via Stripe")}
        </button>
        <p className="mt-3 text-center font-mono text-xs text-zinc-600">
          {tr("وضع تجريبي · البطاقة 4242 4242 4242 4242", "Test mode · card 4242 4242 4242 4242")}
        </p>
      </div>
    </div>
  );
}

function Pricing() {
  const { tr } = useLang();
  const [modal, setModal] = useState(null);
  const tiers = [
    { key: "free", name: "FREE", price: "$0", ar: ["8 عمليات فحص يومياً", "دروس أساسية", "تحديات CTF"], en: ["8 daily scans", "Basic lessons", "CTF challenges"], cta: tr("ابدأ مجاناً", "Start Free"), free: true },
    { key: "pro", name: "PRO", price: "$9.99", per: tr("/شهر", "/mo"), ar: ["150 عملية فحص يومياً", "كل دروس الأكاديمية", "كل تحديات CTF", "دعم أولوية"], en: ["150 daily scans", "All academy lessons", "All CTF challenges", "Priority support"], cta: tr("اشترك في Pro", "Get Pro") },
    { key: "elite", name: "ELITE", price: "$24.99", per: tr("/شهر", "/mo"), ar: ["عمليات فحص غير محدودة", "كل الميزات", "وصول مبكر للأدوات", "دعم مخصّص"], en: ["Unlimited scans", "Everything included", "Early tool access", "Dedicated support"], cta: tr("اشترك في Elite", "Get Elite"), elite: true },
  ];
  return (
    <Section id="pricing" className="py-20 md:py-28">
      <div className="text-center">
        <h2 className="font-display text-3xl font-black tracking-tight md:text-5xl">{tr("خطط الاشتراك", "Pricing")}</h2>
        <p className="mt-4 text-zinc-400">{tr("افتح مشروعك الاحترافي في الأمن السيبراني.", "Launch your professional cybersecurity business.")}</p>
      </div>
      <div className="mt-14 grid gap-6 md:grid-cols-3">
        {tiers.map((t, i) => (
          <motion.div key={t.key} custom={i} initial="hidden" whileInView="show" viewport={{ once: true }} variants={fade}
            className={`relative flex flex-col p-8 ${t.elite ? "beam" : "border border-white/10 bg-[#0b0b0d]"}`}
            data-testid={`price-${t.key}`}>
            {t.elite && (
              <span className="absolute -top-3 start-8 bg-cyan px-3 py-0.5 font-mono text-xs font-bold text-black">
                {tr("الأكثر قوة", "MOST POWERFUL")}
              </span>
            )}
            <div className="font-mono text-sm text-zinc-500">{t.name}</div>
            <div className="mt-3 flex items-end gap-1">
              <span className="font-display text-4xl font-black">{t.price}</span>
              {t.per && <span className="mb-1 text-zinc-500">{t.per}</span>}
            </div>
            <ul className="mt-7 flex-1 space-y-3">
              {tr(t.ar, t.en).map((f, j) => (
                <li key={j} className="flex items-start gap-2.5 text-sm text-zinc-300">
                  <Check size={16} className="mt-0.5 shrink-0 text-cyan-400" /> {f}
                </li>
              ))}
            </ul>
            {t.free ? (
              <a href={BOT_LINK} target="_blank" rel="noreferrer" data-testid={`price-cta-${t.key}`}
                className="mt-8 border border-white/20 py-3 text-center font-semibold transition-colors hover:border-cyan-400/60 hover:text-cyan-400">
                {t.cta}
              </a>
            ) : (
              <button onClick={() => setModal(t.key)} data-testid={`price-cta-${t.key}`}
                className={`mt-8 py-3 text-center font-semibold transition-transform hover:scale-[1.02] ${t.elite ? "bg-cyan text-black" : "border border-cyan-400/50 text-cyan-400 hover:bg-cyan-400/10"}`}>
                {t.cta}
              </button>
            )}
          </motion.div>
        ))}
      </div>
      <CheckoutModal open={!!modal} plan={modal || "pro"} onClose={() => setModal(null)} />
    </Section>
  );
}

function LegalCTA() {
  const { tr } = useLang();
  return (
    <Section className="pb-24">
      <div className="relative overflow-hidden border border-white/10 bg-[#0b0b0d] p-10 md:p-16">
        <div className="absolute inset-0 grid-bg opacity-40" />
        <div className="relative z-10 max-w-2xl">
          <div className="mb-4 inline-flex items-center gap-2 border border-emerald-400/40 bg-emerald-400/5 px-3 py-1 font-mono text-xs text-emerald-400">
            <Shield size={13} /> {tr("أخلاقي · قانوني · مسؤول", "Ethical · Legal · Responsible")}
          </div>
          <h2 className="font-display text-3xl font-black tracking-tight md:text-4xl">
            {tr("جاهز تبدأ؟", "Ready to start?")}
          </h2>
          <p className="mt-4 text-zinc-400">
            {tr("منصّتنا مخصّصة للأمن السيبراني الدفاعي والتعلّم وجمع المعلومات من المصادر المفتوحة فقط. لا ندعم اختراق أجهزة الآخرين أو انتهاك الخصوصية.",
              "Our platform is for defensive security, learning, and open-source intelligence only. We do not support hacking others' devices or violating privacy.")}
          </p>
          <a href={BOT_LINK} target="_blank" rel="noreferrer" data-testid="footer-open-bot"
            className="mt-8 inline-flex items-center gap-2 bg-cyan px-6 py-3 font-semibold text-black transition-transform hover:scale-[1.03]">
            <Send size={18} /> {tr("افتح البوت على تليجرام", "Open the Telegram Bot")}
          </a>
        </div>
      </div>
    </Section>
  );
}

function Footer() {
  const { tr } = useLang();
  return (
    <footer className="relative z-10 border-t border-white/10 py-8">
      <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-3 px-5 text-sm text-zinc-500 md:flex-row md:px-8">
        <span className="font-display font-bold text-zinc-300">CYBER<span className="text-cyan">OSINT</span> SUITE</span>
        <span className="font-mono text-xs">{tr("© 2026 · للاستخدام الأخلاقي والقانوني فقط", "© 2026 · For ethical & legal use only")}</span>
        <a href="/admin" className="font-mono text-xs hover:text-cyan-400" data-testid="admin-link">{tr("لوحة التحكم", "Admin")}</a>
      </div>
    </footer>
  );
}

export default function Landing() {
  return (
    <div>
      <Header />
      <Hero />
      <LiveStats />
      <Tools />
      <Learn />
      <Pricing />
      <LegalCTA />
      <Footer />
    </div>
  );
}
