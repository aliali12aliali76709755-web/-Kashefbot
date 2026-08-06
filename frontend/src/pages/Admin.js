import React, { useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { motion } from "framer-motion";
import { Shield, Users, DollarSign, ScanLine, Trophy, Send, LogOut, RefreshCw } from "lucide-react";
import { useLang } from "@/i18n";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function Admin() {
  const { tr, toggle, lang } = useLang();
  const [key, setKey] = useState(sessionStorage.getItem("adminKey") || "");
  const [authed, setAuthed] = useState(false);
  const [input, setInput] = useState("");
  const [overview, setOverview] = useState(null);
  const [users, setUsers] = useState([]);
  const [msg, setMsg] = useState("");
  const [loading, setLoading] = useState(false);

  const load = async (k) => {
    try {
      const [ov, us] = await Promise.all([
        axios.get(`${API}/admin/overview`, { params: { key: k } }),
        axios.get(`${API}/admin/users`, { params: { key: k } }),
      ]);
      setOverview(ov.data);
      setUsers(us.data.users);
      setAuthed(true);
    } catch {
      toast.error(tr("مفتاح غير صحيح", "Invalid key"));
      sessionStorage.removeItem("adminKey");
    }
  };

  useEffect(() => { if (key) load(key); /* eslint-disable-next-line */ }, []);

  const login = async () => {
    try {
      await axios.post(`${API}/admin/login`, { key: input });
      sessionStorage.setItem("adminKey", input);
      setKey(input);
      load(input);
    } catch {
      toast.error(tr("مفتاح غير صحيح", "Invalid key"));
    }
  };

  const broadcast = async () => {
    if (!msg.trim()) return;
    setLoading(true);
    try {
      const r = await axios.post(`${API}/admin/broadcast`, { key, message: msg });
      toast.success(tr(`أُرسلت إلى ${r.data.sent} مستخدم`, `Sent to ${r.data.sent} users`));
      setMsg("");
    } catch {
      toast.error(tr("فشل الإرسال", "Broadcast failed"));
    }
    setLoading(false);
  };

  const logout = () => { sessionStorage.removeItem("adminKey"); setAuthed(false); setKey(""); };

  if (!authed) {
    return (
      <div className="grain flex min-h-screen items-center justify-center px-5">
        <div className="w-full max-w-sm border border-white/15 bg-[#0d0d0f] p-8">
          <div className="mb-6 flex items-center gap-2">
            <Shield className="text-cyan" size={22} />
            <h1 className="font-display text-xl font-black">{tr("لوحة التحكم", "Admin Panel")}</h1>
          </div>
          <label className="text-sm text-zinc-400">{tr("مفتاح الإدارة", "Admin Key")}</label>
          <input type="password" value={input} onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && login()} data-testid="admin-key-input"
            className="mt-2 w-full border border-white/15 bg-black px-3 py-2.5 font-mono text-sm outline-none focus:border-cyan-400" />
          <button onClick={login} data-testid="admin-login-btn"
            className="mt-5 w-full bg-cyan py-2.5 font-semibold text-black transition-transform hover:scale-[1.02]">
            {tr("دخول", "Enter")}
          </button>
        </div>
      </div>
    );
  }

  const cards = overview ? [
    { icon: Users, l: tr("المستخدمون", "Users"), v: overview.users },
    { icon: DollarSign, l: tr("الإيرادات", "Revenue"), v: `$${overview.revenue}` },
    { icon: Trophy, l: tr("اشتراكات مدفوعة", "Paid Subs"), v: overview.paid_subscriptions },
    { icon: ScanLine, l: tr("عمليات الفحص", "Scans"), v: overview.scans },
  ] : [];

  return (
    <div className="grain min-h-screen">
      <header className="sticky top-0 z-40 border-b border-white/10 bg-black/60 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5">
          <div className="flex items-center gap-2">
            <Shield className="text-cyan" size={20} />
            <span className="font-display font-black">{tr("لوحة التحكم", "Admin")}</span>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={toggle} className="border border-white/15 px-3 py-1.5 font-mono text-xs hover:text-cyan-400">{lang === "ar" ? "EN" : "ع"}</button>
            <button onClick={() => load(key)} data-testid="admin-refresh" className="border border-white/15 p-2 hover:text-cyan-400"><RefreshCw size={15} /></button>
            <button onClick={logout} data-testid="admin-logout" className="flex items-center gap-1.5 border border-white/15 px-3 py-1.5 text-sm hover:text-red-400"><LogOut size={15} /> {tr("خروج", "Exit")}</button>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-6xl px-5 py-8">
        <div className="grid grid-cols-2 border-s border-t border-white/10 md:grid-cols-4">
          {cards.map((c, i) => (
            <motion.div key={i} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.05 }}
              className="border-b border-e border-white/10 p-6" data-testid={`admin-stat-${i}`}>
              <c.icon size={18} className="text-cyan" />
              <div className="mt-3 font-mono text-2xl font-bold">{c.v}</div>
              <div className="mt-1 text-sm text-zinc-500">{c.l}</div>
            </motion.div>
          ))}
        </div>

        {overview && (
          <div className="mt-6 flex flex-wrap gap-3 font-mono text-xs">
            {Object.entries(overview.plan_breakdown).map(([p, n]) => (
              <span key={p} className="border border-white/10 px-3 py-1.5 text-zinc-400">
                {p.toUpperCase()}: <span className="text-cyan">{n}</span>
              </span>
            ))}
          </div>
        )}

        <div className="mt-8 border border-white/10 bg-[#0b0b0d] p-6">
          <h3 className="flex items-center gap-2 font-display font-bold"><Send size={16} className="text-violet" /> {tr("بث رسالة للجميع", "Broadcast to all")}</h3>
          <div className="mt-4 flex flex-col gap-3 md:flex-row">
            <input value={msg} onChange={(e) => setMsg(e.target.value)} data-testid="broadcast-input"
              placeholder={tr("اكتب رسالتك…", "Type your message…")}
              className="flex-1 border border-white/15 bg-black px-3 py-2.5 text-sm outline-none focus:border-cyan-400" />
            <button onClick={broadcast} disabled={loading} data-testid="broadcast-send"
              className="bg-cyan px-6 py-2.5 font-semibold text-black transition-transform hover:scale-[1.02] disabled:opacity-60">
              {loading ? tr("جارٍ الإرسال…", "Sending…") : tr("إرسال", "Send")}
            </button>
          </div>
        </div>

        <div className="mt-8 border border-white/10">
          <div className="border-b border-white/10 p-4 font-display font-bold">{tr("المستخدمون", "Users")} ({users.length})</div>
          <div className="overflow-x-auto">
            <table className="w-full font-mono text-xs" data-testid="admin-users-table">
              <thead className="text-zinc-500">
                <tr className="border-b border-white/10 text-start">
                  <th className="p-3 text-start">Telegram ID</th>
                  <th className="p-3 text-start">{tr("الاسم", "Name")}</th>
                  <th className="p-3 text-start">{tr("الباقة", "Plan")}</th>
                  <th className="p-3 text-start">{tr("النقاط", "Points")}</th>
                  <th className="p-3 text-start">{tr("إحالات", "Refs")}</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u, i) => (
                  <tr key={i} className="border-b border-white/5 hover:bg-white/[0.02]">
                    <td className="p-3">{u.telegram_id}</td>
                    <td className="p-3 text-zinc-300">{u.first_name || (u.username ? "@" + u.username : "—")}</td>
                    <td className="p-3">
                      <span className={u.plan === "free" ? "text-zinc-500" : u.plan === "elite" ? "text-violet" : "text-cyan"}>{u.plan.toUpperCase()}</span>
                    </td>
                    <td className="p-3">{u.points}</td>
                    <td className="p-3">{u.ref_count}</td>
                  </tr>
                ))}
                {users.length === 0 && (
                  <tr><td colSpan={5} className="p-6 text-center text-zinc-600">{tr("لا يوجد مستخدمون بعد", "No users yet")}</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
