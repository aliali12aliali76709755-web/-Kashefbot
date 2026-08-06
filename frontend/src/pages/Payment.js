import React, { useEffect, useState } from "react";
import axios from "axios";
import { CheckCircle2, XCircle, Loader2, Send, ArrowLeft } from "lucide-react";
import { useLang } from "@/i18n";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const BOT_LINK = "https://t.me/xvcezxbot";

function Shell({ children }) {
  return (
    <div className="grain grid-bg flex min-h-screen items-center justify-center px-5">
      <div className="relative z-10 w-full max-w-md border border-white/15 bg-[#0d0d0f] p-10 text-center">
        {children}
      </div>
    </div>
  );
}

export function PaymentSuccess() {
  const { tr } = useLang();
  const [state, setState] = useState("checking"); // checking | paid | timeout
  const [tries, setTries] = useState(0);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const sid = params.get("session_id");
    if (!sid) { setState("timeout"); return; }
    let cancelled = false;
    const poll = async (n) => {
      if (cancelled) return;
      if (n > 8) { setState("timeout"); return; }
      try {
        const r = await axios.get(`${API}/payments/status/${sid}`);
        if (r.data.payment_status === "paid") { setState("paid"); return; }
      } catch {}
      setTries(n);
      setTimeout(() => poll(n + 1), 2000);
    };
    poll(0);
    return () => { cancelled = true; };
  }, []);

  return (
    <Shell>
      {state === "checking" && (
        <>
          <Loader2 className="mx-auto animate-spin text-cyan" size={44} />
          <h1 className="mt-6 font-display text-2xl font-black">{tr("جارٍ تأكيد الدفع…", "Confirming payment…")}</h1>
          <p className="mt-2 font-mono text-xs text-zinc-500">{tr("لحظات من فضلك", "Please wait a moment")} ({tries})</p>
        </>
      )}
      {state === "paid" && (
        <>
          <CheckCircle2 className="mx-auto text-emerald-400" size={52} />
          <h1 className="mt-6 font-display text-2xl font-black">{tr("تم الدفع بنجاح! 🎉", "Payment successful! 🎉")}</h1>
          <p className="mt-3 text-zinc-400">{tr("تم تفعيل اشتراكك تلقائياً على البوت.", "Your subscription is now active on the bot.")}</p>
          <a href={BOT_LINK} className="mt-8 inline-flex items-center gap-2 bg-cyan px-6 py-3 font-semibold text-black transition-transform hover:scale-[1.03]">
            <Send size={17} /> {tr("العودة إلى البوت", "Back to the bot")}
          </a>
        </>
      )}
      {state === "timeout" && (
        <>
          <Loader2 className="mx-auto text-yellow-400" size={44} />
          <h1 className="mt-6 font-display text-2xl font-black">{tr("قيد المعالجة", "Processing")}</h1>
          <p className="mt-3 text-zinc-400">{tr("قد يستغرق التفعيل دقيقة. تحقّق من البوت عبر /me.", "Activation may take a minute. Check the bot via /me.")}</p>
          <a href={BOT_LINK} className="mt-8 inline-flex items-center gap-2 border border-white/20 px-6 py-3 font-semibold hover:text-cyan-400">
            <Send size={17} /> {tr("فتح البوت", "Open bot")}
          </a>
        </>
      )}
    </Shell>
  );
}

export function PaymentCancel() {
  const { tr } = useLang();
  return (
    <Shell>
      <XCircle className="mx-auto text-red-400" size={52} />
      <h1 className="mt-6 font-display text-2xl font-black">{tr("أُلغيت العملية", "Payment cancelled")}</h1>
      <p className="mt-3 text-zinc-400">{tr("لم يتم خصم أي مبلغ. يمكنك المحاولة مجدداً في أي وقت.", "No charge was made. You can try again anytime.")}</p>
      <a href="/#pricing" className="mt-8 inline-flex items-center gap-2 border border-white/20 px-6 py-3 font-semibold hover:text-cyan-400">
        <ArrowLeft size={17} className="rtl:-scale-x-100" /> {tr("العودة للأسعار", "Back to pricing")}
      </a>
    </Shell>
  );
}
